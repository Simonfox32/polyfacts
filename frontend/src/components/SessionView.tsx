"use client";

import { useCallback, useEffect, useState } from "react";
import { ClaimCard } from "./ClaimCard";
import { Timeline } from "./Timeline";

interface TranscriptSegment {
  segment_id: string;
  speaker_label: string | null;
  text: string;
  start_ms: number;
  end_ms: number;
}

interface ClaimSummary {
  claim_id: string;
  claim_text: string;
  claim_type: string;
  speaker: { speaker_label: string; party?: string } | null;
  timestamp_range: { start_ms: number; end_ms: number };
  verdict: {
    label: string;
    confidence: number | null;
    rationale_summary: string | null;
  } | null;
  source_count: number;
}

interface SessionStatus {
  clip_id: string;
  status: string;
  stage: string | null;
  progress_pct: number;
  claims_detected: number;
  claims_verdicted: number;
}

interface Props {
  sessionId: string;
}

export function SessionView({ sessionId }: Props) {
  const [status, setStatus] = useState<SessionStatus | null>(null);
  const [transcript, setTranscript] = useState<TranscriptSegment[]>([]);
  const [claims, setClaims] = useState<ClaimSummary[]>([]);
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null);

  // Poll session status
  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch(`/api/clips/${sessionId}/status`);
        if (res.ok) {
          const data = await res.json();
          setStatus(data);

          if (data.status === "completed" || data.status === "failed") {
            clearInterval(interval);
            // Load full data
            loadTranscript();
            loadClaims();
          }
        }
      } catch {}
    };

    const interval = setInterval(poll, 2000);
    poll();
    return () => clearInterval(interval);
  }, [sessionId]);

  const loadTranscript = useCallback(async () => {
    try {
      const res = await fetch(`/api/sessions/${sessionId}/transcript`);
      if (res.ok) setTranscript(await res.json());
    } catch {}
  }, [sessionId]);

  const loadClaims = useCallback(async () => {
    try {
      const res = await fetch(`/api/sessions/${sessionId}/claims`);
      if (res.ok) {
        const data = await res.json();
        setClaims(data.results || []);
      }
    } catch {}
  }, [sessionId]);

  const stageLabel: Record<string, string> = {
    asr: "Transcribing audio",
    speaker_identification: "Identifying speakers",
    claim_detection: "Detecting claims",
    evidence_retrieval: "Retrieving evidence",
    verdict_generation: "Generating verdicts",
  };

  // Processing state
  if (!status || status.status === "queued" || status.status === "processing") {
    return (
      <div className="rounded-xl border p-8 text-center">
        <div className="animate-spin h-8 w-8 border-2 border-gray-300 border-t-black rounded-full mx-auto mb-4" />
        <p className="font-medium">
          {status?.stage ? stageLabel[status.stage] || status.stage : "Processing..."}
        </p>
        <div className="mt-3 w-full bg-gray-200 rounded-full h-2 max-w-md mx-auto">
          <div
            className="bg-black h-2 rounded-full transition-all duration-500"
            style={{ width: `${status?.progress_pct || 0}%` }}
          />
        </div>
        <p className="text-sm text-gray-500 mt-2">
          {status?.claims_detected || 0} claims detected, {status?.claims_verdicted || 0} verdicted
        </p>
      </div>
    );
  }

  // Error state
  if (status.status === "failed") {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-8 text-center">
        <p className="font-medium text-red-800">Processing failed</p>
        <p className="text-sm text-red-600 mt-1">Please try uploading again.</p>
      </div>
    );
  }

  // Completed: show transcript + claims
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Transcript panel */}
      <div className="lg:col-span-2">
        <h2 className="text-lg font-semibold mb-3">Transcript</h2>
        <Timeline
          segments={transcript}
          claims={claims}
          selectedClaimId={selectedClaimId}
          onClaimSelect={setSelectedClaimId}
        />
      </div>

      {/* Claims panel */}
      <div>
        <h2 className="text-lg font-semibold mb-3">
          Claims ({claims.length})
        </h2>
        <div className="space-y-3">
          {claims.length === 0 && (
            <p className="text-sm text-gray-500">No checkable claims detected.</p>
          )}
          {claims.map((claim) => (
            <ClaimCard
              key={claim.claim_id}
              claim={claim}
              isSelected={claim.claim_id === selectedClaimId}
              onClick={() =>
                setSelectedClaimId(
                  claim.claim_id === selectedClaimId ? null : claim.claim_id
                )
              }
            />
          ))}
        </div>
      </div>
    </div>
  );
}
