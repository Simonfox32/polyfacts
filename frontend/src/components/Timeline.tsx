"use client";

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
  timestamp_range: { start_ms: number; end_ms: number };
  verdict: { label: string } | null;
}

const VERDICT_DOT_COLORS: Record<string, string> = {
  TRUE: "bg-green-500",
  MOSTLY_TRUE: "bg-lime-500",
  HALF_TRUE: "bg-yellow-500",
  MOSTLY_FALSE: "bg-orange-500",
  FALSE: "bg-red-500",
  UNVERIFIED: "bg-gray-400",
};

interface Props {
  segments: TranscriptSegment[];
  claims: ClaimSummary[];
  selectedClaimId: string | null;
  onClaimSelect: (id: string | null) => void;
}

export function Timeline({ segments, claims, selectedClaimId, onClaimSelect }: Props) {
  // Map claims to their segments
  const claimsBySegment = new Map<string, ClaimSummary[]>();
  for (const claim of claims) {
    // Find the segment that contains this claim
    for (const seg of segments) {
      if (
        claim.timestamp_range.start_ms >= seg.start_ms &&
        claim.timestamp_range.start_ms <= seg.end_ms
      ) {
        const existing = claimsBySegment.get(seg.segment_id) || [];
        existing.push(claim);
        claimsBySegment.set(seg.segment_id, existing);
        break;
      }
    }
  }

  if (segments.length === 0) {
    return <p className="text-sm text-gray-500">No transcript available.</p>;
  }

  // Timeline bar
  const totalDuration = segments[segments.length - 1]?.end_ms || 1;

  return (
    <div>
      {/* Timeline bar with claim markers */}
      <div className="relative h-6 bg-gray-100 rounded-full mb-6 overflow-visible">
        {claims.map((claim) => {
          const left = (claim.timestamp_range.start_ms / totalDuration) * 100;
          const color = VERDICT_DOT_COLORS[claim.verdict?.label || "UNVERIFIED"];
          return (
            <button
              key={claim.claim_id}
              className={`absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full ${color} border-2 border-white shadow-sm hover:scale-150 transition-transform ${
                claim.claim_id === selectedClaimId ? "ring-2 ring-black scale-150" : ""
              }`}
              style={{ left: `${left}%` }}
              title={claim.claim_text.slice(0, 80)}
              onClick={() =>
                onClaimSelect(claim.claim_id === selectedClaimId ? null : claim.claim_id)
              }
            />
          );
        })}
      </div>

      {/* Transcript segments */}
      <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-2">
        {segments.map((seg) => {
          const segClaims = claimsBySegment.get(seg.segment_id) || [];
          const hasSelectedClaim = segClaims.some((c) => c.claim_id === selectedClaimId);

          return (
            <div
              key={seg.segment_id}
              className={`rounded-lg p-3 transition-colors ${
                hasSelectedClaim ? "bg-yellow-50 border border-yellow-200" : "hover:bg-gray-50"
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs text-gray-400 font-mono">
                  {formatMs(seg.start_ms)}
                </span>
                {seg.speaker_label && (
                  <span className="text-xs font-medium text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded">
                    {seg.speaker_label}
                  </span>
                )}
                {segClaims.map((c) => (
                  <span
                    key={c.claim_id}
                    className={`inline-block w-2 h-2 rounded-full ${
                      VERDICT_DOT_COLORS[c.verdict?.label || "UNVERIFIED"]
                    }`}
                    title={`${c.verdict?.label || "Pending"}: ${c.claim_text.slice(0, 60)}`}
                  />
                ))}
              </div>
              <p className="text-sm leading-relaxed">{highlightClaims(seg.text, segClaims)}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function highlightClaims(text: string, claims: ClaimSummary[]): React.ReactNode {
  if (claims.length === 0) return text;

  // Simple approach: bold claim text within the segment
  let result = text;
  for (const claim of claims) {
    const idx = result.toLowerCase().indexOf(claim.claim_text.toLowerCase().slice(0, 30));
    if (idx >= 0) {
      // Found a match — return with highlight
      const before = result.slice(0, idx);
      const match = result.slice(idx, idx + claim.claim_text.length);
      const after = result.slice(idx + claim.claim_text.length);
      return (
        <>
          {before}
          <span className="bg-yellow-100 font-medium">{match}</span>
          {after}
        </>
      );
    }
  }
  return text;
}

function formatMs(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}
