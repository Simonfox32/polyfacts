"use client";

import Link from "next/link";

export interface SessionSummaryCard {
  session_id: string;
  title: string | null;
  status: string;
  channel_name?: string | null;
  media_type?: string | null;
  duration_seconds: number | null;
  claims_count: number;
  verdict_distribution?: Record<string, number> | null;
  thumbnail_url?: string | null;
  like_count?: number | null;
  view_count?: number | null;
  created_at: string;
}

interface SessionCardProps {
  session: SessionSummaryCard;
}

const STATUS_STYLES: Record<string, string> = {
  processing: "bg-amber-400/90 text-amber-950",
  queued: "bg-slate-200/90 text-slate-900",
  failed: "bg-red-500/90 text-white",
};

const VERDICT_BAR_COLORS: Record<string, string> = {
  TRUE: "bg-green-500",
  MOSTLY_TRUE: "bg-lime-500",
  HALF_TRUE: "bg-yellow-400",
  MOSTLY_FALSE: "bg-orange-500",
  FALSE: "bg-red-500",
  UNVERIFIED: "bg-slate-400",
};

export function SessionCard({ session }: SessionCardProps) {
  const thumbnailUrl = normalizeMediaPath(session.thumbnail_url);
  const verdictDistribution = session.verdict_distribution || {};
  const totalVerdicts = Object.values(verdictDistribution).reduce(
    (sum, value) => sum + value,
    0
  );

  return (
    <Link
      href={`/session/${session.session_id}`}
      className="group overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-black/5 transition-shadow duration-200 hover:shadow-md"
    >
      <div className="relative aspect-video overflow-hidden rounded-t-2xl bg-gray-950">
        {session.media_type === "video" && thumbnailUrl ? (
          <img
            src={thumbnailUrl}
            alt={session.title || "Session thumbnail"}
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-gray-950 via-slate-900 to-gray-800 px-6">
            <div className="w-full max-w-xs rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur">
              <div className="mb-3 flex items-center justify-between text-xs uppercase tracking-[0.2em] text-gray-400">
                <span>{session.media_type === "video" ? "Video" : "Audio"}</span>
                <span>Polyfacts</span>
              </div>
              <div className="flex h-14 items-end gap-1">
                {Array.from({ length: 18 }).map((_, index) => (
                  <div
                    key={index}
                    className="flex-1 rounded-t-full bg-gradient-to-t from-cyan-500 via-sky-400 to-cyan-200"
                    style={{ height: `${30 + ((index * 11) % 60)}%` }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}

        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent" />

        {session.status !== "completed" && (
          <div className="absolute left-3 top-3">
            <span
              className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${
                STATUS_STYLES[session.status] || "bg-slate-200/90 text-slate-900"
              }`}
            >
              {session.status}
            </span>
          </div>
        )}

        <div className="absolute bottom-3 right-3">
          <span className="rounded-md bg-black/80 px-2 py-1 text-xs font-medium text-white">
            {formatDuration(session.duration_seconds)}
          </span>
        </div>

        {typeof session.like_count === "number" && (
          <div className="absolute bottom-3 left-3">
            <span className="rounded-full bg-white/90 px-2.5 py-1 text-[11px] font-semibold text-gray-900 shadow-sm backdrop-blur">
              {formatCompactNumber(session.like_count)} likes
            </span>
          </div>
        )}
      </div>

      <div className="space-y-3 p-4">
        <div>
          <h3 className="line-clamp-2 text-sm font-medium leading-5 text-gray-950">
            {session.title || session.session_id}
          </h3>
          <p className="mt-1 text-xs text-gray-500">
            {session.channel_name || "Unknown channel"}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-500">
          <span>{session.claims_count} claims</span>
          <span aria-hidden="true">•</span>
          <span>{timeAgo(session.created_at)}</span>
          {typeof session.view_count === "number" && (
            <>
              <span aria-hidden="true">•</span>
              <span className="inline-flex items-center gap-1">
                <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 fill-current" aria-hidden="true">
                  <path d="M12 5C6.5 5 2.13 8.11 1 12c1.13 3.89 5.5 7 11 7s9.87-3.11 11-7c-1.13-3.89-5.5-7-11-7Zm0 12a5 5 0 1 1 0-10 5 5 0 0 1 0 10Zm0-2.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z" />
                </svg>
                <span>{formatCompactNumber(session.view_count)}</span>
              </span>
            </>
          )}
        </div>

        <div className="space-y-1.5">
          <div className="flex h-2 overflow-hidden rounded-full bg-gray-100">
            {totalVerdicts > 0 ? (
              Object.entries(verdictDistribution).map(([label, count]) => (
                <div
                  key={label}
                  className={VERDICT_BAR_COLORS[label] || "bg-slate-400"}
                  style={{ width: `${(count / totalVerdicts) * 100}%` }}
                  title={`${label}: ${count}`}
                />
              ))
            ) : (
              <div className="h-full w-full bg-gray-200" />
            )}
          </div>
          <p className="text-[11px] uppercase tracking-wide text-gray-400">
            Verdict mix
          </p>
        </div>
      </div>
    </Link>
  );
}

function formatDuration(durationSeconds: number | null): string {
  if (!durationSeconds || durationSeconds <= 0) {
    return "--:--";
  }

  const hours = Math.floor(durationSeconds / 3600);
  const minutes = Math.floor((durationSeconds % 3600) / 60);
  const seconds = durationSeconds % 60;

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${seconds
      .toString()
      .padStart(2, "0")}`;
  }

  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function normalizeMediaPath(path: string | null | undefined): string | null {
  if (!path) return null;
  return path.startsWith("/v1/") ? path.replace("/v1/", "/api/") : path;
}

function formatCompactNumber(value: number): string {
  if (value < 1000) {
    return String(value);
  }

  return new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function timeAgo(input: string): string {
  const date = new Date(input);
  const diffMs = date.getTime() - Date.now();
  const absMs = Math.abs(diffMs);
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const week = 7 * day;
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

  if (absMs < hour) {
    return rtf.format(Math.round(diffMs / minute), "minute");
  }

  if (absMs < day) {
    return rtf.format(Math.round(diffMs / hour), "hour");
  }

  if (absMs < week) {
    return rtf.format(Math.round(diffMs / day), "day");
  }

  return date.toLocaleDateString();
}
