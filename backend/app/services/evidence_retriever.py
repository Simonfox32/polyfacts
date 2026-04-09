"""Evidence retrieval: hybrid search (BM25 + embedding) + government API calls + web search.

Uses Reciprocal Rank Fusion to merge keyword and semantic results.
"""

import json
import time
from collections import defaultdict
from decimal import Decimal, InvalidOperation

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
        self._api_cache: dict[str, dict] = {}

    def _cache_key(self, api: str, identifier: str) -> str:
        return f"{api}:{identifier}"

    def _get_cached(self, key: str, max_age: int = 60) -> list[dict] | None:
        entry = self._api_cache.get(key)
        if entry and (time.time() - entry["ts"]) < max_age:
            log.debug("evidence_cache_hit", key=key)
            return entry["results"]
        return None

    def _set_cache(self, key: str, results: list[dict]) -> None:
        self._api_cache[key] = {"ts": time.time(), "results": results}

    def clear_cache(self) -> None:
        self._api_cache.clear()

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
        web_results = await self._web_search(claim_text, normalized_claim)

        total_raw = len(bm25_results) + len(embedding_results) + len(api_results) + len(web_results)
        log.info(
            "evidence_raw_counts",
            bm25=len(bm25_results),
            embedding=len(embedding_results),
            api=len(api_results),
            web=len(web_results),
        )
        if total_raw == 0:
            log.warning("evidence_no_raw_results", claim=claim_text[:100])

        # 5. RRF fusion
        fused = self._reciprocal_rank_fusion(bm25_results, embedding_results, api_results, web_results)

        rerank_candidates = fused[:15]
        reranked = await self._rerank_evidence(claim_text, rerank_candidates)

        # Return top 10 after LLM reranking
        results = reranked[: settings.max_evidence_sources]
        log.info("evidence_retrieve_done", count=len(results))
        return results

    async def _rerank_evidence(self, claim_text: str, evidence_list: list[dict]) -> list[dict]:
        """Rerank fused evidence candidates with Claude and fall back to original order."""
        if len(evidence_list) <= 1:
            return evidence_list

        candidate_lines = []
        for idx, evidence in enumerate(evidence_list):
            title = str(evidence.get("title", "")).strip() or "Untitled"
            snippet = str(evidence.get("snippet", "")).strip().replace("\n", " ")[:200]
            candidate_lines.append(
                f"{idx}. Title: {title}\n"
                f"Snippet: {snippet}"
            )

        prompt = (
            "Rank the evidence candidates by relevance to the claim.\n\n"
            f"Claim: {claim_text}\n\n"
            "Candidates:\n"
            f"{chr(10).join(candidate_lines)}\n\n"
            "Return ONLY a JSON array of candidate indices in descending relevance order. "
            f"Include the top {min(settings.max_evidence_sources, len(evidence_list))} indices only. "
            "Do not include any explanation or markdown."
        )

        try:
            response = await self.anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                messages=[{
                    "role": "user",
                    "content": prompt,
                }],
            )

            response_text = response.content[0].text.strip()
            if response_text.startswith("```"):
                response_text = response_text.split("\n", 1)[1]
            if response_text.endswith("```"):
                response_text = response_text.rsplit("```", 1)[0]
            response_text = response_text.strip()

            json_start = response_text.find("[")
            json_end = response_text.rfind("]") + 1
            if json_start < 0 or json_end <= json_start:
                raise ValueError("No JSON array found in rerank response")

            parsed_indices = json.loads(response_text[json_start:json_end])
            if not isinstance(parsed_indices, list):
                raise ValueError("Rerank response was not a list")

            seen_indices = set()
            ranked_indices = []
            for idx in parsed_indices:
                if not isinstance(idx, int):
                    raise ValueError("Rerank response contained a non-integer index")
                if idx < 0 or idx >= len(evidence_list):
                    raise ValueError("Rerank response contained an out-of-range index")
                if idx in seen_indices:
                    continue
                seen_indices.add(idx)
                ranked_indices.append(idx)

            if not ranked_indices:
                raise ValueError("Rerank response was empty after validation")

            remaining_indices = [
                idx for idx in range(len(evidence_list)) if idx not in seen_indices
            ]
            return [evidence_list[idx] for idx in ranked_indices + remaining_indices]
        except Exception as e:
            log.warning("evidence_rerank_error", error=str(e))
            return evidence_list

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
        if any(
            kw in claim_lower
            for kw in [
                "gdp",
                "inflation",
                "interest rate",
                "economy",
                "deficit",
                "trade deficit",
                "housing",
                "wage",
                "poverty",
            ]
        ):
            fred_results = await self._query_fred(claim_lower)
            results.extend(fred_results)

        # CDC data for health claims
        if any(
            kw in claim_lower
            for kw in [
                "deaths",
                "mortality",
                "covid",
                "vaccination",
                "life expectancy",
                "opioid",
                "health",
            ]
        ):
            cdc_results = await self._query_cdc()
            results.extend(cdc_results)

        # Treasury debt data for federal debt claims
        if any(
            kw in claim_lower
            for kw in ["national debt", "debt ceiling", "treasury", "federal debt"]
        ):
            treasury_results = await self._query_treasury()
            results.extend(treasury_results)

        # Census ACS data for demographic claims
        if any(
            kw in claim_lower
            for kw in [
                "population",
                "census",
                "demographic",
                "demographics",
                "poverty rate",
                "median income",
                "household income",
            ]
        ):
            census_results = await self._query_census()
            results.extend(census_results)

        # Congress.gov for legislative claims
        if any(kw in claim_lower for kw in ["bill", "law", "act", "congress", "legislation", "voted", "passed"]):
            congress_results = await self._query_congress(claim_text)
            results.extend(congress_results)

        return results

    async def _query_bls(self) -> list[dict]:
        """Query BLS API for unemployment rate data."""
        series_id = "LNS14000000"
        cache_key = self._cache_key("bls", series_id)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            response = await self.http_client.post(
                "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                json={
                    "seriesid": [series_id],  # Unemployment rate
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
                results = [{
                    "source_id": None,
                    "url": f"https://data.bls.gov/timeseries/{series_id}",
                    "title": "Labor Force Statistics — Unemployment Rate",
                    "publisher": "U.S. Bureau of Labor Statistics",
                    "source_tier": "tier_1_government_primary",
                    "snippet": snippet,
                    "retrieval_method": "api",
                    "score": 1.0,
                }]
                self._set_cache(cache_key, results)
                return results
            self._set_cache(cache_key, [])
        except Exception as e:
            log.warning("bls_api_error", error=str(e))
        return []

    async def _query_cdc(self) -> list[dict]:
        """Query CDC provisional COVID deaths data."""
        cache_key = self._cache_key("cdc", "provisional_covid_deaths")
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            response = await self.http_client.get(
                "https://data.cdc.gov/resource/bi63-dtpu.json",
                params={
                    "$limit": 10,
                    "$order": "end_date DESC",
                },
            )
            records = response.json()
            if isinstance(records, list) and records:
                snippet_parts = []
                for record in records[:5]:
                    end_date = self._first_present_value(record, "end_date", "submission_date", "date")
                    covid_deaths = self._first_present_value(
                        record,
                        "covid_19_deaths",
                        "covid_deaths",
                        "covid_death",
                    )
                    total_deaths = self._first_present_value(record, "total_deaths")

                    part = end_date or "Latest CDC record"
                    if covid_deaths:
                        part += f": COVID deaths {covid_deaths}"
                    if total_deaths:
                        part += f", total deaths {total_deaths}"
                    snippet_parts.append(part)

                results = [{
                    "source_id": None,
                    "url": "https://data.cdc.gov/resource/bi63-dtpu",
                    "title": "CDC Provisional COVID-19 Death Counts",
                    "publisher": "Centers for Disease Control and Prevention",
                    "source_tier": "tier_1_government_primary",
                    "snippet": "; ".join(snippet_parts),
                    "retrieval_method": "api",
                    "score": 1.0,
                }]
                self._set_cache(cache_key, results)
                return results
            self._set_cache(cache_key, [])
        except Exception as e:
            log.warning("cdc_api_error", error=str(e))
        return []

    async def _query_treasury(self) -> list[dict]:
        """Query Treasury Fiscal Data API for debt to the penny."""
        cache_key = self._cache_key("treasury", "debt_to_penny")
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            response = await self.http_client.get(
                "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny",
                params={
                    "sort": "-record_date",
                    "page[size]": 12,
                },
            )
            payload = response.json()
            records = payload.get("data", [])
            if records:
                snippet_parts = []
                for record in records[:5]:
                    record_date = self._first_present_value(record, "record_date", "date") or "Latest"
                    total_debt = self._format_amount(
                        self._first_present_value(
                            record,
                            "tot_pub_debt_out_amt",
                            "total_public_debt_outstanding_amt",
                            "tot_pub_debt_outstanding_amt",
                        )
                    )
                    debt_held_public = self._format_amount(
                        self._first_present_value(
                            record,
                            "debt_held_public_amt",
                            "debt_held_by_public_amt",
                        )
                    )
                    intragovernmental_holdings = self._format_amount(
                        self._first_present_value(
                            record,
                            "intragov_hold_amt",
                            "intragovernmental_holdings_amt",
                        )
                    )

                    part = f"{record_date}: total debt {total_debt or 'N/A'}"
                    if debt_held_public:
                        part += f", debt held by public {debt_held_public}"
                    if intragovernmental_holdings:
                        part += (
                            f", intragovernmental holdings {intragovernmental_holdings}"
                        )
                    snippet_parts.append(part)

                results = [{
                    "source_id": None,
                    "url": "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny",
                    "title": "Debt to the Penny",
                    "publisher": "U.S. Department of the Treasury",
                    "source_tier": "tier_1_government_primary",
                    "snippet": "; ".join(snippet_parts),
                    "retrieval_method": "api",
                    "score": 1.0,
                }]
                self._set_cache(cache_key, results)
                return results
            self._set_cache(cache_key, [])
        except Exception as e:
            log.warning("treasury_api_error", error=str(e))
        return []

    async def _query_fred(self, claim_lower: str) -> list[dict]:
        """Query FRED API for economic data."""
        if not settings.fred_api_key:
            return []

        # Map claim keywords to FRED series
        series_map = {
            "trade deficit": ("BOPGSTB", "Trade Balance: Goods and Services"),
            "gdp": ("GDP", "Gross Domestic Product"),
            "inflation": ("CPIAUCSL", "Consumer Price Index"),
            "interest rate": ("FEDFUNDS", "Federal Funds Rate"),
            "housing": ("HOUST", "Housing Starts"),
            "wage": ("CES0500000003", "Average Hourly Earnings"),
            "poverty": ("PPAAUS00000A156N", "Poverty Rate"),
            "deficit": ("FYFSD", "Federal Surplus or Deficit"),
        }

        for keyword, (series_id, title) in series_map.items():
            if keyword in claim_lower:
                cache_key = self._cache_key("fred", title)
                cached = self._get_cached(cache_key)
                if cached is not None:
                    return cached
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
                    if observations:
                        snippet = "; ".join(
                            f"{o['date']}: {o['value']}" for o in observations[:6]
                        )
                        results = [{
                            "source_id": None,
                            "url": f"https://fred.stlouisfed.org/series/{series_id}",
                            "title": title,
                            "publisher": "Federal Reserve Bank of St. Louis",
                            "source_tier": "tier_1_government_primary",
                            "snippet": snippet,
                            "retrieval_method": "api",
                            "score": 1.0,
                        }]
                        self._set_cache(cache_key, results)
                        return results
                    self._set_cache(cache_key, [])
                    return []
                except Exception as e:
                    log.warning("fred_api_error", error=str(e))
        return []

    async def _query_census(self) -> list[dict]:
        """Query Census ACS 5-year API for national demographic indicators."""
        cache_key = self._cache_key("census", "acs5:2022:us:1")
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            response = await self.http_client.get(
                "https://api.census.gov/data/2022/acs/acs5",
                params={
                    "get": "NAME,B01003_001E,B19013_001E,B17001_002E,B01002_001E",
                    "for": "us:1",
                },
            )
            data = response.json()
            if isinstance(data, list) and len(data) >= 2:
                headers = data[0]
                values = data[1]
                record = dict(zip(headers, values, strict=False))

                population = self._first_present_value(record, "B01003_001E")
                median_income = self._first_present_value(record, "B19013_001E")
                poverty_count = self._first_present_value(record, "B17001_002E")
                median_age = self._first_present_value(record, "B01002_001E")

                snippet_parts = []
                if population:
                    snippet_parts.append(
                        f"Total population: {int(population):,}"
                        if population.isdigit()
                        else f"Total population: {population}"
                    )
                if median_income:
                    snippet_parts.append(
                        f"Median household income: {self._format_amount(median_income) or median_income}"
                    )
                if poverty_count:
                    snippet_parts.append(
                        f"Poverty count: {int(poverty_count):,}"
                        if poverty_count.isdigit()
                        else f"Poverty count: {poverty_count}"
                    )
                if population and poverty_count and population.isdigit() and poverty_count.isdigit():
                    poverty_rate = (int(poverty_count) / int(population)) * 100
                    snippet_parts.append(f"Derived poverty rate: {poverty_rate:.1f}%")
                if median_age:
                    snippet_parts.append(f"Median age: {median_age}")

                results = [{
                    "source_id": None,
                    "url": "https://api.census.gov/data/2022/acs/acs5",
                    "title": "Census ACS 5-Year National Demographic Indicators",
                    "publisher": "U.S. Census Bureau",
                    "source_tier": "tier_1_government_primary",
                    "snippet": "; ".join(snippet_parts),
                    "retrieval_method": "api",
                    "score": 1.0,
                }]
                self._set_cache(cache_key, results)
                return results
            self._set_cache(cache_key, [])
        except Exception as e:
            log.warning("census_api_error", error=str(e))
        return []

    async def _query_congress(self, claim_text: str) -> list[dict]:
        """Query Congress.gov API for legislative information."""
        if not settings.congress_api_key:
            return []
        query_text = claim_text[:100].strip().lower()
        cache_key = self._cache_key("congress", query_text)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
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
            self._set_cache(cache_key, results)
            return results
        except Exception as e:
            log.warning("congress_api_error", error=str(e))
        return []

    def _build_search_query(
        self,
        claim_text: str,
        normalized_claim: dict | None = None,
        *,
        include_time_scope: bool = False,
    ) -> str:
        """Build a more targeted search query from normalized claim fields."""
        if not normalized_claim:
            return claim_text
        if isinstance(normalized_claim.get("normalized_claim"), dict):
            normalized_claim = normalized_claim["normalized_claim"]

        query_parts = [
            normalized_claim.get("subject", ""),
            normalized_claim.get("predicate", ""),
            normalized_claim.get("object", ""),
        ]

        qualifiers = normalized_claim.get("qualifiers") or []
        if isinstance(qualifiers, list):
            query_parts.extend(str(q).strip() for q in qualifiers if str(q).strip())

        if include_time_scope:
            query_parts.extend(self._extract_time_scope_terms(normalized_claim))

        deduped_parts = []
        seen_parts = set()
        for part in query_parts:
            if not part:
                continue
            normalized_part = part.lower()
            if normalized_part in seen_parts:
                continue
            seen_parts.add(normalized_part)
            deduped_parts.append(part)

        return " ".join(deduped_parts) or claim_text

    def _build_followup_search_query(
        self, claim_text: str, normalized_claim: dict | None, first_query: str
    ) -> str:
        """Build a second-pass web query with time scope when available."""
        time_scope_query = self._build_search_query(
            claim_text,
            normalized_claim,
            include_time_scope=True,
        )
        if time_scope_query != first_query:
            return time_scope_query
        if claim_text != first_query:
            return claim_text
        return f"{first_query} source data report"

    @staticmethod
    def _extract_time_scope_terms(normalized_claim: dict | None) -> list[str]:
        """Extract temporal cues from normalized claim data when present."""
        if not normalized_claim:
            return []

        time_terms = []
        time_scope = normalized_claim.get("time_scope", {})
        if isinstance(time_scope, dict):
            if time_scope.get("start_date"):
                time_terms.append(str(time_scope["start_date"]))
            if time_scope.get("end_date"):
                time_terms.append(str(time_scope["end_date"]))
            if time_scope.get("is_current"):
                time_terms.append("current")
            if time_scope.get("ambiguity_notes"):
                time_terms.append(str(time_scope["ambiguity_notes"]))
        else:
            if normalized_claim.get("start_date"):
                time_terms.append(str(normalized_claim["start_date"]))
            if normalized_claim.get("end_date"):
                time_terms.append(str(normalized_claim["end_date"]))
            if normalized_claim.get("is_current"):
                time_terms.append("current")
            if normalized_claim.get("ambiguity_notes"):
                time_terms.append(str(normalized_claim["ambiguity_notes"]))

        qualifiers = normalized_claim.get("qualifiers") or []
        temporal_markers = (
            "current",
            "currently",
            "today",
            "yesterday",
            "tomorrow",
            "annual",
            "annually",
            "monthly",
            "quarter",
            "q1",
            "q2",
            "q3",
            "q4",
            "week",
            "month",
            "year",
            "years",
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        )
        if isinstance(qualifiers, list):
            for qualifier in qualifiers:
                qualifier_text = str(qualifier).strip()
                if not qualifier_text:
                    continue
                qualifier_lower = qualifier_text.lower()
                if any(char.isdigit() for char in qualifier_text) or any(
                    marker in qualifier_lower for marker in temporal_markers
                ):
                    time_terms.append(qualifier_text)

        deduped_terms = []
        seen_terms = set()
        for term in time_terms:
            normalized_term = term.lower()
            if normalized_term in seen_terms:
                continue
            seen_terms.add(normalized_term)
            deduped_terms.append(term)
        return deduped_terms

    async def _run_web_search_pass(self, claim_text: str, search_query: str) -> list[dict]:
        """Run one web search pass using Brave Search API."""
        if not settings.brave_search_api_key:
            log.warning("brave_search_skipped", reason="no API key configured")
            return []

        try:
            response = await self.http_client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={
                    "q": search_query,
                    "count": 10,
                    "text_decorations": False,
                    "search_lang": "en",
                },
                headers={
                    "X-Subscription-Token": settings.brave_search_api_key,
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()

            results = []
            seen_urls = set()

            web_results = data.get("web", {}).get("results", [])
            for item in web_results:
                url = item.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                title = item.get("title", "")
                snippet = item.get("description", "")
                extra = item.get("extra_snippets", [])
                if extra:
                    snippet = snippet + " " + " ".join(extra[:2])

                tier = self._classify_source_tier(url)
                results.append({
                    "source_id": None,
                    "url": url,
                    "title": title,
                    "publisher": self._extract_publisher(url),
                    "source_tier": tier,
                    "snippet": snippet[:500],
                    "retrieval_method": "brave_web_search",
                    "score": 0.8,
                })

            log.info("brave_search_results", query=search_query[:80], count=len(results))
            return results
        except Exception as e:
            log.warning("brave_search_error", error=str(e), query=search_query[:120])
            return []

    @staticmethod
    def _dedupe_results_by_url(results: list[dict]) -> list[dict]:
        """Deduplicate result rows while preserving order."""
        deduped = []
        seen_urls = set()
        for result in results:
            url = result.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            deduped.append(result)
        return deduped

    async def _web_search(
        self, claim_text: str, normalized_claim: dict | None = None
    ) -> list[dict]:
        """Search the web for evidence using Brave Search API.

        Two-pass: first with targeted query, then a follow-up if too few results.
        """
        try:
            first_query = self._build_search_query(claim_text, normalized_claim)
            results = await self._run_web_search_pass(claim_text, first_query)

            if len(results) < 3:
                second_query = self._build_followup_search_query(
                    claim_text,
                    normalized_claim,
                    first_query,
                )
                second_results = await self._run_web_search_pass(claim_text, second_query)
                results = self._dedupe_results_by_url(results + second_results)

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

    @staticmethod
    def _first_present_value(record: dict, *keys: str) -> str | None:
        """Return the first non-empty value for the provided keys."""
        for key in keys:
            value = record.get(key)
            if value not in (None, ""):
                return str(value)
        return None

    @staticmethod
    def _format_amount(value: str | None) -> str | None:
        """Format numeric amounts for snippets while tolerating API string values."""
        if value in (None, ""):
            return None
        try:
            number = Decimal(value)
            if number == number.to_integral_value():
                return f"${int(number):,}"
            return f"${number:,.2f}"
        except (InvalidOperation, ValueError, TypeError):
            return value

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
