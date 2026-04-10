"""Verdict generation: retrieval-gated, citation-anchored LLM verdicts.

Enforces mandatory retrieval before generation and validates citations.
"""

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone

import anthropic
import structlog

from app.config import settings

log = structlog.get_logger()

VERDICT_PROMPT = """You are a political fact-checking system. Your role is to evaluate claims based ONLY on the retrieved evidence provided below.

RULES:
1. You MUST base your verdict ONLY on the evidence passages below. Do NOT use prior knowledge.
2. Every factual assertion in your rationale MUST cite a source using [SOURCE_N] notation.
3. If no evidence supports or contradicts the claim, output verdict "UNVERIFIED".
4. Do NOT generate any claim about the world that is not directly supported by the evidence.
5. Distinguish between "investigated" vs "charged" vs "convicted" — use precise language.
6. If a claim states a number (e.g., "40%") and the data shows a different number (e.g., "38.7%"), note the discrepancy.
7. If the claim hinges on an ambiguous definition, evaluate under all reasonable definitions and note the ambiguity.

CLAIM:
"{claim_text}"

SPEAKER: {speaker}
CONTEXT: Spoken at timestamp {start_ms}ms-{end_ms}ms

NORMALIZED CLAIM:
Subject: {subject}
Predicate: {predicate}
Object: {object}

EVIDENCE PASSAGES:
{evidence_block}

Respond ONLY with a JSON object (no markdown, no explanation):
{{
  "verdict_label": "TRUE|MOSTLY_TRUE|HALF_TRUE|MOSTLY_FALSE|FALSE|UNVERIFIED",
  "confidence": 0.0-1.0,
  "rationale_summary": "One sentence summary (max 280 chars)",
  "rationale_bullets": ["Bullet 1 with [SOURCE_N] citation", "Bullet 2..."],
  "what_would_change_verdict": "Description of what new evidence would change this verdict"
}}"""


class VerdictEngine:
    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def _call_anthropic(self, **kwargs):
        """Call Anthropic API with retry on overloaded (529) errors."""
        for attempt in range(4):
            try:
                return await self.client.messages.create(**kwargs)
            except anthropic.APIStatusError as e:
                if e.status_code == 529 and attempt < 3:
                    wait = (attempt + 1) * 10
                    log.warning("anthropic_overloaded_retry", attempt=attempt, wait=wait)
                    await asyncio.sleep(wait)
                else:
                    raise

    async def generate_verdict(
        self,
        claim_text: str,
        normalized_claim: dict | None,
        speaker: str | None,
        start_ms: int,
        end_ms: int,
        evidence: list[dict],
    ) -> dict:
        """Generate a verdict for a claim given retrieved evidence.

        Returns verdict dict with label, confidence, rationale, and citations.
        """
        log.info("verdict_generate_start", claim=claim_text[:100], evidence_count=len(evidence))

        # If no evidence, return UNVERIFIED immediately
        if len(evidence) < 1:
            return {
                "verdict_label": "UNVERIFIED",
                "confidence": None,
                "rationale_summary": "Insufficient evidence retrieved to evaluate this claim.",
                "rationale_bullets": [
                    f"Only {len(evidence)} evidence passage(s) found; minimum 1 required for a verdict."
                ],
                "what_would_change_verdict": "Additional authoritative sources addressing this specific claim.",
            }

        # Build evidence block
        evidence_block = self._format_evidence(evidence)

        # Extract normalized claim fields
        nc = normalized_claim or {}
        subject = nc.get("subject", "Unknown")
        predicate = nc.get("predicate", "Unknown")
        obj = nc.get("object", claim_text)

        prompt = VERDICT_PROMPT.format(
            claim_text=claim_text,
            speaker=speaker or "Unknown",
            start_ms=start_ms,
            end_ms=end_ms,
            subject=subject,
            predicate=predicate,
            object=obj,
            evidence_block=evidence_block,
        )

        # Generate verdict (with retry on citation validation failure)
        for attempt in range(3):
            response = await self._call_anthropic(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )

            text = response.content[0].text.strip()
            verdict = self._parse_verdict(text)

            if verdict and self._validate_citations(verdict, evidence):
                verdict["model_used"] = "claude-sonnet-4-20250514"
                verdict["prompt_hash"] = hashlib.sha256(prompt.encode()).hexdigest()[:16]
                log.info(
                    "verdict_generate_done",
                    label=verdict["verdict_label"],
                    confidence=verdict.get("confidence"),
                    attempt=attempt + 1,
                )
                return verdict

            log.warning("verdict_citation_validation_failed", attempt=attempt + 1)

        # Fallback after 3 failed attempts
        log.error("verdict_generation_failed_all_attempts")
        return {
            "verdict_label": "UNVERIFIED",
            "confidence": None,
            "rationale_summary": "Unable to generate a well-cited verdict for this claim.",
            "rationale_bullets": ["Verdict generation failed citation validation after 3 attempts."],
            "what_would_change_verdict": "Manual review required.",
        }

    def _format_evidence(self, evidence: list[dict]) -> str:
        """Format evidence passages for the prompt."""
        lines = []
        for i, e in enumerate(evidence):
            lines.append(
                f"[SOURCE_{i + 1}] {e.get('title', 'Unknown')} "
                f"({e.get('publisher', 'Unknown')}, {e.get('source_tier', 'unknown')})\n"
                f"URL: {e.get('url', 'N/A')}\n"
                f"Snippet: {e.get('snippet', 'No content')}\n"
            )
        return "\n".join(lines)

    def _parse_verdict(self, text: str) -> dict | None:
        """Parse LLM response into verdict dict."""
        # Strip markdown fences
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.warning("verdict_parse_error", raw=text[:200])
            return None

    def _extract_non_trivial_words(self, text: str) -> set[str]:
        """Extract normalized words suitable for lightweight citation overlap checks."""
        return {
            word
            for word in re.findall(r"\b[a-z0-9']+\b", text.lower())
            if len(word) > 3
        }

    def _get_citation_sentence(self, bullet: str, citation: str) -> str:
        """Return the sentence containing a citation, falling back to the full bullet."""
        sentences = re.split(r"(?<=[.!?])\s+", bullet)
        for sentence in sentences:
            if citation in sentence:
                return sentence
        return bullet

    def _validate_citations(self, verdict: dict, evidence: list[dict]) -> bool:
        """Validate that all [SOURCE_N] references map to actual evidence."""
        bullets = verdict.get("rationale_bullets", [])
        all_text = " ".join(bullets)

        # Find all SOURCE_N references
        citations = re.findall(r"\[SOURCE_(\d+)\]", all_text)
        max_source = len(evidence)

        for cite_num in citations:
            if int(cite_num) < 1 or int(cite_num) > max_source:
                return False

        for bullet in bullets:
            bullet_citations = re.findall(r"\[SOURCE_(\d+)\]", bullet)
            if not bullet_citations:
                continue

            bullet_words = self._extract_non_trivial_words(bullet)
            for cite_num in bullet_citations:
                citation = f"[SOURCE_{cite_num}]"
                snippet = evidence[int(cite_num) - 1].get("snippet", "")
                snippet_words = self._extract_non_trivial_words(snippet)
                sentence = self._get_citation_sentence(bullet, citation)
                sentence_words = self._extract_non_trivial_words(sentence)
                overlap_count = len(snippet_words & (sentence_words | bullet_words))

                if overlap_count == 0:
                    log.warning(
                        "verdict_citation_keyword_overlap_zero",
                        source_num=int(cite_num),
                        bullet=bullet[:240],
                        snippet=snippet[:240],
                    )

        # At least one bullet should have a citation (unless UNVERIFIED)
        if verdict.get("verdict_label") != "UNVERIFIED" and not citations:
            return False

        summary = verdict.get("rationale_summary", "")
        summary_lower = summary.lower()
        label = verdict.get("verdict_label", "").upper()

        if label in {"TRUE", "MOSTLY_TRUE"} and re.search(
            r"\b(false|incorrect|wrong|inaccurate)\b", summary_lower
        ):
            return False

        if label in {"FALSE", "MOSTLY_FALSE"} and re.search(
            r"\b(confirmed|accurate|correct|true)\b", summary_lower
        ):
            return False

        return True

    def compute_heuristic_confidence(
        self,
        claim_worthiness: float,
        evidence_count: int,
        source_tiers: list[str],
    ) -> float:
        """Compute heuristic confidence score for MVP (no calibration model)."""
        # Factor 1: Claim worthiness score
        f1 = claim_worthiness

        # Factor 2: Evidence count (normalized to 0-1, cap at 5)
        f2 = min(evidence_count / 5.0, 1.0)

        # Factor 3: Source tier quality (best tier among evidence)
        tier_scores = {
            "tier_1_government_primary": 1.0,
            "tier_2_court_academic": 0.85,
            "tier_3_major_outlet": 0.7,
            "tier_4_regional_specialty": 0.5,
            "tier_5_other": 0.3,
        }
        f3 = max((tier_scores.get(t, 0.3) for t in source_tiers), default=0.3)
        f4 = min(len({tier for tier in source_tiers if tier}) / 3.0, 1.0)

        return round((0.20 * f1) + (0.35 * f2) + (0.30 * f3) + (0.15 * f4), 2)
