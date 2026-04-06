"use client";

import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { SessionCard, type SessionSummaryCard } from "@/components/SessionCard";
import { useAuth } from "@/context/AuthContext";

type LibraryTab = "liked" | "saved" | "history";

interface HistorySession extends SessionSummaryCard {
  last_watched_at: string;
  progress_seconds: number;
}

interface TabState<T> {
  items: T[];
  page: number;
  hasMore: boolean;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
}

type AnyLibraryItem = SessionSummaryCard | HistorySession;
type AnyLibraryState = TabState<AnyLibraryItem>;

const PAGE_SIZE = 12;

const TAB_META: Record<LibraryTab, { label: string; endpoint: string; empty: string }> = {
  liked: {
    label: "Liked",
    endpoint: "/api/me/liked",
    empty: "You have not liked any sessions yet.",
  },
  saved: {
    label: "Saved",
    endpoint: "/api/me/saved",
    empty: "You have not saved any sessions yet.",
  },
  history: {
    label: "History",
    endpoint: "/api/me/history",
    empty: "Your watch history will appear here after you start watching sessions.",
  },
};

const EMPTY_STATE = {
  items: [],
  page: 0,
  hasMore: true,
  loading: false,
  loadingMore: false,
  error: null,
};

export default function LibraryPage() {
  const router = useRouter();
  const { user, token, loading } = useAuth();
  const [activeTab, setActiveTab] = useState<LibraryTab>("liked");
  const [likedState, setLikedState] = useState<TabState<SessionSummaryCard>>(EMPTY_STATE);
  const [savedState, setSavedState] = useState<TabState<SessionSummaryCard>>(EMPTY_STATE);
  const [historyState, setHistoryState] = useState<TabState<HistorySession>>(EMPTY_STATE);

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/login?next=/library");
    }
  }, [loading, router, user]);

  const authHeaders = useMemo(
    () =>
      token
        ? {
            Authorization: `Bearer ${token}`,
          }
        : undefined,
    [token]
  );

  useEffect(() => {
    if (!user || !token) return;

    if (activeTab === "liked" && likedState.items.length === 0 && !likedState.loading) {
      void loadTab("liked", 1);
    }

    if (activeTab === "saved" && savedState.items.length === 0 && !savedState.loading) {
      void loadTab("saved", 1);
    }

    if (activeTab === "history" && historyState.items.length === 0 && !historyState.loading) {
      void loadTab("history", 1);
    }
  }, [
    activeTab,
    historyState.items.length,
    historyState.loading,
    likedState.items.length,
    likedState.loading,
    savedState.items.length,
    savedState.loading,
    token,
    user,
  ]);

  async function loadTab(tab: LibraryTab, page: number) {
    const isLoadMore = page > 1;
    const updater = getTabSetter(tab);

    updater((current) => ({
      ...current,
      loading: !isLoadMore,
      loadingMore: isLoadMore,
      error: null,
    }));

    try {
      const response = await fetch(
        `${TAB_META[tab].endpoint}?${new URLSearchParams({
          page: String(page),
          per_page: String(PAGE_SIZE),
        }).toString()}`,
        {
          headers: authHeaders,
        }
      );

      if (!response.ok) {
        throw new Error(tab === "history" ? "Unable to load watch history" : "Unable to load library");
      }

      const data = await response.json();
      updater((current) => ({
        ...current,
        items: isLoadMore ? [...current.items, ...data] : data,
        page,
        hasMore: Array.isArray(data) && data.length === PAGE_SIZE,
        loading: false,
        loadingMore: false,
        error: null,
      }));
    } catch (loadError) {
      updater((current) => ({
        ...current,
        loading: false,
        loadingMore: false,
        error: loadError instanceof Error ? loadError.message : "Unable to load library",
      }));
    }
  }

  function getTabSetter(tab: LibraryTab) {
    let setter: Dispatch<SetStateAction<AnyLibraryState>>;

    if (tab === "liked") {
      setter = setLikedState as Dispatch<SetStateAction<AnyLibraryState>>;
      return setter;
    }

    if (tab === "saved") {
      setter = setSavedState as Dispatch<SetStateAction<AnyLibraryState>>;
      return setter;
    }

    setter = setHistoryState as Dispatch<SetStateAction<AnyLibraryState>>;
    return setter;
  }

  const currentState = activeTab === "liked" ? likedState : activeTab === "saved" ? savedState : historyState;

  if (loading || !user) {
    return (
      <main className="mx-auto max-w-[1440px] px-4 py-8 sm:px-6">
        <div className="rounded-[28px] bg-white p-10 shadow-sm ring-1 ring-black/5">
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-gray-200 border-t-gray-900" />
          <p className="mt-4 text-center text-sm text-gray-500">Loading your library...</p>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6">
      <div className="rounded-[32px] bg-white p-6 shadow-sm ring-1 ring-black/5 sm:p-8">
        <div className="flex flex-col gap-4 border-b border-gray-100 pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-red-500">
              Personal Library
            </p>
            <h1 className="mt-3 text-3xl font-bold tracking-tight text-gray-950">
              {user.username}&apos;s library
            </h1>
            <p className="mt-2 text-sm text-gray-500">
              Review the sessions you liked, saved, or watched recently.
            </p>
          </div>
          <Link
            href="/"
            className="inline-flex rounded-full border border-gray-300 px-4 py-2 text-sm font-medium text-gray-900 transition hover:border-gray-400 hover:bg-gray-50"
          >
            Browse sessions
          </Link>
        </div>

        <div className="mt-6 flex flex-wrap gap-2">
          {(Object.keys(TAB_META) as LibraryTab[]).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
                activeTab === tab
                  ? "bg-black text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {TAB_META[tab].label}
            </button>
          ))}
        </div>

        {currentState.error && (
          <div className="mt-6 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {currentState.error}
          </div>
        )}

        {currentState.loading ? (
          <div className="mt-8 rounded-[28px] border border-gray-200 bg-gray-50 p-10">
            <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-gray-200 border-t-gray-900" />
          </div>
        ) : currentState.items.length === 0 ? (
          <div className="mt-8 rounded-[28px] border border-dashed border-gray-300 bg-gray-50 p-10 text-center">
            <p className="text-base font-semibold text-gray-950">{TAB_META[activeTab].empty}</p>
            <p className="mt-2 text-sm text-gray-500">Use the feed to find sessions worth keeping.</p>
          </div>
        ) : (
          <>
            <div className="mt-8 grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
              {activeTab === "history"
                ? (currentState.items as HistorySession[]).map((item) => (
                    <div key={item.session_id} className="space-y-3">
                      <SessionCard session={item} />
                      <div className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
                        <div className="flex items-center justify-between gap-3 text-sm">
                          <span className="font-medium text-gray-900">Last watched</span>
                          <span className="text-gray-500">{formatRelativeDate(item.last_watched_at)}</span>
                        </div>
                        <div className="mt-3 h-2 overflow-hidden rounded-full bg-gray-200">
                          <div
                            className="h-full rounded-full bg-red-500"
                            style={{ width: `${progressPercent(item.progress_seconds, item.duration_seconds)}%` }}
                          />
                        </div>
                        <p className="mt-2 text-xs text-gray-500">
                          {formatProgress(item.progress_seconds)} of {formatProgress(item.duration_seconds || 0)}
                        </p>
                      </div>
                    </div>
                  ))
                : (currentState.items as SessionSummaryCard[]).map((item) => (
                    <SessionCard key={item.session_id} session={item} />
                  ))}
            </div>

            {currentState.hasMore && (
              <div className="mt-8 flex justify-center">
                <button
                  type="button"
                  onClick={() => void loadTab(activeTab, currentState.page + 1)}
                  disabled={currentState.loadingMore}
                  className="rounded-full border border-gray-300 bg-white px-5 py-2.5 text-sm font-semibold text-gray-900 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {currentState.loadingMore ? "Loading..." : "Load more"}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}

function progressPercent(progressSeconds: number, durationSeconds: number | null) {
  if (!durationSeconds || durationSeconds <= 0) {
    return 0;
  }

  return Math.min((progressSeconds / durationSeconds) * 100, 100);
}

function formatProgress(seconds: number) {
  const safeSeconds = Math.max(Math.floor(seconds), 0);
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const remainingSeconds = safeSeconds % 60;

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${remainingSeconds
      .toString()
      .padStart(2, "0")}`;
  }

  return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
}

function formatRelativeDate(input: string) {
  const date = new Date(input);
  const diffMs = date.getTime() - Date.now();
  const absMs = Math.abs(diffMs);
  const hour = 60 * 60 * 1000;
  const day = 24 * hour;
  const week = 7 * day;
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

  if (absMs < day) {
    return rtf.format(Math.round(diffMs / hour), "hour");
  }

  if (absMs < week) {
    return rtf.format(Math.round(diffMs / day), "day");
  }

  return date.toLocaleDateString();
}
