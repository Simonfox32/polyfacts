"""Pipeline orchestrator: processes a clip end-to-end.

Audio → ASR → Speaker ID → Claim Detection → Evidence Retrieval → Verdict Generation
"""

import json
from datetime import datetime, timezone

import anthropic
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.claim import Claim, EvidencePassage, Source, VerdictAuditLog
from app.models.session import Session, TranscriptSegment
from app.services.asr_pipeline import ASRPipeline
from app.services.claim_detector import ClaimDetector
from app.services.evidence_retriever import EvidenceRetriever
from app.services.verdict_engine import VerdictEngine

log = structlog.get_logger()


class PipelineOrchestrator:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.asr = ASRPipeline()
        self.detector = ClaimDetector()
        self.retriever = EvidenceRetriever()
        self.verdict_engine = VerdictEngine()
        self.anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def process_clip(self, session_id: str) -> None:
        """Process a clip through the full pipeline."""
        result = await self.db.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if not session:
            log.error("session_not_found", session_id=session_id)
            return

        try:
            # Stage 1: ASR
            await self._update_status(session, "processing", "asr", 10)
            segments = await self.asr.transcribe_file(session.audio_file_path)
            await self._update_status(session, "processing", "asr", 20)

            # Stage 1.5: Speaker Identification
            await self._update_status(session, "processing", "speaker_identification", 22)
            segments = await self._identify_speakers(segments)
            await self._store_transcript(session_id, segments)
            await self._update_status(session, "processing", "speaker_identification", 28)

            # Stage 2: Claim Detection
            await self._update_status(session, "processing", "claim_detection", 30)
            claims = await self._detect_claims(session_id, segments)
            await self._update_status(session, "processing", "claim_detection", 50)

            # Stage 3: Evidence Retrieval + Verdict Generation
            total_claims = len(claims)
            for i, claim in enumerate(claims):
                pct = 50 + int((i / max(total_claims, 1)) * 40)
                await self._update_status(session, "processing", "evidence_retrieval", pct)

                # Retrieve evidence
                evidence = await self.retriever.retrieve(
                    claim.claim_text, claim.normalized_claim, self.db
                )

                # Store evidence
                await self._store_evidence(claim, evidence)

                # Generate verdict
                await self._update_status(session, "processing", "verdict_generation", pct + 5)
                verdict = await self.verdict_engine.generate_verdict(
                    claim_text=claim.claim_text,
                    normalized_claim=claim.normalized_claim,
                    speaker=claim.speaker_label,
                    start_ms=claim.start_ms,
                    end_ms=claim.end_ms,
                    evidence=evidence,
                )

                # Store verdict
                await self._store_verdict(claim, verdict, evidence)

            # Done
            session.status = "completed"
            session.processing_stage = None
            session.progress_pct = 100
            session.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
            log.info("pipeline_complete", session_id=session_id, claims=total_claims)

        except Exception as e:
            log.error("pipeline_error", session_id=session_id, error=str(e), exc_info=True)
            session.status = "failed"
            session.error_message = str(e)[:1000]
            await self.db.commit()

    async def _update_status(
        self, session: Session, status: str, stage: str, pct: int
    ) -> None:
        session.status = status
        session.processing_stage = stage
        session.progress_pct = pct
        await self.db.commit()

    async def _store_transcript(self, session_id: str, segments: list[dict]) -> None:
        for seg in segments:
            ts = TranscriptSegment(
                session_id=session_id,
                speaker_label=seg.get("speaker_label"),
                text=seg["text"],
                start_ms=seg["start_ms"],
                end_ms=seg["end_ms"],
            )
            self.db.add(ts)
        await self.db.commit()

    async def _identify_speakers(self, segments: list[dict]) -> list[dict]:
        """Identify speakers by web-searching each speaker's quotes individually."""
        if not segments:
            return segments

        unique_speakers = set(seg.get("speaker_label", "") for seg in segments)

        # For each unique speaker, collect their most distinctive quotes
        speaker_quotes: dict[str, list[str]] = {}
        for speaker_label in unique_speakers:
            speaker_segs = [s for s in segments if s.get("speaker_label") == speaker_label]
            # Sort by length descending — longer utterances are more searchable
            speaker_segs.sort(key=lambda s: len(s["text"]), reverse=True)
            quotes = []
            for seg in speaker_segs[:3]:
                text = seg["text"].strip()
                if len(text) > 30:
                    quotes.append(text[:200])
            if quotes:
                speaker_quotes[speaker_label] = quotes

        if not speaker_quotes:
            return segments

        # Also build context: what does each speaker say and who do they address?
        context_lines = []
        for seg in segments[:30]:
            context_lines.append(f'{seg.get("speaker_label", "?")}: {seg["text"][:100]}')
        context_block = "\n".join(context_lines)

        # Search each speaker's quotes individually to find specific attribution
        speaker_map: dict[str, dict] = {}
        for label, quotes in speaker_quotes.items():
            quote_block = "\n".join(f'  - "{q}"' for q in quotes)

            prompt = f"""I need to identify ONE specific speaker from a political broadcast. This speaker is labeled "{label}" in the transcript.

Here are quotes ONLY from {label}:
{quote_block}

Here is broader transcript context showing the conversation:
{context_block[:2000]}

Search the web for the quotes above. Find news articles or transcripts that attribute these SPECIFIC words to a SPECIFIC person. Pay close attention to:
- Who is QUOTED as saying these exact words (not just mentioned in the same article)
- If {label} says "I ask you, Attorney General Bondi" — then {label} is NOT Bondi, they are questioning Bondi
- If {label} is answering questions and defending positions, they are likely the witness/official being questioned

Respond ONLY with a JSON object for this one speaker:
{{"name": "Full Name with Title", "party": "D or R or null"}}"""

            try:
                response = await self.anthropic_client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=512,
                    tools=[{
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": 2,
                    }],
                    messages=[{"role": "user", "content": prompt}],
                )

                result_text = ""
                for block in response.content:
                    if block.type == "text":
                        result_text += block.text

                result_text = result_text.strip()
                if result_text.startswith("```"):
                    result_text = result_text.split("\n", 1)[1]
                if result_text.endswith("```"):
                    result_text = result_text.rsplit("```", 1)[0]
                result_text = result_text.strip()

                json_start = result_text.find("{")
                json_end = result_text.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    info = json.loads(result_text[json_start:json_end])
                    speaker_map[label] = info
                    log.info("speaker_identified", label=label, info=info)

            except Exception as e:
                log.warning("speaker_id_search_error", label=label, error=str(e))

        # Apply the mapping to all segments
        for seg in segments:
            label = seg.get("speaker_label", "")
            if label in speaker_map:
                info = speaker_map[label]
                if isinstance(info, dict):
                    seg["speaker_label"] = info.get("name", label)
                    seg["speaker_party"] = info.get("party")
                elif isinstance(info, str):
                    seg["speaker_label"] = info

        log.info("speakers_identified_all", mapping=speaker_map)
        return segments

    async def _detect_claims(
        self, session_id: str, segments: list[dict]
    ) -> list[Claim]:
        """Detect claims using LLM batch evaluation for better accuracy."""
        # Merge adjacent same-speaker segments for better context
        merged = self._merge_adjacent_segments(segments)

        # Build numbered transcript for LLM evaluation
        numbered_lines = []
        for i, seg in enumerate(merged):
            numbered_lines.append(f"[{i}] {seg.get('speaker_label', 'Unknown')}: {seg['text']}")

        transcript_for_llm = "\n".join(numbered_lines)

        # Use Claude to identify checkable claims in batch
        prompt = f"""You are a claim detector for a political fact-checking tool. Analyze this transcript and identify ALL statements that contain checkable factual claims.

A checkable claim is a statement that:
- Asserts something specific happened or is true
- Can be verified with evidence (government data, news reports, court records, etc.)
- Names specific people, events, numbers, dates, or actions

Do NOT flag:
- Questions or requests for information
- Pure opinions without factual basis ("this is terrible")
- Procedural speech ("thank you", "I yield my time")
- Vague statements without specific checkable assertions
- Sentence fragments that don't make a complete claim

For each checkable claim, extract the COMPLETE claim text (combine fragments if needed to form a complete assertion).

Respond ONLY with a JSON array. Each element should have:
- "line_index": the [N] number of the transcript line containing the claim
- "claim_text": the complete checkable claim (rewrite fragments into a complete sentence if needed)
- "claim_type": "checkable_fact" | "opinion" | "forecast" | "value_judgment"

Example: [{{"line_index": 3, "claim_text": "The unemployment rate dropped to 3.5 percent last month", "claim_type": "checkable_fact"}}]

Transcript:
{transcript_for_llm[:4000]}"""

        try:
            response = await self.anthropic_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )

            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            text = text.strip()

            detected = json.loads(text)
            log.info("llm_claims_detected", count=len(detected))

        except Exception as e:
            log.warning("llm_claim_detection_error", error=str(e))
            # Fall back to heuristic detection
            return await self._detect_claims_heuristic(session_id, segments)

        # Build Claim objects from LLM results
        claims = []
        for item in detected:
            line_idx = item.get("line_index", 0)
            if line_idx < 0 or line_idx >= len(merged):
                continue

            seg = merged[line_idx]
            claim_text = item.get("claim_text", seg["text"]).strip()
            claim_type = item.get("claim_type", "checkable_fact")

            if len(claim_text) < 10:
                continue

            # Extract structured claim
            struct = await self.detector.extract_claim_struct(
                claim_text, seg.get("speaker_label")
            )

            # Compute a worthiness score for the record
            score = await self.detector.score_claim_worthiness(claim_text)

            claim = Claim(
                session_id=session_id,
                claim_text=claim_text,
                normalized_claim=struct.get("normalized_claim"),
                time_scope=struct.get("time_scope"),
                location_scope=struct.get("location_scope"),
                speaker_label=seg.get("speaker_label"),
                start_ms=seg["start_ms"],
                end_ms=seg["end_ms"],
                claim_type=claim_type,
                claim_worthiness_score=max(score, 0.5),  # LLM-selected claims get min 0.5
                required_evidence_types=struct.get("required_evidence_types"),
            )
            self.db.add(claim)
            claims.append(claim)

        await self.db.commit()
        log.info("claims_detected", count=len(claims))
        return claims

    async def _detect_claims_heuristic(
        self, session_id: str, segments: list[dict]
    ) -> list[Claim]:
        """Fallback heuristic claim detection."""
        claims = []
        for seg in segments:
            sentences = self._split_sentences(seg["text"])
            for sentence in sentences:
                if len(sentence.strip()) < 10:
                    continue

                score = await self.detector.score_claim_worthiness(sentence)
                if score < settings.claim_worthiness_threshold:
                    continue

                struct = await self.detector.extract_claim_struct(
                    sentence, seg.get("speaker_label")
                )

                claim = Claim(
                    session_id=session_id,
                    claim_text=sentence.strip(),
                    normalized_claim=struct.get("normalized_claim"),
                    time_scope=struct.get("time_scope"),
                    location_scope=struct.get("location_scope"),
                    speaker_label=seg.get("speaker_label"),
                    start_ms=seg["start_ms"],
                    end_ms=seg["end_ms"],
                    claim_type=struct.get("claim_type", "checkable_fact"),
                    claim_worthiness_score=score,
                    required_evidence_types=struct.get("required_evidence_types"),
                )
                self.db.add(claim)
                claims.append(claim)

        await self.db.commit()
        log.info("claims_detected_heuristic", count=len(claims))
        return claims

    @staticmethod
    def _merge_adjacent_segments(segments: list[dict]) -> list[dict]:
        """Merge adjacent segments from the same speaker into longer utterances."""
        if not segments:
            return []

        merged = [dict(segments[0])]  # copy first segment
        for seg in segments[1:]:
            prev = merged[-1]
            # Merge if same speaker and gap < 2 seconds
            if (
                seg.get("speaker_label") == prev.get("speaker_label")
                and seg["start_ms"] - prev["end_ms"] < 2000
            ):
                prev["text"] = prev["text"].rstrip() + " " + seg["text"].lstrip()
                prev["end_ms"] = seg["end_ms"]
            else:
                merged.append(dict(seg))

        return merged

    async def _store_evidence(self, claim: Claim, evidence: list[dict]) -> None:
        for e in evidence:
            # Get or create source
            source = await self._get_or_create_source(e)

            passage = EvidencePassage(
                claim_id=claim.id,
                source_id=source.id,
                snippet=e.get("snippet", "")[:2000],
                relevance_to_claim="provides_context",
                relevance_score=e.get("score"),
                retrieval_method=e.get("retrieval_method"),
            )
            self.db.add(passage)
        await self.db.commit()

    async def _get_or_create_source(self, evidence: dict) -> Source:
        url = evidence.get("url", "")
        result = await self.db.execute(select(Source).where(Source.url == url))
        source = result.scalar_one_or_none()

        if not source:
            source = Source(
                url=url,
                title=evidence.get("title", "Unknown"),
                publisher=evidence.get("publisher", "Unknown"),
                source_tier=evidence.get("source_tier", "tier_5_other"),
                content_text=evidence.get("snippet"),
            )
            self.db.add(source)
            await self.db.flush()

        return source

    async def _store_verdict(
        self, claim: Claim, verdict: dict, evidence: list[dict]
    ) -> None:
        claim.verdict_label = verdict.get("verdict_label", "UNVERIFIED")
        claim.verdict_confidence = verdict.get("confidence")
        claim.verdict_rationale_summary = verdict.get("rationale_summary")
        claim.verdict_rationale_bullets = verdict.get("rationale_bullets")
        claim.verdict_version = 1
        claim.verdict_model_used = verdict.get("model_used")
        claim.verdict_generated_at = datetime.now(timezone.utc)
        claim.what_would_change_verdict = verdict.get("what_would_change_verdict")

        # If confidence not set by model, use heuristic
        if claim.verdict_confidence is None and claim.verdict_label != "UNVERIFIED":
            source_tiers = [e.get("source_tier", "tier_5_other") for e in evidence]
            claim.verdict_confidence = self.verdict_engine.compute_heuristic_confidence(
                claim.claim_worthiness_score, len(evidence), source_tiers
            )

        # Audit log
        audit = VerdictAuditLog(
            claim_id=claim.id,
            version=1,
            verdict_label=claim.verdict_label,
            confidence=claim.verdict_confidence,
            rationale_summary=claim.verdict_rationale_summary,
            rationale_bullets=claim.verdict_rationale_bullets,
            model_used=claim.verdict_model_used,
            prompt_hash=verdict.get("prompt_hash"),
            evidence_ids=[e.get("source_id") for e in evidence if e.get("source_id")],
        )
        self.db.add(audit)
        await self.db.commit()

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Sentence splitting that handles abbreviations and common patterns."""
        import re
        # Protect common abbreviations from splitting
        protected = text
        abbreviations = [
            "Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Sen.", "Rep.", "Gov.",
            "Gen.", "Sgt.", "Lt.", "Col.", "Maj.", "Capt.",
            "U.S.", "U.N.", "D.C.", "D.O.J.", "F.B.I.", "C.I.A.",
            "Jr.", "Sr.", "Inc.", "Corp.", "Ltd.", "vs.", "etc.",
            "Jan.", "Feb.", "Mar.", "Apr.", "Jun.", "Jul.", "Aug.",
            "Sep.", "Oct.", "Nov.", "Dec.", "No.", "St.",
        ]
        for abbr in abbreviations:
            protected = protected.replace(abbr, abbr.replace(".", "\x00"))

        sentences = re.split(r"(?<=[.!?])\s+", protected)
        # Restore dots
        sentences = [s.replace("\x00", ".").strip() for s in sentences]
        return [s for s in sentences if s.strip()]
