"use client";

import { useEffect, useState } from "react";

interface SourceItem {
  source_id: string;
  url: string;
  title: string;
  publisher: string | null;
  source_tier: string;
  publication_date: string | null;
}

interface TierGroup {
  tier: string;
  display_name: string;
  sources: SourceItem[];
}

const TIER_COLORS: Record<string, string> = {
  tier_1_government_primary: "bg-blue-100 text-blue-800",
  tier_2_court_academic: "bg-purple-100 text-purple-800",
  tier_3_major_outlet: "bg-green-100 text-green-800",
  tier_4_regional_specialty: "bg-amber-100 text-amber-800",
  tier_5_other: "bg-gray-100 text-gray-700",
};

export function SourcesPanel({ sessionId }: { sessionId: string }) {
  const [groups, setGroups] = useState<TierGroup[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    fetch(`/api/sessions/${sessionId}/sources`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error("Failed to load sources"))))
      .then((data) => {
        if (cancelled) return;
        setGroups(data.groups || []);
        setTotal(data.total_sources || 0);
      })
      .catch(() => {
        if (cancelled) return;
        setGroups([]);
        setTotal(0);
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  if (loading || total === 0) {
    return null;
  }

  return (
    <section className="rounded-[28px] border border-gray-200 bg-white p-5 shadow-sm ring-1 ring-black/5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-gray-950">Sources</h2>
        <span className="text-sm text-gray-500">{total} sources cited</span>
      </div>

      <div className="space-y-5">
        {groups.map((group) => (
          <div key={group.tier}>
            <div className="mb-2 flex items-center gap-2">
              <span
                className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                  TIER_COLORS[group.tier] || "bg-gray-100 text-gray-700"
                }`}
              >
                {group.display_name}
              </span>
              <span className="text-xs text-gray-400">{group.sources.length}</span>
            </div>

            <div className="space-y-2 pl-1">
              {group.sources.map((source) => (
                <div key={source.source_id} className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm font-medium text-blue-600 hover:text-blue-800 hover:underline"
                    >
                      {source.title || source.url}
                    </a>
                    {source.publisher && (
                      <p className="text-xs text-gray-500">{source.publisher}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
