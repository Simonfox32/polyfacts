"use client";

import { useEffect, useState } from "react";

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

interface ClaimDetail {
  claim_id: string;
  claim_text: string;
  claim_type: string;
  verdict: {
    label: string;
    confidence: number | null;
    rationale_summary: string | null;
    rationale_bullets: string[];
  } | null;
  sources: {
    source_id: string;
    url: string;
    title: string;
    publisher: string;
    source_tier: string;
    snippet_supporting: string;
    relevance_to_claim: string;
  }[];
  what_would_change_verdict: string | null;
}

const VERDICT_COLORS: Record<string, string> = {
  TRUE: "bg-verdict-true text-white",
  MOSTLY_TRUE: "bg-verdict-mostly-true text-white",
  HALF_TRUE: "bg-verdict-half-true text-black",
  MOSTLY_FALSE: "bg-verdict-mostly-false text-white",
  FALSE: "bg-verdict-false text-white",
  UNVERIFIED: "bg-verdict-unverified text-white",
};

const TIER_LABELS: Record<string, string> = {
  tier_1_government_primary: "Gov Primary",
  tier_2_court_academic: "Court/Academic",
  tier_3_major_outlet: "Major Outlet",
  tier_4_regional_specialty: "Regional",
  tier_5_other: "Other",
};

interface Props {
  claim: ClaimSummary;
  isSelected: boolean;
  onClick: () => void;
}

export function ClaimCard({ claim, isSelected, onClick }: Props) {
  const [detail, setDetail] = useState<ClaimDetail | null>(null);

  useEffect(() => {
    if (isSelected && !detail) {
      fetch(`/api/claims/${claim.claim_id}`)
        .then((r) => r.json())
        .then(setDetail)
        .catch(() => {});
    }
  }, [isSelected, claim.claim_id, detail]);

  const verdictLabel = claim.verdict?.label || "PENDING";
  const colorClass = VERDICT_COLORS[verdictLabel] || "bg-gray-300";

  return (
    <div
      className={`rounded-lg border p-3 cursor-pointer transition-all ${
        isSelected ? "border-black shadow-md" : "border-gray-200 hover:border-gray-400"
      }`}
      onClick={onClick}
    >
      {/* Verdict chip */}
      <div className="flex items-center gap-2 mb-2">
        <span className={`text-xs font-bold px-2 py-0.5 rounded ${colorClass}`}>
          {verdictLabel.replace("_", " ")}
        </span>
        {claim.verdict?.confidence != null && (
          <span className="text-xs text-gray-500">
            {Math.round(claim.verdict.confidence * 100)}% confidence
          </span>
        )}
        <span className="text-xs text-gray-400 ml-auto">
          {formatMs(claim.timestamp_range.start_ms)}
        </span>
      </div>

      {/* Claim text */}
      <p className="text-sm leading-snug">
        {claim.speaker && (
          <span className="font-medium">{claim.speaker.speaker_label}: </span>
        )}
        {claim.claim_text}
      </p>

      {/* Rationale summary */}
      {claim.verdict?.rationale_summary && (
        <p className="text-xs text-gray-600 mt-1.5 leading-relaxed">
          {claim.verdict.rationale_summary}
        </p>
      )}

      {/* Expanded detail */}
      {isSelected && detail && (
        <div className="mt-3 pt-3 border-t space-y-3">
          {/* Rationale bullets */}
          {detail.verdict?.rationale_bullets && detail.verdict.rationale_bullets.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold uppercase text-gray-500 mb-1">
                Analysis
              </h4>
              <ul className="text-xs space-y-1">
                {detail.verdict.rationale_bullets.map((bullet, i) => (
                  <li key={i} className="leading-relaxed pl-3 relative">
                    <span className="absolute left-0">-</span>
                    {bullet}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Sources */}
          {detail.sources && detail.sources.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold uppercase text-gray-500 mb-2">
                Sources ({detail.sources.length})
              </h4>
              <div className="space-y-2.5">
                {detail.sources.map((source, i) => (
                  <div key={source.source_id || `src-${i}`} className="text-xs border-l-2 border-gray-200 pl-2">
                    <div className="flex items-start gap-1.5">
                      <span className="shrink-0 px-1.5 py-0.5 bg-gray-100 rounded text-[10px] font-medium whitespace-nowrap mt-0.5">
                        {TIER_LABELS[source.source_tier] || source.source_tier}
                      </span>
                      <div className="min-w-0">
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:underline line-clamp-2 block leading-snug"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {source.title}
                        </a>
                        <p className="text-gray-400 mt-0.5">{source.publisher}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* What would change */}
          {detail.what_would_change_verdict && (
            <div>
              <h4 className="text-xs font-semibold uppercase text-gray-500 mb-1">
                What would change this verdict?
              </h4>
              <p className="text-xs text-gray-600 leading-relaxed">
                {detail.what_would_change_verdict}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatMs(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}
