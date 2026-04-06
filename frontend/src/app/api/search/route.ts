import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const BACKEND_BASE = process.env.BACKEND_URL || "http://localhost:8000/v1";

type SortOption = "newest" | "most-claims";

interface SessionSummary {
  session_id: string;
  title: string | null;
  status: string;
  channel_name?: string | null;
  media_type?: string | null;
  duration_seconds?: number | null;
  claims_count: number;
  verdict_distribution?: Record<string, number>;
  thumbnail_url?: string | null;
  created_at: string;
}

interface BackendSearchResponse {
  claims?: Array<{
    claim_id: string;
    claim_text: string;
    speaker: string | null;
    verdict_label: string | null;
    confidence: number | null;
    session_id: string;
    start_ms: number;
  }>;
  sessions?: Array<Partial<SessionSummary>>;
}

type SearchItem =
  | ({ kind: "session" } & SessionSummary)
  | {
      kind: "claim";
      claim_id: string;
      claim_text: string;
      speaker: string | null;
      verdict_label: string | null;
      confidence: number | null;
      session_id: string;
      session_title: string | null;
      channel_name: string | null;
      thumbnail_url: string | null;
      media_type: string | null;
      created_at: string;
      start_ms: number;
      claims_count: number;
    };

function normalizeSort(value: string | null): SortOption {
  return value === "most-claims" ? "most-claims" : "newest";
}

function normalizeMediaPath(path: string | null | undefined): string | null {
  if (!path) return null;
  return path.startsWith("/v1/") ? path.replace("/v1/", "/api/") : path;
}

function sortItems(items: SearchItem[], sort: SortOption) {
  return [...items].sort((left, right) => {
    if (sort === "most-claims" && right.claims_count !== left.claims_count) {
      return right.claims_count - left.claims_count;
    }

    return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
  });
}

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const q = searchParams.get("q")?.trim() ?? "";
  const page = Number(searchParams.get("page") ?? "1");
  const perPage = Number(searchParams.get("per_page") ?? "12");
  const sort = normalizeSort(searchParams.get("sort"));

  if (!q) {
    return NextResponse.json({
      items: [],
      total: 0,
      page,
      per_page: perPage,
    });
  }

  const sessionIndexUrl = new URL(`${BACKEND_BASE}/sessions`);
  sessionIndexUrl.searchParams.set("page", "1");
  sessionIndexUrl.searchParams.set("per_page", "100");

  try {
    const [sessionIndexRes, backendSearchRes] = await Promise.all([
      fetch(sessionIndexUrl, { cache: "no-store" }),
      fetch(
        `${BACKEND_BASE}/search?${new URLSearchParams({
          q,
          page: String(page),
          per_page: String(perPage),
        }).toString()}`,
        { cache: "no-store" }
      ),
    ]);

    const sessionIndex: SessionSummary[] = sessionIndexRes.ok ? await sessionIndexRes.json() : [];
    const sessionMap = new Map(sessionIndex.map((session) => [session.session_id, session]));

    if (backendSearchRes.ok) {
      const backendSearch: BackendSearchResponse = await backendSearchRes.json();
      const items: SearchItem[] = [
        ...(backendSearch.sessions ?? []).map((session) => {
          const fullSession = sessionMap.get(session.session_id ?? "") ?? null;

          return {
            kind: "session" as const,
            session_id: session.session_id ?? "",
            title: fullSession?.title ?? session.title ?? null,
            status: fullSession?.status ?? session.status ?? "completed",
            channel_name: fullSession?.channel_name ?? session.channel_name ?? null,
            media_type: fullSession?.media_type ?? session.media_type ?? "audio",
            duration_seconds: fullSession?.duration_seconds ?? session.duration_seconds ?? null,
            claims_count: fullSession?.claims_count ?? session.claims_count ?? 0,
            verdict_distribution:
              fullSession?.verdict_distribution ?? session.verdict_distribution ?? {},
            thumbnail_url: normalizeMediaPath(
              fullSession?.thumbnail_url ?? session.thumbnail_url ?? null
            ),
            created_at: fullSession?.created_at ?? session.created_at ?? new Date().toISOString(),
          };
        }),
        ...(backendSearch.claims ?? []).map((claim) => {
          const session = sessionMap.get(claim.session_id);

          return {
            kind: "claim" as const,
            claim_id: claim.claim_id,
            claim_text: claim.claim_text,
            speaker: claim.speaker,
            verdict_label: claim.verdict_label,
            confidence: claim.confidence,
            session_id: claim.session_id,
            session_title: session?.title ?? null,
            channel_name: session?.channel_name ?? null,
            thumbnail_url: normalizeMediaPath(session?.thumbnail_url ?? null),
            media_type: session?.media_type ?? "audio",
            created_at: session?.created_at ?? new Date().toISOString(),
            start_ms: claim.start_ms,
            claims_count: session?.claims_count ?? 0,
          };
        }),
      ];

      return NextResponse.json({
        items: sortItems(items, sort),
        total: items.length,
        page,
        per_page: perPage,
      });
    }

    const fallbackItems = sortItems(
      sessionIndex
        .filter((session) => {
          const title = session.title?.toLowerCase() ?? "";
          const channel = session.channel_name?.toLowerCase() ?? "";
          return title.includes(q.toLowerCase()) || channel.includes(q.toLowerCase());
        })
        .map((session) => ({
          ...session,
          kind: "session" as const,
          thumbnail_url: normalizeMediaPath(session.thumbnail_url),
        })),
      sort
    );

    return NextResponse.json({
      items: fallbackItems,
      total: fallbackItems.length,
      page,
      per_page: perPage,
    });
  } catch (error) {
    return NextResponse.json(
      {
        detail: error instanceof Error ? error.message : "Search failed",
      },
      { status: 500 }
    );
  }
}
