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
      className={`cursor-pointer rounded-xl border bg-white p-4 shadow-sm transition-all ${
        isSelected
          ? "border-black shadow-md ring-1 ring-black/10"
          : "border-gray-200 hover:-translate-y-0.5 hover:border-gray-300 hover:shadow-md"
      }`}
      onClick={onClick}
    >
      <div className="mb-2 flex items-center gap-2">
        <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${colorClass}`}>
          {verdictLabel.replace("_", " ")}
        </span>
        {claim.verdict?.confidence != null && (
          <span className="text-xs text-gray-500">
            {Math.round(claim.verdict.confidence * 100)}% confidence
          </span>
        )}
        <span className="ml-auto text-xs text-gray-400">
          {formatMs(claim.timestamp_range.start_ms)}
        </span>
      </div>

      <p className="text-sm leading-snug text-gray-900">
        {claim.speaker && (
          <span className="font-medium">{claim.speaker.speaker_label}: </span>
        )}
        {claim.claim_text}
      </p>

      {claim.verdict?.rationale_summary && (
        <p className="mt-1.5 text-xs leading-relaxed text-gray-600">
          {claim.verdict.rationale_summary}
        </p>
      )}

      {isSelected && detail && (
        <div className="mt-3 space-y-3 border-t border-gray-100 pt-3">
          {detail.verdict?.rationale_bullets && detail.verdict.rationale_bullets.length > 0 && (
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase text-gray-500">
                Analysis
              </h4>
              <ul className="space-y-1 text-xs">
                {detail.verdict.rationale_bullets.map((bullet, i) => (
                  <li key={i} className="relative pl-3 leading-relaxed">
                    <span className="absolute left-0">-</span>
                    {bullet}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {detail.sources && detail.sources.length > 0 && (
            <div>
              <h4 className="mb-2 text-xs font-semibold uppercase text-gray-500">
                Sources ({detail.sources.length})
              </h4>
              <div className="space-y-2.5">
                {detail.sources.map((source, i) => (
                  <div
                    key={source.source_id || `src-${i}`}
                    className="border-l-2 border-gray-200 pl-2 text-xs"
                  >
                    <div className="flex items-start gap-1.5">
                      <span className="mt-0.5 shrink-0 whitespace-nowrap rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium">
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

          {detail.what_would_change_verdict && (
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase text-gray-500">
                What would change this verdict?
              </h4>
              <p className="text-xs leading-relaxed text-gray-600">
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
