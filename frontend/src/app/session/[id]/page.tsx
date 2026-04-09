"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CommentsSection } from "@/components/CommentsSection";
// SourcesPanel removed — sources are accessible via individual claim cards
import { VideoPlayer, type VideoPlayerHandle } from "@/components/VideoPlayer";
import { useAuth } from "@/context/AuthContext";

export interface TranscriptSegment {
  segment_id: string;
  speaker_label: string | null;
  text: string;
  start_ms: number;
  end_ms: number;
}

export interface ClaimSummary {
  claim_id: string;
  claim_text: string;
  claim_type: string;
  speaker: { speaker_label: string; party?: string | null; role?: string | null } | null;
  timestamp_range: { start_ms: number; end_ms: number };
  verdict: {
    label: string;
    confidence: number | null;
    rationale_summary: string | null;
  } | null;
  source_count: number;
}

export interface SessionDetail {
  session_id: string;
  title: string | null;
  description: string | null;
  status: string;
  channel_name: string | null;
  broadcast_date: string | null;
  duration_seconds: number | null;
  media_type: "audio" | "video";
  claims_count: number;
  speakers: string[];
  verdict_distribution: Record<string, number>;
  created_at: string;
  completed_at: string | null;
}

function highlightText(text: string, query: string) {
  const trimmedQuery = query.trim();
  if (!trimmedQuery) return text;

  const escapedQuery = trimmedQuery.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const regex = new RegExp(`(${escapedQuery})`, "gi");
  const parts = text.split(regex);

  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <mark key={i} className="rounded bg-yellow-300/70 px-0.5">
        {part}
      </mark>
    ) : (
      part
    )
  );
}

const VERDICT_FILTERS = [
  "ALL",
  "TRUE",
  "MOSTLY_TRUE",
  "HALF_TRUE",
  "MOSTLY_FALSE",
  "FALSE",
  "UNVERIFIED",
] as const;

const VERDICT_STYLES: Record<string, string> = {
  TRUE: "bg-green-100 text-green-800",
  MOSTLY_TRUE: "bg-lime-100 text-lime-800",
  HALF_TRUE: "bg-yellow-100 text-yellow-800",
  MOSTLY_FALSE: "bg-orange-100 text-orange-800",
  FALSE: "bg-red-100 text-red-800",
  UNVERIFIED: "bg-slate-100 text-slate-700",
};

export default function SessionDetailPage() {
  const params = useParams<{ id: string | string[] }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, token } = useAuth();
  const rawId = params?.id;
  const sessionId = Array.isArray(rawId) ? rawId[0] : rawId;
  const linkedClaimId = searchParams.get("claim");
  const linkedTimeMs = Number(searchParams.get("t") ?? "0");

  const playerRef = useRef<VideoPlayerHandle>(null);
  const transcriptContainerRef = useRef<HTMLDivElement>(null);
  const transcriptNodeMapRef = useRef(new Map<string, HTMLSpanElement | null>());
  const claimNodeMapRef = useRef(new Map<string, HTMLElement | null>());
  const initialLinkHandledRef = useRef(false);
  const currentTimeMsRef = useRef(0);
  const lastWatchPostedSecondsRef = useRef(0);
  const savedLookupAbortRef = useRef(false);

  const [session, setSession] = useState<SessionDetail | null>(null);
  const [transcript, setTranscript] = useState<TranscriptSegment[]>([]);
  const [claims, setClaims] = useState<ClaimSummary[]>([]);
  const [activeSegmentId, setActiveSegmentId] = useState<string | null>(null);
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null);
  const [expandedClaimSources, setExpandedClaimSources] = useState<Record<string, { loading: boolean; sources: Array<{ source_id: string; url: string; title: string; publisher: string | null }> } | undefined>>({});
  const [currentTimeMs, setCurrentTimeMs] = useState(0);
  const [verdictFilter, setVerdictFilter] =
    useState<(typeof VERDICT_FILTERS)[number]>("ALL");
  const [speakerFilter, setSpeakerFilter] = useState<string | null>(null);
  const [transcriptSearch, setTranscriptSearch] = useState("");
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [shareToast, setShareToast] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [likeCount, setLikeCount] = useState(0);
  const [likedByMe, setLikedByMe] = useState(false);
  const [savedByMe, setSavedByMe] = useState(false);
  const [resumeTime, setResumeTime] = useState<number | null>(null);
  const [showResumeBanner, setShowResumeBanner] = useState(false);
  const [likePending, setLikePending] = useState(false);
  const [savePending, setSavePending] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [isEditingMeta, setIsEditingMeta] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) return;

    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);

      try {
        const [sessionRes, transcriptRes, claimsRes] = await Promise.all([
          fetch(`/api/sessions/${sessionId}`),
          fetch(`/api/sessions/${sessionId}/transcript`),
          fetch(`/api/sessions/${sessionId}/claims`),
        ]);

        if (!sessionRes.ok || !transcriptRes.ok || !claimsRes.ok) {
          throw new Error("Unable to load session");
        }

        const [sessionData, transcriptData, claimsData] = await Promise.all([
          sessionRes.json(),
          transcriptRes.json(),
          claimsRes.json(),
        ]);

        if (cancelled) return;

        setSession(sessionData);
        setTranscript(transcriptData);
        setClaims(claimsData.results || []);

        // Increment view count (fire and forget)
        fetch(`/api/sessions/${sessionId}/view`, { method: "POST" }).catch(() => {});
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Unable to load session");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    load();

    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Highlight only — no auto-scroll for transcript
  // useEffect removed: transcript should not follow playback

  useEffect(() => {
    if (!selectedClaimId) return;
    const node = claimNodeMapRef.current.get(selectedClaimId);
    node?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedClaimId]);

  useEffect(() => {
    if (initialLinkHandledRef.current || loading) {
      return;
    }

    if (!linkedClaimId && !(Number.isFinite(linkedTimeMs) && linkedTimeMs > 0)) {
      initialLinkHandledRef.current = true;
      return;
    }

    initialLinkHandledRef.current = true;

    if (linkedClaimId) {
      setSelectedClaimId(linkedClaimId);
    }

    if (Number.isFinite(linkedTimeMs) && linkedTimeMs > 0) {
      window.setTimeout(() => {
        playerRef.current?.seekTo(linkedTimeMs);
        setCurrentTimeMs(linkedTimeMs);
      }, 50);
    }
  }, [linkedClaimId, linkedTimeMs, loading]);

  useEffect(() => {
    if (!shareToast) return;

    const timeout = window.setTimeout(() => setShareToast(null), 1800);
    return () => window.clearTimeout(timeout);
  }, [shareToast]);

  useEffect(() => {
    currentTimeMsRef.current = currentTimeMs;
  }, [currentTimeMs]);

  useEffect(() => {
    if (!token || !session) {
      setResumeTime(null);
      setShowResumeBanner(false);
      return;
    }

    fetch(`/api/sessions/${session.session_id}/watch`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data && data.progress_seconds > 30) {
          setResumeTime(data.progress_seconds);
          setShowResumeBanner(true);
          return;
        }

        setResumeTime(null);
        setShowResumeBanner(false);
      })
      .catch(() => {});
  }, [token, session]);

  const authHeaders = useMemo(
    () =>
      token
        ? {
            Authorization: `Bearer ${token}`,
          }
        : undefined,
    [token]
  );

  const requireAuth = useCallback(() => {
    if (user && token) {
      return true;
    }

    router.push(`/login?next=${encodeURIComponent(`/session/${sessionId}`)}`);
    return false;
  }, [router, sessionId, token, user]);

  useEffect(() => {
    if (!sessionId) return;

    let cancelled = false;
    savedLookupAbortRef.current = false;

    async function loadPreferences() {
      try {
        const likeResponse = await fetch(`/api/sessions/${sessionId}/like-count`, {
          headers: authHeaders,
        });

        if (!likeResponse.ok) {
          throw new Error("Unable to load likes");
        }

        const likeData = await likeResponse.json();
        if (!cancelled) {
          setLikeCount(likeData.count ?? 0);
          setLikedByMe(Boolean(likeData.liked_by_me));
        }

        if (!token || !user) {
          if (!cancelled) {
            setSavedByMe(false);
          }
          return;
        }

        const isSaved = await lookupSavedState(sessionId, token, () => cancelled || savedLookupAbortRef.current);
        if (!cancelled) {
          setSavedByMe(isSaved);
        }
      } catch {
        if (!cancelled) {
          setLikeCount(0);
          setLikedByMe(false);
          setSavedByMe(false);
        }
      }
    }

    void loadPreferences();

    return () => {
      cancelled = true;
      savedLookupAbortRef.current = true;
    };
  }, [authHeaders, sessionId, token, user]);

  const sendWatchProgress = useCallback(async () => {
    if (!sessionId || !token) return;

    const progressSeconds = Math.floor(currentTimeMsRef.current / 1000);
    if (progressSeconds <= 0 || progressSeconds <= lastWatchPostedSecondsRef.current) {
      return;
    }

    try {
      const response = await fetch(`/api/sessions/${sessionId}/watch`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ progress_seconds: progressSeconds }),
      });

      if (response.ok) {
        lastWatchPostedSecondsRef.current = progressSeconds;
      }
    } catch {
      // Ignore watch-history failures during playback.
    }
  }, [sessionId, token]);

  useEffect(() => {
    if (!isPlaying || !user || !token || !sessionId) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void sendWatchProgress();
    }, 30_000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [isPlaying, sendWatchProgress, sessionId, token, user]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || target?.isContentEditable) {
        return;
      }

      switch (e.key) {
        case " ":
        case "k":
          e.preventDefault();
          playerRef.current?.togglePlayback();
          break;
        case "j":
          e.preventDefault();
          playerRef.current?.seekRelative(-10000);
          break;
        case "l":
          e.preventDefault();
          playerRef.current?.seekRelative(10000);
          break;
        case "ArrowLeft":
          e.preventDefault();
          playerRef.current?.seekRelative(-5000);
          break;
        case "ArrowRight":
          e.preventDefault();
          playerRef.current?.seekRelative(5000);
          break;
        case "ArrowUp":
          e.preventDefault();
          playerRef.current?.adjustVolume(0.05);
          break;
        case "ArrowDown":
          e.preventDefault();
          playerRef.current?.adjustVolume(-0.05);
          break;
        case "m":
          e.preventDefault();
          playerRef.current?.toggleMute();
          break;
        // F key reserved for browser Ctrl+F find
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const speakers = useMemo(
    () =>
      Array.from(
        new Set(
          claims
            .map((claim) => claim.speaker?.speaker_label)
            .filter((speaker): speaker is string => Boolean(speaker))
        )
      ),
    [claims]
  );

  const filteredClaims = useMemo(
    () =>
      claims.filter((claim) => {
        const matchesVerdict =
          verdictFilter === "ALL" || (claim.verdict?.label || "UNVERIFIED") === verdictFilter;
        const claimSpeaker = claim.speaker?.speaker_label || null;
        const matchesSpeaker = !speakerFilter || claimSpeaker === speakerFilter;
        return matchesVerdict && matchesSpeaker;
      }),
    [claims, speakerFilter, verdictFilter]
  );

  const filteredTranscript = useMemo(() => {
    if (!transcriptSearch.trim()) return transcript;
    const query = transcriptSearch.toLowerCase();
    return transcript.filter((seg) => seg.text.toLowerCase().includes(query));
  }, [transcript, transcriptSearch]);

  const groupedTranscript = useMemo(() => {
    const groups: { speaker: string | null; segments: TranscriptSegment[] }[] = [];

    for (const seg of filteredTranscript) {
      const lastGroup = groups[groups.length - 1];

      if (lastGroup && lastGroup.speaker === seg.speaker_label) {
        lastGroup.segments.push(seg);
      } else {
        groups.push({ speaker: seg.speaker_label, segments: [seg] });
      }
    }

    return groups;
  }, [filteredTranscript]);

  function handlePlayerTimeUpdate(nextMs: number) {
    setCurrentTimeMs(nextMs);

    const activeSegment =
      transcript.find(
        (segment) => nextMs >= segment.start_ms && nextMs < segment.end_ms
      ) || transcript[transcript.length - 1] || null;

    if (activeSegment?.segment_id !== activeSegmentId) {
      setActiveSegmentId(activeSegment?.segment_id || null);
    }
  }

  function handleTranscriptSeek(segment: TranscriptSegment) {
    playerRef.current?.seekTo(segment.start_ms);
    setCurrentTimeMs(segment.start_ms);
    setActiveSegmentId(segment.segment_id);
  }

  function exportTranscript(format: "txt" | "srt") {
    setShowExportMenu(false);

    let content = "";
    const filename = `transcript-${sessionId}`;

    if (format === "txt") {
      content = transcript
        .map((seg) => {
          const time = formatExportTimestamp(seg.start_ms);
          const speaker = seg.speaker_label || "Speaker";
          return `[${time}] ${speaker}: ${seg.text}`;
        })
        .join("\n");
    } else {
      content = transcript
        .map((seg, i) => {
          const startTime = formatSrtTime(seg.start_ms);
          const endTime = formatSrtTime(seg.end_ms);
          return `${i + 1}\n${startTime} --> ${endTime}\n${seg.speaker_label ? `${seg.speaker_label}: ` : ""}${seg.text}\n`;
        })
        .join("\n");
    }

    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename}.${format}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function handleClaimSeek(claim: ClaimSummary) {
    setSelectedClaimId(claim.claim_id);
    setCurrentTimeMs(claim.timestamp_range.start_ms);
    playerRef.current?.seekTo(claim.timestamp_range.start_ms);
  }

  async function handleShare() {
    if (typeof window === "undefined") return;

    try {
      const shareUrl = new URL(window.location.href);
      const selectedClaim = claims.find((claim) => claim.claim_id === selectedClaimId) || null;
      const shareTime = selectedClaim?.timestamp_range.start_ms ?? currentTimeMs;

      if (selectedClaimId) {
        shareUrl.searchParams.set("claim", selectedClaimId);
      } else {
        shareUrl.searchParams.delete("claim");
      }

      if (shareTime > 0) {
        shareUrl.searchParams.set("t", String(Math.round(shareTime)));
      } else {
        shareUrl.searchParams.delete("t");
      }

      await navigator.clipboard.writeText(shareUrl.toString());
      setShareToast("Copied!");
    } catch {
      setShareToast("Copy failed");
    }
  }

  async function handleLikeToggle() {
    if (!requireAuth() || !sessionId) return;

    setLikePending(true);
    setActionError(null);

    try {
      const response = await fetch(`/api/sessions/${sessionId}/like`, {
        method: likedByMe ? "DELETE" : "POST",
        headers: authHeaders,
      });

      if (!response.ok) {
        throw new Error("Unable to update like");
      }

      setLikedByMe((current) => !current);
      setLikeCount((current) => Math.max(current + (likedByMe ? -1 : 1), 0));
    } catch (toggleError) {
      setActionError(toggleError instanceof Error ? toggleError.message : "Unable to update like");
    } finally {
      setLikePending(false);
    }
  }

  async function handleSaveToggle() {
    if (!requireAuth() || !sessionId) return;

    setSavePending(true);
    setActionError(null);

    try {
      const response = await fetch(`/api/sessions/${sessionId}/save`, {
        method: savedByMe ? "DELETE" : "POST",
        headers: authHeaders,
      });

      if (!response.ok) {
        throw new Error("Unable to update saved state");
      }

      setSavedByMe((current) => !current);
    } catch (toggleError) {
      setActionError(
        toggleError instanceof Error ? toggleError.message : "Unable to update saved state"
      );
    } finally {
      setSavePending(false);
    }
  }

  async function handleDelete() {
    if (!token) return;

    try {
      const res = await fetch(`/api/sessions/${sessionId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        window.location.href = "/";
      }
    } catch {}
  }

  const handleSaveMeta = async () => {
    if (!token || !session) return;
    try {
      const res = await fetch(`/api/sessions/${session.session_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ title: editTitle, description: editDescription }),
      });
      if (res.ok) {
        const data = await res.json();
        setSession({
          ...session,
          title: data.title ?? null,
          description: data.description ?? null,
        });
        setIsEditingMeta(false);
      }
    } catch {}
  };

  if (!sessionId) {
    return (
      <main className="mx-auto max-w-[1440px] px-4 py-8 sm:px-6">
        <p className="text-sm text-red-600">Session ID is missing.</p>
      </main>
    );
  }

  if (loading) {
    return (
      <main className="mx-auto max-w-[1440px] px-4 py-8 sm:px-6">
        <Link href="/" className="text-sm text-gray-500 transition-colors hover:text-gray-900">
          ← Back to home
        </Link>
        <div className="mt-6 rounded-2xl bg-white p-10 shadow-sm ring-1 ring-black/5">
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-gray-200 border-t-gray-900" />
          <p className="mt-4 text-center text-sm text-gray-500">Loading session...</p>
        </div>
      </main>
    );
  }

  if (error || !session) {
    return (
      <main className="mx-auto max-w-[1440px] px-4 py-8 sm:px-6">
        <Link href="/" className="text-sm text-gray-500 transition-colors hover:text-gray-900">
          ← Back to home
        </Link>
        <div className="mt-6 rounded-2xl border border-red-200 bg-red-50 p-8">
          <p className="font-semibold text-red-900">Session failed to load</p>
          <p className="mt-1 text-sm text-red-700">{error || "Unknown error"}</p>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6">
      <Link href="/" className="text-sm text-gray-500 transition-colors hover:text-gray-900">
        ← Back to home
      </Link>

      <div className="mt-6 flex flex-col gap-6 lg:grid lg:grid-cols-[minmax(0,1fr)_360px] lg:gap-8 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="space-y-6 sm:space-y-8">
          {showResumeBanner && resumeTime && (
            <div className="flex flex-col gap-3 rounded-2xl bg-blue-50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <span className="text-sm text-blue-800">
                Resume from {Math.floor(resumeTime / 60)}:
                {String(Math.floor(resumeTime % 60)).padStart(2, "0")}?
              </span>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setShowResumeBanner(false)}
                  className="min-h-11 rounded-full px-3 text-sm text-blue-600 transition-colors hover:bg-blue-100 hover:text-blue-800"
                >
                  Dismiss
                </button>
                <button
                  type="button"
                  onClick={() => {
                    playerRef.current?.seekTo(resumeTime * 1000);
                    setShowResumeBanner(false);
                  }}
                  className="min-h-11 rounded-full bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
                >
                  Resume
                </button>
              </div>
            </div>
          )}

          <VideoPlayer
            ref={playerRef}
            sessionId={session.session_id}
            mediaType={session.media_type}
            durationSeconds={session.duration_seconds}
            claims={claims.map((claim) => ({
              claim_id: claim.claim_id,
              start_ms: claim.timestamp_range.start_ms,
              verdict_label: claim.verdict?.label || "UNVERIFIED",
            }))}
            onTimeUpdate={handlePlayerTimeUpdate}
            onPlaybackStateChange={setIsPlaying}
            onClaimClick={(claimId) => {
              setSelectedClaimId(claimId);
            }}
          />

          <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-black/5 sm:p-6">
            <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-start gap-2">
                  {isEditingMeta ? (
                    <div className="flex-1 space-y-3">
                      <input
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        className="w-full rounded-2xl border border-gray-300 px-3 py-2 text-xl font-bold transition-colors focus:border-blue-500 focus:outline-none"
                        placeholder="Session title..."
                      />
                      <textarea
                        value={editDescription}
                        onChange={(e) => setEditDescription(e.target.value)}
                        className="w-full resize-none rounded-2xl border border-gray-300 px-3 py-2 text-sm transition-colors focus:border-blue-500 focus:outline-none"
                        rows={3}
                        placeholder="Add a description..."
                      />
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={handleSaveMeta}
                          className="min-h-11 rounded-full bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
                        >
                          Save
                        </button>
                        <button
                          type="button"
                          onClick={() => setIsEditingMeta(false)}
                          className="min-h-11 rounded-full px-4 py-2 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-100"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex-1">
                      <h1 className="break-words text-2xl font-bold text-gray-950 sm:text-3xl">
                        {session.title || "Untitled Session"}
                      </h1>
                      {session.description && (
                        <p className="mt-2 text-sm text-gray-600">{session.description}</p>
                      )}
                    </div>
                  )}
                  {user?.is_admin && !isEditingMeta && (
                    <button
                      type="button"
                      onClick={() => {
                        setEditTitle(session.title || "");
                        setEditDescription(session.description || "");
                        setIsEditingMeta(true);
                      }}
                      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
                      title="Edit title & description"
                    >
                      <svg
                        className="h-4 w-4"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"
                        />
                      </svg>
                    </button>
                  )}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-gray-500">
                  <span>{session.channel_name || "Unknown channel"}</span>
                  <span className="hidden sm:inline">•</span>
                  <span>{formatLongDate(session.created_at)}</span>
                  <span className="hidden sm:inline">•</span>
                  <span>{session.claims_count} claims checked</span>
                </div>
              </div>

              <div className="flex w-full flex-wrap items-center gap-3 lg:w-auto lg:justify-end">
                <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-gray-700">
                  {session.status}
                </span>
                {user?.is_admin && (
                  <>
                    <button
                      type="button"
                      onClick={() => setShowDeleteConfirm(true)}
                      className="min-h-11 rounded-full bg-red-50 px-4 py-2 text-xs font-semibold text-red-600 transition-colors hover:bg-red-100"
                    >
                      Delete
                    </button>

                    {showDeleteConfirm && (
                      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
                        <div className="mx-4 max-w-sm rounded-2xl bg-white p-6 shadow-xl">
                          <h3 className="text-lg font-semibold text-gray-950">
                            Delete session?
                          </h3>
                          <p className="mt-2 text-sm text-gray-600">
                            This will permanently delete the session, all claims, verdicts, and
                            comments. This cannot be undone.
                          </p>
                          <div className="mt-4 flex flex-wrap justify-end gap-3">
                            <button
                              type="button"
                              onClick={() => setShowDeleteConfirm(false)}
                              className="min-h-11 rounded-full px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-100"
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              onClick={handleDelete}
                              className="min-h-11 rounded-full bg-red-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-700"
                            >
                              Delete permanently
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                  </>
                )}
                <button
                  type="button"
                  onClick={handleShare}
                  className="min-h-11 rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-900 shadow-sm transition-colors hover:bg-gray-50"
                >
                  Share
                </button>
              </div>
            </div>

            <div className="mt-5 flex flex-col gap-4 rounded-2xl bg-gray-50 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-4">
                <div className="flex -space-x-2">
                  {(session.speakers.length > 0 ? session.speakers : [session.channel_name || "PF"])
                    .slice(0, 3)
                    .map((speaker) => (
                      <div
                        key={speaker}
                        className="flex h-11 w-11 items-center justify-center rounded-full border-2 border-white bg-gray-200 text-sm font-semibold text-gray-700"
                      >
                        {initialsFor(speaker)}
                      </div>
                    ))}
                </div>
                <div>
                  <p className="font-semibold text-gray-950">
                    {session.channel_name || "Polyfacts session"}
                  </p>
                  <p className="text-sm text-gray-500">
                    {session.speakers.length > 0
                      ? `${session.speakers.length} speakers identified`
                      : "Speaker labels are still processing"}
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                {(session.speakers.length > 0 ? session.speakers : ["No speaker labels"])
                  .slice(0, 4)
                  .map((speaker) => (
                    <span
                      key={speaker}
                      className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-700"
                    >
                      {speaker}
                    </span>
                  ))}
              </div>
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => void handleLikeToggle()}
                disabled={likePending}
                className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
                  likedByMe
                    ? "border-red-200 bg-red-50 text-red-700"
                    : "border-gray-300 bg-white text-gray-800 hover:border-gray-400 hover:bg-gray-50"
                } disabled:cursor-not-allowed disabled:opacity-60`}
              >
                <svg
                  viewBox="0 0 24 24"
                  className={`h-4 w-4 ${likedByMe ? "fill-current" : "fill-none stroke-current"}`}
                  aria-hidden="true"
                >
                  <path
                    d="M12 21l-1.45-1.32C5.4 15.04 2 11.95 2 8.15 2 5.06 4.42 3 7.4 3c1.74 0 3.41.81 4.6 2.09C13.19 3.81 14.86 3 16.6 3 19.58 3 22 5.06 22 8.15c0 3.8-3.4 6.89-8.55 11.54L12 21Z"
                    strokeWidth={1.8}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                <span>{likedByMe ? "Liked" : "Like"}</span>
                <span className="text-xs text-gray-500">{likeCount}</span>
              </button>

              <button
                type="button"
                onClick={() => void handleSaveToggle()}
                disabled={savePending}
                className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
                  savedByMe
                    ? "border-gray-900 bg-gray-900 text-white"
                    : "border-gray-300 bg-white text-gray-800 hover:border-gray-400 hover:bg-gray-50"
                } disabled:cursor-not-allowed disabled:opacity-60`}
              >
                <svg
                  viewBox="0 0 24 24"
                  className={`h-4 w-4 ${savedByMe ? "fill-current" : "fill-none stroke-current"}`}
                  aria-hidden="true"
                >
                  <path
                    d="M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1Z"
                    strokeWidth={1.8}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                <span>{savedByMe ? "Saved" : "Save"}</span>
              </button>

              {!user && (
                <p className="text-sm text-gray-500">
                  Sign in to keep a library and sync watch history.
                </p>
              )}
            </div>

            {actionError && <p className="mt-3 text-sm text-red-600">{actionError}</p>}
          </section>

          {/* Sources accessible via individual claim cards */}

          <section className="w-full rounded-2xl bg-white p-4 shadow-sm ring-1 ring-black/5 sm:p-6">
            <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
              <h2 className="text-lg font-semibold text-gray-950">Transcript</h2>
              <div className="relative w-full sm:w-auto">
                <button
                  type="button"
                  onClick={() => setShowExportMenu(!showExportMenu)}
                  className="min-h-11 w-full rounded-full border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-50 sm:w-auto sm:px-3 sm:py-1.5 sm:text-xs"
                >
                  Export
                </button>
                {showExportMenu && (
                  <div className="absolute right-0 top-full z-10 mt-1 w-40 rounded-2xl border border-gray-200 bg-white py-1 shadow-lg">
                    <button
                      type="button"
                      onClick={() => exportTranscript("txt")}
                      className="block w-full px-4 py-2 text-left text-sm text-gray-700 transition-colors hover:bg-gray-50"
                    >
                      Download .txt
                    </button>
                    <button
                      type="button"
                      onClick={() => exportTranscript("srt")}
                      className="block w-full px-4 py-2 text-left text-sm text-gray-700 transition-colors hover:bg-gray-50"
                    >
                      Download .srt
                    </button>
                  </div>
                )}
              </div>
              <div className="relative w-full flex-1 sm:max-w-xs">
                <input
                  type="text"
                  value={transcriptSearch}
                  onChange={(e) => setTranscriptSearch(e.target.value)}
                  placeholder="Search transcript..."
                  className="min-h-11 w-full rounded-2xl border border-gray-200 bg-gray-50 px-3 py-2 pl-8 text-sm transition-colors focus:border-blue-500 focus:bg-white focus:outline-none"
                />
                <svg
                  className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                  />
                </svg>
                {transcriptSearch && (
                  <button
                    type="button"
                    onClick={() => setTranscriptSearch("")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 transition-colors hover:text-gray-600"
                  >
                    <svg
                      className="h-3.5 w-3.5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                )}
              </div>
              {transcriptSearch && (
                <span className="text-xs text-gray-500 sm:ml-auto">
                  {filteredTranscript.length} match{filteredTranscript.length !== 1 ? "es" : ""}
                </span>
              )}
            </div>

            <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="mt-1 text-sm text-gray-500">
                  Click any text to seek the player.
                </p>
              </div>
              <p className="text-sm text-gray-500">{transcript.length} segments</p>
            </div>

            <div ref={transcriptContainerRef} className="max-h-[60vh] overflow-y-auto pr-1 sm:max-h-[720px]">
              {groupedTranscript.length === 0 && (
                <p className="text-sm text-gray-500">No transcript available.</p>
              )}

              {groupedTranscript.map((group, gi) => (
                <div key={gi} className="mb-4">
                  <div className="mb-1 flex items-center gap-2">
                    {group.speaker && (
                      <span className="text-xs font-semibold text-gray-700">{group.speaker}</span>
                    )}
                    <span className="text-xs font-mono text-gray-400">
                      {formatTimestamp(group.segments[0].start_ms)}
                    </span>
                  </div>

                  <p className="text-sm leading-7 text-gray-800">
                    {group.segments.map((seg) => {
                      const isActive = seg.segment_id === activeSegmentId;

                      return (
                        <span
                          key={seg.segment_id}
                          ref={(node) => {
                            transcriptNodeMapRef.current.set(seg.segment_id, node);
                          }}
                          onClick={() => handleTranscriptSeek(seg)}
                          className={`cursor-pointer rounded px-0.5 transition-colors ${
                            isActive
                              ? "bg-yellow-200/70 text-gray-950"
                              : "hover:bg-gray-100"
                          }`}
                        >
                          {highlightText(seg.text, transcriptSearch)}{" "}
                        </span>
                      );
                    })}
                  </p>
                </div>
              ))}
            </div>
          </section>

          <div className="w-full">
            <CommentsSection sessionId={session.session_id} />
          </div>
        </div>

        <aside className="w-full max-h-[50vh] overflow-y-auto overflow-x-hidden lg:sticky lg:top-20 lg:self-start lg:max-h-[calc(100vh-6rem)]">
          <section className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-black/5 sm:p-5">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-gray-950">
                  {session.claims_count} claims fact-checked
                </h2>
                <p className="mt-1 text-sm text-gray-500">Jump to a claim moment or scan verdicts.</p>
              </div>
              <span className="text-sm text-gray-500">{filteredClaims.length}</span>
            </div>

            <div className="mb-4 flex flex-wrap gap-2">
              {VERDICT_FILTERS.map((filter) => (
                <button
                  key={filter}
                  type="button"
                  onClick={() => setVerdictFilter(filter)}
                  className={`rounded-full px-3 py-1.5 text-xs font-semibold transition-colors ${
                    verdictFilter === filter
                      ? "bg-black text-white"
                      : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                  }`}
                >
                  {filter.replaceAll("_", " ")}
                </button>
              ))}
            </div>

            <div className="mb-4">
              <label className="flex flex-col gap-2 text-sm text-gray-500">
                <span>Speaker</span>
                <select
                  value={speakerFilter ?? ""}
                  onChange={(event) => setSpeakerFilter(event.target.value || null)}
                  className="h-10 rounded-full border border-gray-300 bg-white px-4 text-sm font-medium text-gray-900 transition-colors focus:border-gray-400 focus:outline-none"
                >
                  <option value="">All speakers</option>
                  {speakers.map((speaker) => (
                    <option key={speaker} value={speaker}>
                      {speaker}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="space-y-2.5">
              {filteredClaims.length === 0 && (
                <p className="text-sm text-gray-500">No claims match the current filters.</p>
              )}

              {filteredClaims.map((claim) => {
                const verdictLabel = claim.verdict?.label || "UNVERIFIED";
                const isSelected = claim.claim_id === selectedClaimId;

                const claimSources = expandedClaimSources[claim.claim_id];
                const sourcesExpanded = !!claimSources;

                const toggleSources = async (e: React.MouseEvent) => {
                  e.stopPropagation();
                  if (sourcesExpanded) {
                    setExpandedClaimSources((prev) => {
                      const next = { ...prev };
                      delete next[claim.claim_id];
                      return next;
                    });
                    return;
                  }
                  setExpandedClaimSources((prev) => ({
                    ...prev,
                    [claim.claim_id]: { loading: true, sources: [] },
                  }));
                  try {
                    const res = await fetch(`/api/claims/${claim.claim_id}`);
                    if (res.ok) {
                      const data = await res.json();
                      const sources = (data.sources || []).map((ep: Record<string, unknown>) => ({
                        source_id: ep.source_id || "",
                        url: (ep.url as string) || "",
                        title: (ep.title as string) || (ep.url as string) || "Source",
                        publisher: (ep.publisher as string) || null,
                      }));
                      setExpandedClaimSources((prev) => ({
                        ...prev,
                        [claim.claim_id]: { loading: false, sources },
                      }));
                    }
                  } catch {
                    setExpandedClaimSources((prev) => ({
                      ...prev,
                      [claim.claim_id]: { loading: false, sources: [] },
                    }));
                  }
                };

                return (
                  <div
                    key={claim.claim_id}
                    ref={(node) => {
                      claimNodeMapRef.current.set(claim.claim_id, node);
                    }}
                    className={`rounded-2xl border p-3 transition-all duration-200 ${
                      isSelected
                        ? "border-red-200 bg-red-50 shadow-sm"
                        : "border-gray-200 bg-white hover:border-gray-300 hover:shadow-sm"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => handleClaimSeek(claim)}
                      className="block w-full text-left"
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${
                            VERDICT_STYLES[verdictLabel] || "bg-slate-100 text-slate-700"
                          }`}
                        >
                          {verdictLabel.replaceAll("_", " ")}
                        </span>
                        <span className="text-xs font-mono text-gray-500">
                          {formatTimestamp(claim.timestamp_range.start_ms)}
                        </span>
                      </div>

                      <p className="mt-2 text-[13px] font-medium leading-5 text-gray-900">
                        {claim.claim_text}
                      </p>

                      {claim.verdict?.rationale_summary && (
                        <p className="mt-1.5 text-xs leading-5 text-gray-600">
                          {claim.verdict.rationale_summary}
                        </p>
                      )}
                    </button>

                    <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                      {claim.speaker?.speaker_label && <span>{claim.speaker.speaker_label}</span>}
                      {claim.speaker?.speaker_label && <span>•</span>}
                      <button
                        type="button"
                        onClick={toggleSources}
                        className="text-blue-600 hover:text-blue-800 font-medium"
                      >
                        {sourcesExpanded ? "Hide sources" : `${claim.source_count} sources`}
                      </button>
                    </div>

                    {sourcesExpanded && (
                      <div className="mt-2 border-t border-gray-100 pt-2">
                        {claimSources.loading ? (
                          <p className="text-xs text-gray-400">Loading sources...</p>
                        ) : claimSources.sources.length === 0 ? (
                          <p className="text-xs text-gray-400">No sources found.</p>
                        ) : (
                          <ul className="space-y-1.5">
                            {claimSources.sources.map((src, i) => (
                              <li key={src.source_id || i}>
                                <a
                                  href={src.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-xs text-blue-600 hover:text-blue-800 hover:underline leading-4"
                                >
                                  {src.title}
                                </a>
                                {src.publisher && (
                                  <span className="text-[10px] text-gray-400 ml-1">— {src.publisher}</span>
                                )}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        </aside>
      </div>

      {shareToast && (
        <div className="fixed bottom-5 right-5 rounded-full bg-black px-4 py-2 text-sm font-medium text-white shadow-lg">
          {shareToast}
        </div>
      )}
    </main>
  );
}

function initialsFor(input: string) {
  return input
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

function formatTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${seconds
      .toString()
      .padStart(2, "0")}`;
  }

  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function formatExportTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(
    seconds
  ).padStart(2, "0")}`;
}

function formatSrtTime(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const millis = ms % 1000;

  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(
    seconds
  ).padStart(2, "0")},${String(millis).padStart(3, "0")}`;
}

function formatLongDate(input: string): string {
  return new Date(input).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

async function lookupSavedState(
  sessionId: string,
  token: string,
  shouldAbort: () => boolean
): Promise<boolean> {
  const perPage = 100;

  for (let page = 1; page <= 10; page += 1) {
    if (shouldAbort()) {
      return false;
    }

    const response = await fetch(
      `/api/me/saved?${new URLSearchParams({
        page: String(page),
        per_page: String(perPage),
      }).toString()}`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    );

    if (!response.ok) {
      throw new Error("Unable to load saved sessions");
    }

    const sessions: Array<{ session_id: string }> = await response.json();
    if (sessions.some((savedSession) => savedSession.session_id === sessionId)) {
      return true;
    }

    if (sessions.length < perPage) {
      return false;
    }
  }

  return false;
}
