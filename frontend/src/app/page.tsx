"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ClipUploader } from "@/components/ClipUploader";
import { SessionCard } from "@/components/SessionCard";
import { useAuth } from "@/context/AuthContext";

interface SessionSummary {
  session_id: string;
  title: string | null;
  status: string;
  channel_name?: string | null;
  media_type?: string | null;
  duration_seconds: number | null;
  claims_count: number;
  verdict_distribution?: Record<string, number>;
  thumbnail_url?: string | null;
  view_count?: number | null;
  created_at: string;
}

interface SearchClaimResult {
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
}

interface SearchSessionResult extends SessionSummary {
  kind: "session";
}

interface SearchResponse {
  items: Array<SearchClaimResult | SearchSessionResult>;
  total: number;
  page: number;
  per_page: number;
}

const PAGE_SIZE = 12;
const CATEGORIES = ["All", "Politics", "Economy", "Health", "Legal"] as const;
const SORT_OPTIONS = [
  { label: "Newest", value: "newest" },
  { label: "Most Claims", value: "most-claims" },
] as const;
const VERDICT_FILTERS = [
  "ALL",
  "TRUE",
  "MOSTLY_TRUE",
  "HALF_TRUE",
  "MOSTLY_FALSE",
  "FALSE",
  "UNVERIFIED",
] as const;

type Category = (typeof CATEGORIES)[number];
type SortOption = (typeof SORT_OPTIONS)[number]["value"];
type VerdictFilter = (typeof VERDICT_FILTERS)[number];
type FeedItem = SearchClaimResult | SearchSessionResult;

function HomeInner() {
  const router = useRouter();
  const { isAdmin } = useAuth();
  const searchParams = useSearchParams();
  const query = searchParams.get("q")?.trim() ?? "";
  const sort = normalizeSort(searchParams.get("sort"));

  const [searchDraft, setSearchDraft] = useState(query);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [searchResults, setSearchResults] = useState<FeedItem[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<Category>("All");
  const [verdictFilter, setVerdictFilter] = useState<VerdictFilter>("ALL");
  const [speakerDraft, setSpeakerDraft] = useState("");
  const [speakerFilter, setSpeakerFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSearchDraft(query);
  }, [query]);

  useEffect(() => {
    if (query) return;
    setVerdictFilter("ALL");
    setSpeakerDraft("");
    setSpeakerFilter("");
  }, [query]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setSpeakerFilter(speakerDraft.trim());
    }, 500);

    return () => window.clearTimeout(timeout);
  }, [speakerDraft]);

  useEffect(() => {
    let cancelled = false;

    const loadInitial = async () => {
      setLoading(true);
      setError(null);

      try {
        if (query) {
          const params = new URLSearchParams({
            q: query,
            sort,
            page: "1",
            per_page: String(PAGE_SIZE),
          });
          if (verdictFilter !== "ALL") {
            params.set("verdict", verdictFilter);
          }
          if (speakerFilter) {
            params.set("speaker", speakerFilter);
          }

          const res = await fetch(`/api/search?${params.toString()}`);

          if (!res.ok) {
            throw new Error("Unable to load search results");
          }

          const data: SearchResponse = await res.json();
          if (cancelled) return;

          setSearchResults(data.items);
          setSessions([]);
          setPage(1);
          setHasMore(false);
          return;
        }

        const res = await fetch(
          `/api/sessions?${new URLSearchParams({
            page: "1",
            per_page: String(PAGE_SIZE),
            sort,
          }).toString()}`
        );

        if (!res.ok) {
          throw new Error("Unable to load sessions");
        }

        const data: SessionSummary[] = await res.json();
        if (cancelled) return;

        setSessions(data);
        setSearchResults([]);
        setPage(1);
        setHasMore(data.length === PAGE_SIZE);
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Unable to load feed");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    loadInitial();

    return () => {
      cancelled = true;
    };
  }, [query, sort, verdictFilter, speakerFilter]);

  async function handleLoadMore() {
    const nextPage = page + 1;
    setLoadingMore(true);
    setError(null);

    try {
      const res = await fetch(
        `/api/sessions?${new URLSearchParams({
          page: String(nextPage),
          per_page: String(PAGE_SIZE),
          sort,
        }).toString()}`
      );

      if (!res.ok) {
        throw new Error("Unable to load more sessions");
      }

      const data: SessionSummary[] = await res.json();
      setSessions((current) => [...current, ...data]);
      setPage(nextPage);
      setHasMore(data.length === PAGE_SIZE);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load more sessions");
    } finally {
      setLoadingMore(false);
    }
  }

  function updateUrl(nextQuery: string, nextSort: SortOption) {
    const nextParams = new URLSearchParams();
    if (nextQuery.trim()) {
      nextParams.set("q", nextQuery.trim());
    }
    if (nextSort !== "newest") {
      nextParams.set("sort", nextSort);
    }

    const nextUrl = nextParams.toString() ? `/?${nextParams.toString()}` : "/";
    router.push(nextUrl);
  }

  function handleSearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    updateUrl(searchDraft, sort);
  }

  const rawItems: FeedItem[] = query
    ? searchResults
    : sessions.map((session) => ({
        ...session,
        kind: "session" as const,
        thumbnail_url: normalizeMediaPath(session.thumbnail_url),
      }));

  const sortedItems = sortFeedItems(rawItems, sort);
  const visibleItems = sortedItems.filter((item) =>
    selectedCategory === "All" ? true : inferCategory(getCategoryText(item)) === selectedCategory
  );
  const headerTitle = query ? `Results for "${query}"` : "Latest sessions";
  const headerDescription = query
    ? "Claims and sessions are mixed together so you can jump straight into the right moment."
    : "Browse recent fact-check runs and explore AI-backed claim verdicts.";

  return (
    <main className="min-h-[calc(100vh-3.5rem)] bg-background">
      <div className="sticky top-14 z-30 border-b border-gray-200 bg-background/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1440px] gap-2 overflow-x-auto px-4 py-3 sm:px-6">
          {CATEGORIES.map((category) => (
            <button
              key={category}
              type="button"
              onClick={() => setSelectedCategory(category)}
              className={`shrink-0 rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                selectedCategory === category
                  ? "bg-black text-white"
                  : "bg-white text-gray-700 shadow-sm ring-1 ring-black/5 hover:bg-gray-100"
              }`}
            >
              {category}
            </button>
          ))}
        </div>
      </div>

      <div className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6">
        <section className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-black/5 sm:p-5">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-red-600">
                Political Fact-Checking Feed
              </p>
              <h1 className="mt-2 text-2xl font-bold tracking-tight text-gray-950 sm:text-3xl">
                {headerTitle}
              </h1>
              <p className="mt-2 text-sm leading-6 text-gray-500">{headerDescription}</p>
            </div>

            <div className="flex w-full flex-col gap-3 lg:max-w-2xl">
              <form onSubmit={handleSearchSubmit} className="flex flex-col gap-3 sm:flex-row">
                <div className="relative flex-1">
                  <svg
                    viewBox="0 0 24 24"
                    className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 fill-gray-400"
                    aria-hidden="true"
                  >
                    <path d="M10 4a6 6 0 1 0 3.874 10.582l4.772 4.772 1.414-1.414-4.772-4.772A6 6 0 0 0 10 4Zm0 2a4 4 0 1 1 0 8 4 4 0 0 1 0-8Z" />
                  </svg>
                  <input
                    type="search"
                    value={searchDraft}
                    onChange={(event) => setSearchDraft(event.target.value)}
                    placeholder="Search claims, speakers, channels..."
                    className="h-12 w-full rounded-full border border-gray-300 bg-white pl-11 pr-4 text-sm text-gray-900 placeholder:text-gray-400 transition-colors focus:border-gray-400 focus:outline-none"
                  />
                </div>

                <button
                  type="submit"
                  className="h-12 rounded-full bg-black px-5 text-sm font-medium text-white transition-colors hover:bg-gray-800"
                >
                  Search
                </button>
              </form>

              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm text-gray-500">
                  {query ? `${visibleItems.length} search matches` : `${visibleItems.length} sessions shown`}
                </p>
                <label className="flex items-center gap-3 text-sm text-gray-500">
                  <span>Sort by</span>
                  <select
                    value={sort}
                    onChange={(event) => updateUrl(query, normalizeSort(event.target.value))}
                    className="h-10 rounded-full border border-gray-300 bg-white px-4 text-sm font-medium text-gray-900 transition-colors focus:border-gray-400 focus:outline-none"
                  >
                    {SORT_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              {query && (
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <div className="flex flex-wrap gap-2">
                    {VERDICT_FILTERS.map((filter) => (
                      <button
                        key={filter}
                        type="button"
                        onClick={() => setVerdictFilter(filter)}
                        className={`rounded-full px-3 py-1.5 text-xs font-semibold transition-colors ${
                          verdictFilter === filter
                            ? "bg-gray-900 text-white"
                            : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                        }`}
                      >
                        {filter}
                      </button>
                    ))}
                  </div>

                  <input
                    type="text"
                    value={speakerDraft}
                    onChange={(event) => setSpeakerDraft(event.target.value)}
                    placeholder="Filter by speaker..."
                    className="h-10 w-full rounded-full border border-gray-300 bg-white px-4 text-sm text-gray-900 placeholder:text-gray-400 transition-colors focus:border-gray-400 focus:outline-none lg:max-w-xs"
                  />
                </div>
              )}
            </div>
          </div>
        </section>

        {error && (
          <div className="mt-6 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <section className="mt-6">
          <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-950">
                {query ? "Search feed" : "Recommended for review"}
              </h2>
              <p className="mt-1 text-sm text-gray-500">
                {query
                  ? "Sessions and claim moments are blended into one browsing grid."
                  : "Recent uploads with fast verdict visibility and watch-page deep links."}
              </p>
            </div>
            {!query && <span className="text-sm text-gray-400">{sessions.length} loaded</span>}
          </div>

          {loading ? (
            <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {Array.from({ length: 8 }).map((_, index) => (
                <div
                  key={index}
                  className="overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-black/5"
                >
                  <div className="aspect-video animate-pulse bg-gray-200" />
                  <div className="space-y-3 p-4">
                    <div className="h-4 animate-pulse rounded bg-gray-200" />
                    <div className="h-3 w-2/3 animate-pulse rounded bg-gray-100" />
                    <div className="h-2 animate-pulse rounded-full bg-gray-100" />
                  </div>
                </div>
              ))}
            </div>
          ) : visibleItems.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-gray-300 bg-white px-6 py-12 text-center shadow-sm">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-gray-100">
                <svg viewBox="0 0 24 24" className="h-6 w-6 fill-gray-500" aria-hidden="true">
                  <path d="M10 4a6 6 0 1 0 3.874 10.582l4.772 4.772 1.414-1.414-4.772-4.772A6 6 0 0 0 10 4Zm0 2a4 4 0 1 1 0 8 4 4 0 0 1 0-8Z" />
                </svg>
              </div>
              <h3 className="mt-4 text-lg font-semibold text-gray-950">
                {query ? "No matching claims or sessions" : "No sessions yet"}
              </h3>
              <p className="mt-2 text-sm text-gray-500">
                {query
                  ? "Try a broader speaker name, claim phrase, or channel search."
                  : "No fact-check sessions have been created yet."}
              </p>
              <div className="mt-5 flex flex-wrap justify-center gap-3">
                {query && (
                  <button
                    type="button"
                    onClick={() => updateUrl("", sort)}
                    className="rounded-full bg-black px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-800"
                  >
                    Clear search
                  </button>
                )}
                {isAdmin && (
                  <Link
                    href="/#upload"
                    className="rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-900 transition-colors hover:bg-gray-50"
                  >
                    Jump to upload
                  </Link>
                )}
              </div>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {visibleItems.map((item) =>
                  item.kind === "session" ? (
                    <SessionCard
                      key={item.session_id}
                      session={{
                        ...item,
                        thumbnail_url: normalizeMediaPath(item.thumbnail_url),
                      }}
                    />
                  ) : (
                    <ClaimResultCard key={item.claim_id} claim={item} />
                  )
                )}
              </div>

              {!query && hasMore && (
                <div className="mt-8 flex justify-center">
                  <button
                    type="button"
                    onClick={handleLoadMore}
                    disabled={loadingMore}
                    className="rounded-full border border-gray-300 bg-white px-5 py-2.5 text-sm font-medium text-gray-800 shadow-sm transition-colors hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {loadingMore ? "Loading..." : "Load more"}
                  </button>
                </div>
              )}
            </>
          )}
        </section>

        {isAdmin && (
          <section
            id="upload"
            className="mt-10 scroll-mt-24 rounded-2xl bg-gradient-to-br from-white via-white to-red-50 p-1 shadow-sm ring-1 ring-black/5"
          >
            <div className="rounded-2xl bg-white p-5 sm:p-6">
              <div className="mb-4">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-red-600">
                  Upload
                </p>
                <h2 className="mt-2 text-xl font-bold text-gray-950">Analyze a new clip</h2>
                <p className="mt-1 text-sm text-gray-500">
                  Drop in a broadcast segment or paste a source URL to generate transcript-backed claim verdicts.
                </p>
              </div>
              <ClipUploader
                onSessionCreated={(id) => {
                  router.push(`/session/${id}`);
                }}
              />
            </div>
          </section>
        )}
      </div>
    </main>
  );
}

export default function HomePage() {
  return (
    <Suspense fallback={null}>
      <HomeInner />
    </Suspense>
  );
}

function ClaimResultCard({ claim }: { claim: SearchClaimResult }) {
  const verdict = claim.verdict_label || "UNVERIFIED";

  return (
    <Link
      href={`/session/${claim.session_id}?claim=${claim.claim_id}&t=${claim.start_ms}`}
      className="group overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-black/5 transition-shadow duration-200 hover:shadow-md"
    >
      <div className="relative aspect-video overflow-hidden rounded-2xl bg-gray-950">
        {claim.thumbnail_url ? (
          <img
            src={claim.thumbnail_url}
            alt={claim.session_title || "Session thumbnail"}
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-gray-950 via-gray-900 to-gray-800">
            <div className="rounded-full bg-white/10 px-4 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-white/80">
              Claim Moment
            </div>
          </div>
        )}

        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent px-4 py-3">
          <div className="flex items-center justify-between gap-2">
            <span className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-white backdrop-blur">
              Claim
            </span>
            <span className="rounded-md bg-black/75 px-2 py-1 text-xs font-medium text-white">
              {formatTimestamp(claim.start_ms)}
            </span>
          </div>
        </div>
      </div>

      <div className="space-y-3 p-4">
        <div className="space-y-1.5">
          <h3 className="line-clamp-2 text-sm font-medium leading-5 text-gray-950">
            {claim.claim_text}
          </h3>
          <p className="text-xs text-gray-500">
            {claim.session_title || "Untitled session"}
            {claim.channel_name ? ` • ${claim.channel_name}` : ""}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
          {claim.speaker && <span>{claim.speaker}</span>}
          {claim.speaker && <span>•</span>}
          <span>{timeAgo(claim.created_at)}</span>
        </div>

        <div className="flex items-center justify-between">
          <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${verdictChip(verdict)}`}>
            {verdict.replaceAll("_", " ")}
          </span>
          {claim.confidence != null && (
            <span className="text-xs font-medium text-gray-500">
              {Math.round(claim.confidence * 100)}%
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}

function normalizeSort(value: string | null): SortOption {
  return value === "most-claims" ? "most-claims" : "newest";
}

function normalizeMediaPath(path: string | null | undefined): string | null {
  if (!path) return null;
  return path.startsWith("/v1/") ? path.replace("/v1/", "/api/") : path;
}

function sortFeedItems(items: FeedItem[], sort: SortOption) {
  return [...items].sort((left, right) => {
    if (sort === "most-claims" && right.claims_count !== left.claims_count) {
      return right.claims_count - left.claims_count;
    }

    return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
  });
}

function getCategoryText(item: FeedItem) {
  if (item.kind === "claim") {
    return [item.claim_text, item.speaker, item.session_title, item.channel_name]
      .filter(Boolean)
      .join(" ");
  }

  return [item.title, item.channel_name].filter(Boolean).join(" ");
}

function inferCategory(input: string): Category {
  const text = input.toLowerCase();

  if (/(court|legal|judge|law|constitution|supreme|lawsuit|criminal)/.test(text)) {
    return "Legal";
  }

  if (/(economy|inflation|jobs|tax|wages|trade|budget|debt|gdp|tariff)/.test(text)) {
    return "Economy";
  }

  if (/(health|medicare|medicaid|vaccine|covid|hospital|insurance|abortion)/.test(text)) {
    return "Health";
  }

  return "Politics";
}

function verdictChip(verdict: string) {
  if (verdict === "TRUE") return "bg-green-100 text-green-700";
  if (verdict === "MOSTLY_TRUE") return "bg-lime-100 text-lime-700";
  if (verdict === "HALF_TRUE") return "bg-yellow-100 text-yellow-800";
  if (verdict === "MOSTLY_FALSE") return "bg-orange-100 text-orange-700";
  if (verdict === "FALSE") return "bg-red-100 text-red-700";
  return "bg-gray-100 text-gray-700";
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

function formatTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}
