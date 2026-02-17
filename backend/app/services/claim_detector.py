"""Claim detection: two-stage pipeline.

Stage 1: Heuristic claim worthiness classifier (fast, CPU) — V1: fine-tuned DeBERTa
Stage 2: Claude Haiku structured extraction (normalized claim struct)
"""

import json
import re

import anthropic
import structlog

from app.config import settings

log = structlog.get_logger()

CLAIM_EXTRACTION_PROMPT = """You are a claim extraction system for a political fact-checking tool.

Given a sentence from a political speech or broadcast, extract the structured claim information.

Respond ONLY with a JSON object (no markdown, no explanation) with these fields:
{{
  "normalized_claim": {{
    "subject": "the entity or topic",
    "predicate": "the action or relationship",
    "object": "what is being claimed about the subject",
    "qualifiers": ["any temporal, geographic, or conditional qualifiers"]
  }},
  "time_scope": {{
    "start_date": "YYYY-MM-DD or null",
    "end_date": "YYYY-MM-DD or null",
    "is_current": true/false,
    "ambiguity_notes": "any ambiguity in the time reference or null"
  }},
  "location_scope": "geographic scope or null",
  "claim_type": "checkable_fact|opinion|forecast|definition|value_judgment",
  "required_evidence_types": ["primary_government_data", "court_record", "academic_study", "news_report", "expert_testimony", "legislative_record"]
}}

Sentence: "{sentence}"
Speaker: {speaker}"""


class ClaimDetector:
    def __init__(self):
        self.anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._classifier = None

    async def score_claim_worthiness(self, sentence: str) -> float:
        """Score a sentence for claim-worthiness (0-1).

        MVP: Uses heuristic rules. V1: Fine-tuned DeBERTa.
        """
        score = 0.0
        lower = sentence.lower()
        words = lower.split()

        # --- Negative signals (apply first) ---

        # Questions are almost never checkable claims
        if sentence.strip().endswith("?"):
            return 0.0

        # Very short sentences are not checkable
        if len(words) < 6:
            return 0.0

        # Procedural / conversational speech — not claims
        procedural_patterns = [
            "thank you", "mister chairman", "mister chair", "madam chair",
            "i yield", "yield back", "the gentleman", "the gentlewoman",
            "i ask unanimous consent", "unanimous consent", "without objection",
            "is recognized", "let me", "let's move", "we'll take",
            "good evening", "good morning", "welcome to", "my time",
            "reclaiming my time", "point of order", "order in the",
            "i'd like to", "i want to ask", "can you tell",
            "would you agree", "isn't it true that", "do you believe",
            "alright", "okay so", "moving on",
        ]
        for pattern in procedural_patterns:
            if pattern in lower:
                return 0.0

        # Direct questions phrased as statements
        question_starters = [
            "did you", "do you", "have you", "are you", "were you",
            "was it", "is it", "can you", "could you", "will you",
            "would you", "how many", "how much", "what is", "what are",
            "who is", "who are", "when did", "where did", "why did",
        ]
        for qs in question_starters:
            if lower.startswith(qs):
                return 0.0

        # Opinion indicators reduce score
        opinion_words = [
            "i think", "i believe", "in my opinion", "we should",
            "we need to", "it's time to", "we must", "i feel",
            "it seems", "i hope", "i wish",
        ]
        for kw in opinion_words:
            if kw in lower:
                score -= 0.2
                break

        # --- Positive signals ---

        # Numeric claims with actual digits are strong signals
        has_digits = bool(re.search(r'\d', sentence))
        if has_digits:
            score += 0.35

        # Number words — but only quantitative ones, not "one" in isolation
        strong_number_words = [
            "two", "three", "four", "five", "six", "seven", "eight",
            "nine", "ten", "hundred", "thousand", "million", "billion", "trillion",
            "dozen", "double", "triple", "twice", "half", "quarter",
        ]
        if any(w in words for w in strong_number_words):
            score += 0.3

        # Statistical/quantitative language
        stat_keywords = [
            "percent", "%", "rate", "average", "total",
            "increased", "decreased", "grew", "fell", "dropped", "rose",
            "highest", "lowest", "record", "all-time", "more than", "less than",
            "up from", "down from",
        ]
        for kw in stat_keywords:
            if kw in lower:
                score += 0.2
                break

        # Policy/action claims
        policy_keywords = [
            "passed", "signed", "voted", "enacted", "repealed",
            "spent", "funded", "allocated", "invested", "cut",
            "created", "eliminated", "banned", "legalized",
            "deported", "arrested", "convicted", "charged", "indicted",
        ]
        for kw in policy_keywords:
            if kw in lower:
                score += 0.2
                break

        # Verifiable factual assertions (past tense actions, events)
        factual_verbs = [
            "said", "stated", "claimed", "announced", "confirmed",
            "denied", "admitted", "revealed", "testified", "interviewed",
            "hired", "fired", "appointed", "resigned", "removed",
            "released", "published", "investigated", "found",
            "received", "gave", "sent", "met", "visited",
            "refused", "agreed", "rejected", "approved", "blocked",
        ]
        for kw in factual_verbs:
            if kw in words:
                score += 0.2
                break

        # Named roles/positions — claims about specific officials are often checkable
        role_keywords = [
            "president", "vice president", "senator", "congressman",
            "congresswoman", "representative", "governor", "mayor",
            "attorney general", "secretary", "director", "judge",
            "justice", "chief", "deputy", "prosecutor", "defense attorney",
            "speaker", "chairman", "ambassador", "general",
        ]
        for kw in role_keywords:
            if kw in lower:
                score += 0.15
                break

        # Temporal references make claims more specific and checkable
        temporal_keywords = [
            "yesterday", "last week", "last month", "last year",
            "this year", "this week", "in january", "in february",
            "in march", "in april", "in may", "in june", "in july",
            "in august", "in september", "in october", "in november",
            "in december", "recently", "formerly", "former",
        ]
        for kw in temporal_keywords:
            if kw in lower:
                score += 0.1
                break

        # Attribution to sources strengthens claim
        if any(kw in lower for kw in ["according to", "report shows", "study found",
                                       "data shows", "statistics show", "fbi", "cbo",
                                       "bureau of", "department of"]):
            score += 0.15

        # Comparative claims
        if any(kw in lower for kw in ["more than", "less than", "higher than",
                                       "lower than", "worst", "best", "largest",
                                       "smallest", "biggest"]):
            score += 0.1

        # Proper nouns (capitalized words in the middle of the sentence) — names, places
        mid_sentence_caps = re.findall(r'(?<!\. )(?<!^)[A-Z][a-z]+', sentence)
        if len(mid_sentence_caps) >= 2:
            score += 0.15

        # Longer declarative sentences are more likely to contain claims
        if len(words) >= 15:
            score += 0.05
        if len(words) >= 10:
            score += 0.05

        return max(0.0, min(1.0, score))

    async def extract_claim_struct(
        self, sentence: str, speaker: str | None = None
    ) -> dict:
        """Extract structured claim information using Claude Haiku."""
        prompt = CLAIM_EXTRACTION_PROMPT.format(
            sentence=sentence,
            speaker=speaker or "Unknown",
        )

        response = await self.anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.warning("claim_extraction_parse_error", raw=text[:200])
            return {
                "normalized_claim": {"subject": "", "predicate": "", "object": sentence, "qualifiers": []},
                "claim_type": "checkable_fact",
                "time_scope": {"is_current": True},
                "location_scope": None,
                "required_evidence_types": ["news_report"],
            }
