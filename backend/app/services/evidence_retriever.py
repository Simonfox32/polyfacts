"""Evidence retrieval: hybrid search (BM25 + embedding) + government API calls + web search.

Uses Reciprocal Rank Fusion to merge keyword and semantic results.
"""

import json
from collections import defaultdict

import anthropic
import httpx
import openai
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.claim import Source

log = structlog.get_logger()


class EvidenceRetriever:
    def __init__(self):
        self.openai_client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        self.anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.http_client = httpx.AsyncClient(timeout=30.0)

    async def retrieve(
        self, claim_text: str, normalized_claim: dict | None, db: AsyncSession
    ) -> list[dict]:
        """Retrieve evidence for a claim using hybrid search + government APIs.

        Returns list of evidence dicts: [{source_id, url, title, publisher, snippet, tier, relevance_score}]
        """
        log.info("evidence_retrieve_start", claim=claim_text[:100])

        results = []

        # 1. BM25 keyword search via PostgreSQL tsvector
        bm25_results = await self._bm25_search(claim_text, db)

        # 2. Dense embedding search via pgvector
        embedding_results = await self._embedding_search(claim_text, db)

        # 3. Government API calls for structured data
        api_results = await self._query_government_apis(claim_text, normalized_claim)

        # 4. Web search for broader evidence
        web_results = await self._web_search(claim_text)

        # 5. RRF fusion
        fused = self._reciprocal_rank_fusion(bm25_results, embedding_results, api_results, web_results)

        # Return top 10
        results = fused[: settings.max_evidence_sources]
        log.info("evidence_retrieve_done", count=len(results))
        return results

    async def _bm25_search(self, query: str, db: AsyncSession) -> list[dict]:
        """Full-text search using PostgreSQL tsvector."""
        sql = text("""
            SELECT id, url, title, publisher, source_tier, content_text,
                   ts_rank(to_tsvector('english', content_text), plainto_tsquery('english', :query)) as rank
            FROM sources
            WHERE to_tsvector('english', content_text) @@ plainto_tsquery('english', :query)
            ORDER BY rank DESC
            LIMIT 30
        """)
        result = await db.execute(sql, {"query": query})
        rows = result.fetchall()
        return [
            {
                "source_id": r.id,
                "url": r.url,
                "title": r.title,
                "publisher": r.publisher,
                "source_tier": r.source_tier,
                "snippet": (r.content_text or "")[:500],
                "retrieval_method": "bm25",
                "score": float(r.rank),
            }
            for r in rows
        ]

    async def _embedding_search(self, query: str, db: AsyncSession) -> list[dict]:
        """Semantic search using pgvector cosine similarity."""
        # Check if any embeddings exist first
        count_result = await db.execute(
            text("SELECT COUNT(*) FROM sources WHERE content_embedding IS NOT NULL")
        )
        if count_result.scalar() == 0:
            return []

        embedding = await self._get_embedding(query)
        if not embedding:
            return []

        sql = text("""
            SELECT id, url, title, publisher, source_tier, content_text,
                   1 - (content_embedding <=> CAST(:embedding AS vector)) as similarity
            FROM sources
            WHERE content_embedding IS NOT NULL
            ORDER BY content_embedding <=> CAST(:embedding AS vector)
            LIMIT 30
        """)
        result = await db.execute(sql, {"embedding": str(embedding)})
        rows = result.fetchall()
        return [
            {
                "source_id": r.id,
                "url": r.url,
                "title": r.title,
                "publisher": r.publisher,
                "source_tier": r.source_tier,
                "snippet": (r.content_text or "")[:500],
                "retrieval_method": "embedding",
                "score": float(r.similarity),
            }
            for r in rows
        ]

    async def _get_embedding(self, text: str) -> list[float] | None:
        """Get embedding from OpenAI text-embedding-3-small."""
        try:
            response = await self.openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=text,
            )
            return response.data[0].embedding
        except Exception as e:
            log.warning("embedding_error", error=str(e))
            return None

    async def _query_government_apis(
        self, claim_text: str, normalized_claim: dict | None
    ) -> list[dict]:
        """Query structured government APIs based on claim content."""
        results = []
        claim_lower = claim_text.lower()

        # BLS API for employment/labor claims
        if any(kw in claim_lower for kw in ["unemployment", "jobs", "employment", "labor"]):
            bls_results = await self._query_bls()
            results.extend(bls_results)

        # FRED API for economic claims
        if any(kw in claim_lower for kw in ["gdp", "inflation", "interest rate", "economy", "deficit"]):
            fred_results = await self._query_fred(claim_lower)
            results.extend(fred_results)

        # Congress.gov for legislative claims
        if any(kw in claim_lower for kw in ["bill", "law", "act", "congress", "legislation", "voted", "passed"]):
            congress_results = await self._query_congress(claim_text)
            results.extend(congress_results)

        return results

    async def _query_bls(self) -> list[dict]:
        """Query BLS API for unemployment rate data."""
        try:
            response = await self.http_client.post(
                "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                json={
                    "seriesid": ["LNS14000000"],  # Unemployment rate
                    "startyear": "2020",
                    "endyear": "2026",
                    "registrationkey": settings.bls_api_key or None,
                },
            )
            data = response.json()
            if data.get("status") == "REQUEST_SUCCEEDED":
                series = data.get("Results", {}).get("series", [{}])[0]
                values = series.get("data", [])[:12]
                snippet = "; ".join(
                    f"{v['periodName']} {v['year']}: {v['value']}%" for v in values
                )
                return [{
                    "source_id": None,
                    "url": "https://data.bls.gov/timeseries/LNS14000000",
                    "title": "Labor Force Statistics — Unemployment Rate",
                    "publisher": "U.S. Bureau of Labor Statistics",
                    "source_tier": "tier_1_government_primary",
                    "snippet": snippet,
                    "retrieval_method": "api",
                    "score": 1.0,
                }]
        except Exception as e:
            log.warning("bls_api_error", error=str(e))
        return []

    async def _query_fred(self, claim_lower: str) -> list[dict]:
        """Query FRED API for economic data."""
        if not settings.fred_api_key:
            return []

        # Map claim keywords to FRED series
        series_map = {
            "gdp": ("GDP", "Gross Domestic Product"),
            "inflation": ("CPIAUCSL", "Consumer Price Index"),
            "interest rate": ("FEDFUNDS", "Federal Funds Rate"),
            "deficit": ("FYFSD", "Federal Surplus or Deficit"),
        }

        for keyword, (series_id, title) in series_map.items():
            if keyword in claim_lower:
                try:
                    response = await self.http_client.get(
                        "https://api.stlouisfed.org/fred/series/observations",
                        params={
                            "series_id": series_id,
                            "api_key": settings.fred_api_key,
                            "file_type": "json",
                            "sort_order": "desc",
                            "limit": 12,
                        },
                    )
                    data = response.json()
                    observations = data.get("observations", [])
                    snippet = "; ".join(
                        f"{o['date']}: {o['value']}" for o in observations[:6]
                    )
                    return [{
                        "source_id": None,
                        "url": f"https://fred.stlouisfed.org/series/{series_id}",
                        "title": title,
                        "publisher": "Federal Reserve Bank of St. Louis",
                        "source_tier": "tier_1_government_primary",
                        "snippet": snippet,
                        "retrieval_method": "api",
                        "score": 1.0,
                    }]
                except Exception as e:
                    log.warning("fred_api_error", error=str(e))
        return []

    async def _query_congress(self, claim_text: str) -> list[dict]:
        """Query Congress.gov API for legislative information."""
        if not settings.congress_api_key:
            return []
        try:
            # Extract keywords for search
            response = await self.http_client.get(
                "https://api.congress.gov/v3/bill",
                params={
                    "query": claim_text[:100],
                    "limit": 5,
                    "api_key": settings.congress_api_key,
                },
            )
            data = response.json()
            results = []
            for bill in data.get("bills", [])[:3]:
                results.append({
                    "source_id": None,
                    "url": bill.get("url", ""),
                    "title": bill.get("title", ""),
                    "publisher": "Congress.gov",
                    "source_tier": "tier_1_government_primary",
                    "snippet": f"{bill.get('number', '')}: {bill.get('title', '')}",
                    "retrieval_method": "api",
                    "score": 0.9,
                })
            return results
        except Exception as e:
            log.warning("congress_api_error", error=str(e))
        return []

    async def _web_search(self, claim_text: str) -> list[dict]:
        """Search the web for evidence using Anthropic's web search tool.

        Two-step: (1) web search to find sources, (2) ask Claude to summarize
        what each source specifically says about the claim.
        """
        try:
            # Step 1: Web search — find relevant sources
            response = await self.anthropic_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                tools=[{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 3,
                }],
                messages=[{
                    "role": "user",
                    "content": (
                        f"Find factual evidence for or against this political claim. "
                        f"Search for authoritative sources (government data, major news outlets, academic studies).\n\n"
                        f"Claim: \"{claim_text}\"\n\n"
                        f"After searching, respond with a JSON array of the sources you found. "
                        f"For EACH source, write a UNIQUE snippet summarizing what THAT SPECIFIC source says about the claim. "
                        f"Do NOT repeat the same snippet for multiple sources.\n\n"
                        f"Format:\n"
                        f"[{{\"url\": \"...\", \"title\": \"...\", \"snippet\": \"What this specific source says about the claim\", "
                        f"\"relevance\": \"supports|contradicts|provides_context\"}}]"
                    ),
                }],
            )

            # Extract structured results from Claude's response
            result_text = ""
            source_urls = []  # Collect URLs from search results as backup

            for block in response.content:
                if block.type == "text":
                    result_text += block.text
                elif block.type == "web_search_tool_result":
                    if isinstance(block.content, list):
                        for sr in block.content:
                            if sr.type == "web_search_result":
                                source_urls.append({"url": sr.url, "title": sr.title or ""})

            # Try to parse Claude's structured response
            result_text = result_text.strip()
            if result_text.startswith("```"):
                result_text = result_text.split("\n", 1)[1]
            if result_text.endswith("```"):
                result_text = result_text.rsplit("```", 1)[0]
            result_text = result_text.strip()

            # Find JSON array in the response
            json_start = result_text.find("[")
            json_end = result_text.rfind("]") + 1

            results = []
            seen_urls = set()

            if json_start >= 0 and json_end > json_start:
                try:
                    parsed = json.loads(result_text[json_start:json_end])
                    for item in parsed:
                        url = item.get("url", "")
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)

                        tier = self._classify_source_tier(url)
                        results.append({
                            "source_id": None,
                            "url": url,
                            "title": item.get("title", ""),
                            "publisher": self._extract_publisher(url),
                            "source_tier": tier,
                            "snippet": item.get("snippet", item.get("title", ""))[:500],
                            "retrieval_method": "web_search",
                            "score": 0.8,
                        })
                except json.JSONDecodeError:
                    pass

            # Fallback: if JSON parsing failed, use raw search result URLs with text summary
            if not results and source_urls:
                for src in source_urls:
                    url = src["url"]
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    tier = self._classify_source_tier(url)
                    results.append({
                        "source_id": None,
                        "url": url,
                        "title": src["title"],
                        "publisher": self._extract_publisher(url),
                        "source_tier": tier,
                        "snippet": result_text[:300] if result_text else src["title"],
                        "retrieval_method": "web_search",
                        "score": 0.7,
                    })

            log.info("web_search_done", results=len(results))
            return results

        except Exception as e:
            log.warning("web_search_error", error=str(e))
            return []

    @staticmethod
    def _classify_source_tier(url: str) -> str:
        """Classify a URL into a source tier."""
        url_lower = url.lower()
        if any(d in url_lower for d in [".gov", ".mil", "census.gov", "bls.gov", "fred.stlouisfed.org"]):
            return "tier_1_government_primary"
        if any(d in url_lower for d in [".edu", "courtlistener.com", "scholar.google", "jstor.org", "pubmed"]):
            return "tier_2_court_academic"
        if any(d in url_lower for d in [
            "apnews.com", "reuters.com", "nytimes.com", "wsj.com", "washingtonpost.com",
            "bbc.com", "bbc.co.uk", "pbs.org", "npr.org", "politifact.com", "factcheck.org",
        ]):
            return "tier_3_major_outlet"
        if any(d in url_lower for d in [".org", "state.", "thehill.com", "politico.com"]):
            return "tier_4_regional_specialty"
        return "tier_5_other"

    @staticmethod
    def _extract_publisher(url: str) -> str:
        """Extract a publisher name from a URL."""
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return "Unknown"

    def _reciprocal_rank_fusion(self, *result_lists: list[dict], k: int = 60) -> list[dict]:
        """Merge multiple ranked lists using RRF."""
        scores: dict[str, float] = defaultdict(float)
        docs: dict[str, dict] = {}

        for result_list in result_lists:
            for rank, doc in enumerate(result_list):
                # Use URL as dedup key
                key = doc["url"]
                scores[key] += 1.0 / (k + rank + 1)
                # Keep the highest-tier version
                if key not in docs or self._tier_rank(doc["source_tier"]) < self._tier_rank(
                    docs[key]["source_tier"]
                ):
                    docs[key] = doc

        sorted_keys = sorted(scores.keys(), key=lambda x: -scores[x])
        return [docs[k] for k in sorted_keys if k in docs]

    @staticmethod
    def _tier_rank(tier: str) -> int:
        tiers = {
            "tier_1_government_primary": 1,
            "tier_2_court_academic": 2,
            "tier_3_major_outlet": 3,
            "tier_4_regional_specialty": 4,
            "tier_5_other": 5,
        }
        return tiers.get(tier, 5)
