"""Pipeline orchestrator: processes a clip end-to-end.

Audio → ASR → Speaker ID → Claim Detection → Evidence Retrieval → Verdict Generation
"""

import asyncio
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
            if segments:
                session.duration_seconds = segments[-1]["end_ms"] // 1000
            await self._update_status(session, "processing", "asr", 20)

            # Stage 1.5: LLM re-diarization (fixes Deepgram merging speakers)
            await self._update_status(session, "processing", "diarization_fix", 21)
            segments = await self._llm_rediarize(segments)

            # Stage 1.6: Speaker Identification
            await self._update_status(session, "processing", "speaker_identification", 22)
            segments = await self._identify_speakers(
                segments, video_path=session.audio_file_path
            )
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

            # Stage 4: Generate AI summary
            await self._update_status(session, "processing", "summarization", 95)
            await self._generate_summary(session, segments)

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

    async def _generate_summary(self, session: Session, segments: list[dict]) -> None:
        """Generate an AI title and summary from the transcript."""
        if not segments:
            return

        transcript_lines = []
        for seg in segments:
            speaker = seg.get("speaker_label", "Speaker")
            text = seg.get("text", "")
            transcript_lines.append(f"{speaker}: {text}")

        transcript_text = "\n".join(transcript_lines)[:4000]

        prompt = f"""Analyze this transcript from a political broadcast and generate:
1. A concise, descriptive title (max 80 characters) - like a news headline
2. A 2-3 sentence summary covering the key topics, speakers, and claims discussed

Transcript:
{transcript_text}

Respond ONLY with a JSON object:
{{"title": "Your Title Here", "summary": "Your summary here."}}"""

        for attempt in range(3):
            try:
                response = await self.anthropic_client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=300,
                    messages=[{"role": "user", "content": prompt}],
                )

                result_text = response.content[0].text.strip()
                if result_text.startswith("```"):
                    result_text = result_text.split("\n", 1)[1]
                if result_text.endswith("```"):
                    result_text = result_text.rsplit("```", 1)[0]
                result_text = result_text.strip()

                json_start = result_text.find("{")
                json_end = result_text.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    result = json.loads(result_text[json_start:json_end])

                    generated_title = result.get("title", "")
                    generated_summary = result.get("summary", "")

                    if generated_title and (
                        not session.title or session.title == session.source_url
                    ):
                        session.title = generated_title

                    if generated_summary and not session.description:
                        session.description = generated_summary

                    log.info(
                        "ai_summary_generated",
                        session_id=session.id,
                        title=generated_title[:50],
                    )
                break
            except Exception as e:
                error_str = str(e)
                if "429" in error_str and attempt < 2:
                    import re as _re

                    wait_match = _re.search(r"try again in (\d+\.?\d*)s", error_str)
                    wait_secs = float(wait_match.group(1)) if wait_match else 5.0
                    log.info("summary_rate_limited", attempt=attempt, wait=wait_secs)
                    await asyncio.sleep(wait_secs + 1)
                else:
                    log.warning("ai_summary_failed", session_id=session.id, error=error_str)
                    break

    def _extract_speaker_clues(self, segments: list) -> dict[str, str]:
        """Scan transcript for title-and-name mentions that can identify speakers."""
        import re

        title_pattern = re.compile(
            r"\b(Senator|Representative|Congressman|Congresswoman|Secretary|"
            r"Attorney General|General|Governor|Mayor|President|Vice President|"
            r"Chairman|Chairwoman|Director|Ambassador|Justice|Judge|Dr\.|Professor)\s+"
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"
        )

        # Patterns that indicate the speaker is referring to THEMSELVES
        self_ref_pattern = re.compile(
            r"\b(I am|I'm|my name is|I serve as|I was|speaking as)\b",
            re.IGNORECASE,
        )

        # Patterns that indicate the speaker is ADDRESSING someone else
        address_pattern = re.compile(
            r"\b(thank you|I ask you|you said|do you|would you|can you|Mr\.|Ms\.|Mrs\.)\b",
            re.IGNORECASE,
        )

        # Collect mentions: for each segment, record
        # (speaker_label, mentioned_name, is_likely_addressing_other)
        mentions: list[tuple[str, str, bool]] = []

        for seg in segments:
            speaker = seg.get("speaker_label") or seg.get("speaker", "")
            text = seg.get("text", "")
            if not speaker or not text:
                continue

            matches = title_pattern.findall(text)
            for title, name in matches:
                full_name = f"{title} {name}"
                # Check context around the mention
                has_self_ref = bool(self_ref_pattern.search(text))
                has_address = bool(address_pattern.search(text))

                if has_self_ref and not has_address:
                    # Speaker is likely referring to themselves
                    mentions.append((speaker, full_name, False))
                elif has_address and not has_self_ref:
                    # Speaker is likely addressing someone else
                    mentions.append((speaker, full_name, True))
                else:
                    # Ambiguous — don't use as a definitive clue
                    mentions.append((speaker, full_name, True))

        identified: dict[str, str] = {}
        for speaker, name, is_addressing_other in mentions:
            if not is_addressing_other:
                # Self-reference: the speaker IS this person
                if speaker not in identified:
                    identified[speaker] = name
            # Don't try to assign names to other speakers via heuristic —
            # let the LLM handle that with the clue as context

        return identified

    def _collect_all_name_mentions(self, segments: list) -> list[str]:
        """Collect all name mentions from the transcript for LLM context."""
        import re

        # Title before name: "Senator Smith", "Director Patel"
        title_before = re.compile(
            r"\b(Senator|Representative|Congressman|Congresswoman|Secretary|"
            r"Attorney General|General|Governor|Mayor|President|Vice President|"
            r"Chairman|Chairwoman|Director|Ambassador|Justice|Judge|Dr\.|Professor)\s+"
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"
        )

        # Name followed by title/role: "Harry Enten, Chief Data Analyst"
        name_then_title = re.compile(
            r"\b([A-Z][a-z]+\s+[A-Z][a-z]+),?\s+"
            r"(?:Chief|Senior|Lead|Deputy|Assistant|Associate|Former|Acting)?\s*"
            r"(?:Data |Political |National |White House |Legal )?"
            r"(?:Analyst|Correspondent|Reporter|Anchor|Host|Commentator|Editor|"
            r"Strategist|Advisor|Adviser|Director|Secretary|Producer|Journalist)\b"
        )

        names = set()
        for seg in segments:
            text = seg.get("text", "")
            for title, name in title_before.findall(text):
                names.add(f"{title} {name}")
            for match in name_then_title.finditer(text):
                names.add(match.group(0).rstrip(","))
        return sorted(names)

    @staticmethod
    def _extract_onscreen_text(video_path: str) -> list[str]:
        """Extract on-screen text from video frames using ffmpeg + Tesseract OCR.

        Captures frames at regular intervals and runs OCR to find
        lower-third graphics, chyrons, and name cards.
        """
        import os
        import shutil
        import subprocess
        import tempfile

        if not video_path:
            return []

        video_exts = {".mp4", ".webm", ".mov", ".mkv"}
        ext = os.path.splitext(video_path)[1].lower()
        if ext not in video_exts:
            return []

        texts = []
        tmpdir = tempfile.mkdtemp(prefix="pf_ocr_")

        try:
            # Sample several early timestamps to catch lower thirds and chyrons.
            timestamps = ["0", "5", "15", "30", "60", "120"]
            for i, ts in enumerate(timestamps):
                frame_path = os.path.join(tmpdir, f"frame_{i}.png")
                try:
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-ss",
                            ts,
                            "-i",
                            video_path,
                            "-frames:v",
                            "1",
                            "-vf",
                            "crop=iw:ih/3:0:2*ih/3",
                            "-y",
                            frame_path,
                        ],
                        capture_output=True,
                        timeout=10,
                    )
                    if not os.path.exists(frame_path):
                        continue

                    result = subprocess.run(
                        ["tesseract", frame_path, "-", "--psm", "6"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        text = result.stdout.strip()
                        for line in text.split("\n"):
                            line = line.strip()
                            if len(line) > 5 and sum(
                                c.isalpha() or c.isspace() for c in line
                            ) > len(line) * 0.6:
                                texts.append(line)
                except Exception:
                    continue
        except Exception as e:
            log.warning("ocr_extraction_failed", error=str(e))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        seen = set()
        unique = []
        for text in texts:
            normalized = text.lower().strip()
            if normalized not in seen:
                seen.add(normalized)
                unique.append(text)

        return unique

    async def _identify_faces_from_video(self, video_path: str) -> list[str]:
        """Extract frames from video, read on-screen text, and use Brave Search
        to identify speakers via reverse lookup.

        Returns a list of identified person descriptions like:
        ["Trey Yingst, Fox News Chief Foreign Correspondent"]
        """
        import base64
        import os
        import shutil
        import subprocess
        import tempfile

        import httpx

        if not video_path:
            return []

        video_exts = {".mp4", ".webm", ".mov", ".mkv"}
        ext = os.path.splitext(video_path)[1].lower()
        if ext not in video_exts:
            return []

        tmpdir = tempfile.mkdtemp(prefix="pf_face_")
        identified_people: list[str] = []

        try:
            # Extract frames at different timestamps to catch different speakers
            timestamps = ["3", "10", "30", "60", "90", "120"]
            frame_paths = []

            for i, ts in enumerate(timestamps):
                frame_path = os.path.join(tmpdir, f"frame_{i}.jpg")
                try:
                    subprocess.run(
                        [
                            "ffmpeg", "-ss", ts, "-i", video_path,
                            "-frames:v", "1", "-q:v", "2", "-y", frame_path,
                        ],
                        capture_output=True,
                        timeout=10,
                    )
                    if os.path.exists(frame_path) and os.path.getsize(frame_path) > 1000:
                        frame_paths.append(frame_path)
                except Exception:
                    continue

            if not frame_paths:
                return []

            # Step 1: Send frames to Claude to read ALL on-screen text
            frames_to_send = frame_paths[:4]
            content: list[dict] = []
            for frame_path in frames_to_send:
                with open(frame_path, "rb") as frame_file:
                    image_data = base64.b64encode(frame_file.read()).decode("utf-8")
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_data,
                    },
                })

            content.append({
                "type": "text",
                "text": (
                    "Read ALL text visible on screen in these video frames. "
                    "Focus especially on:\n"
                    "1. Lower-third name graphics (e.g. 'TREY YINGST | FOX NEWS')\n"
                    "2. Chyrons and tickers\n"
                    "3. Network logos (FOX NEWS, CNN, MSNBC, etc)\n"
                    "4. Any names, titles, or show names\n\n"
                    "Also describe each distinct person visible (appearance, position).\n\n"
                    "Respond with JSON:\n"
                    '{"on_screen_text": ["TREY YINGST", "FOX NEWS ALERT", ...], '
                    '"people": [{"description": "blonde woman at anchor desk", '
                    '"visible_name_graphic": "KAYLEIGH MCENANY"}, ...]}'
                ),
            })

            response = await self.anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=800,
                messages=[{"role": "user", "content": content}],
            )

            result_text = response.content[0].text.strip()
            if result_text.startswith("```"):
                result_text = result_text.split("\n", 1)[1]
            if result_text.endswith("```"):
                result_text = result_text.rsplit("```", 1)[0]
            result_text = result_text.strip()

            json_start = result_text.find("{")
            json_end = result_text.rfind("}") + 1
            vision_data = {}
            if json_start >= 0 and json_end > json_start:
                vision_data = json.loads(result_text[json_start:json_end])

            log.info("vision_screen_read", data=str(vision_data)[:500])

            # Collect names from vision — both on_screen_text and people with visible names
            screen_names = []
            for person in vision_data.get("people", []):
                name = person.get("visible_name_graphic", "")
                if name and len(name) > 2:
                    screen_names.append(name)

            # Step 2: For any partial names or descriptions, search Brave for full identity
            all_text = vision_data.get("on_screen_text", [])
            # Filter for likely name strings (capitalized, 2+ words)
            import re as _re
            name_candidates = []
            for t in all_text + screen_names:
                # Skip network names, generic labels
                if any(skip in t.upper() for skip in [
                    "BREAKING", "ALERT", "LIVE", "EXCLUSIVE", "NEWS",
                    "CHANNEL", "PREDICTION", "TRACKER",
                ]):
                    continue
                # Looks like a name: 2+ capitalized words
                if _re.match(r"^[A-Z][a-z]+ [A-Z][a-z]+", t) or _re.match(r"^[A-Z]{2,} [A-Z]{2,}", t):
                    name_candidates.append(t)

            # Also add names from people descriptions
            for person in vision_data.get("people", []):
                name = person.get("visible_name_graphic", "")
                if name and name not in name_candidates:
                    name_candidates.append(name)

            if not name_candidates and not screen_names:
                return []

            # Step 3: Search Brave for each name candidate to get full identity
            if settings.brave_search_api_key:
                async with httpx.AsyncClient(timeout=10) as client:
                    for name in name_candidates[:4]:
                        try:
                            resp = await client.get(
                                "https://api.search.brave.com/res/v1/web/search",
                                params={"q": f'"{name}" journalist OR correspondent OR anchor OR politician OR senator'},
                                headers={"X-Subscription-Token": settings.brave_search_api_key},
                            )
                            if resp.status_code == 200:
                                results = resp.json().get("web", {}).get("results", [])
                                if results:
                                    # Use the first result's title/description to get full identity
                                    title = results[0].get("title", "")
                                    desc = results[0].get("description", "")
                                    identified_people.append(f"{name} (from search: {title[:100]})")
                                    log.info("brave_speaker_lookup", name=name, result=title[:100])
                        except Exception as e:
                            log.warning("brave_speaker_lookup_failed", name=name, error=str(e))
                            continue

            # If we got screen names directly, use those too
            for name in screen_names:
                if not any(name.lower() in p.lower() for p in identified_people):
                    identified_people.append(name)

            log.info("face_id_results", people=identified_people)

        except Exception as e:
            log.warning("face_id_failed", error=str(e))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        return identified_people

    @staticmethod
    def _split_qa_segments(segments: list[dict]) -> list[dict]:
        """Split segments that contain both Q&A dialogue from different speakers.

        In hearings, Deepgram sometimes lumps a question and its answer into one segment.
        Detect this by finding sentences that end with '?' followed by a statement
        that sounds like an answer.
        """
        import re

        result = []
        for seg in segments:
            text = seg.get("text", "").strip()
            if not text:
                result.append(seg)
                continue

            # Look for question mark followed by what looks like an answer
            # Pattern: "...question? Answer statement..."
            qa_split = re.split(r"(\?\s+)", text)

            if len(qa_split) < 3:
                # No Q&A pattern found
                result.append(seg)
                continue

            # Reconstruct: question part includes everything up to and including the ?
            # Answer part is everything after
            question_parts = []
            answer_start_idx = None

            for i, part in enumerate(qa_split):
                if part.strip() == "?":
                    # This is a question mark separator
                    question_parts.append(part)
                    # Check if what follows looks like an answer (not another question)
                    remaining = "".join(qa_split[i + 1 :]).strip()
                    if remaining and not remaining.endswith("?"):
                        answer_start_idx = i + 1
                        break
                else:
                    question_parts.append(part)

            if answer_start_idx is None:
                result.append(seg)
                continue

            question_text = "".join(question_parts).strip()
            answer_text = "".join(qa_split[answer_start_idx:]).strip()

            if not question_text or not answer_text:
                result.append(seg)
                continue

            # Estimate split point in time based on text length ratio
            total_len = len(text)
            q_ratio = len(question_text) / total_len
            duration = seg["end_ms"] - seg["start_ms"]
            split_ms = seg["start_ms"] + int(duration * q_ratio)

            # Create two segments
            q_seg = dict(seg)
            q_seg["text"] = question_text
            q_seg["end_ms"] = split_ms

            a_seg = dict(seg)
            a_seg["text"] = answer_text
            a_seg["start_ms"] = split_ms
            original_label = seg.get("speaker_label", "Speaker")
            other_speakers = [
                s.get("speaker_label", "")
                for s in segments
                if s.get("speaker_label", "") != original_label
            ]
            if other_speakers:
                from collections import Counter

                most_common_other = Counter(other_speakers).most_common(1)[0][0]
                a_seg["speaker_label"] = most_common_other
            else:
                a_seg["speaker_label"] = (
                    f"Speaker {original_label.split()[-1]}B"
                    if " " in original_label
                    else "Respondent"
                )

            result.append(q_seg)
            result.append(a_seg)

        return result

    async def _llm_rediarize(self, segments: list[dict]) -> list[dict]:
        """Use LLM to fix speaker diarization when Deepgram merges multiple speakers.

        Deepgram sometimes assigns most segments to one speaker in broadcast audio.
        This method sends the transcript to the LLM to re-assign speaker labels
        based on conversational context.
        """
        if not segments or len(segments) < 3:
            return segments

        from collections import Counter

        speaker_counts = Counter(seg.get("speaker_label", "") for seg in segments)
        total = sum(speaker_counts.values())
        max_speaker, max_count = speaker_counts.most_common(1)[0]

        if max_count / total < 0.7:
            return segments

        log.info(
            "diarization_suspicious",
            dominant_speaker=max_speaker,
            ratio=max_count / total,
        )

        transcript_lines = []
        for i, seg in enumerate(segments):
            text_preview = seg.get("text", "")[:150]
            start_s = seg["start_ms"] / 1000
            transcript_lines.append(
                f"[{i}] ({start_s:.1f}s) {seg.get('speaker_label', '?')}: {text_preview}"
            )

        transcript_block = "\n".join(transcript_lines[:50])

        prompt = f"""This is a transcript from a political broadcast (likely a congressional hearing or interview). The automatic speaker diarization was poor - it assigned most segments to one speaker, but there are clearly multiple speakers taking turns.

Your job: re-assign speaker labels to each segment. In a hearing, there's typically:
- A QUESTIONER (senator/representative) who asks questions
- A WITNESS (official/appointee) who answers

Key signals:
- Questions end with "?" - the person asking is the questioner
- Short responses like "Yes sir", "That's correct", "Absolutely" - these are the witness answering
- Defensive statements like "The premise is false", "I can tell you that..." - this is the witness
- Accusations, rhetorical questions, citing statistics - this is the questioner
- "Thank you, Senator/Chairman" - this is the witness addressing the questioner

Here is the transcript with segment indices:
{transcript_block}

Re-assign each segment to either "A" (questioner) or "B" (witness/answerer).

CRITICAL: When a single segment contains BOTH a question AND an answer (e.g., "Have you done X? Yes, we have done X because..."), split it:
- Assign the question portion to A and the answer portion to B
- In your response, indicate the split point

Respond with a JSON array where each element is either:
- {{"idx": 0, "speaker": "A"}} for a whole segment
- {{"idx": 0, "speaker": "A", "split_at": "Yes, we have", "second_speaker": "B"}} for segments that need splitting

Return ONLY the JSON array, no other text."""

        for attempt in range(3):
            try:
                response = await self.anthropic_client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=2000,
                    messages=[{"role": "user", "content": prompt}],
                )

                result_text = response.content[0].text.strip()
                if result_text.startswith("```"):
                    result_text = result_text.split("\n", 1)[1]
                if result_text.endswith("```"):
                    result_text = result_text.rsplit("```", 1)[0]
                result_text = result_text.strip()

                json_start = result_text.find("[")
                json_end = result_text.rfind("]") + 1
                if json_start < 0 or json_end <= json_start:
                    log.warning("rediarize_parse_failed", text=result_text[:200])
                    return segments

                assignments = json.loads(result_text[json_start:json_end])
                if not isinstance(assignments, list):
                    log.warning("rediarize_parse_failed", text=result_text[:200])
                    return segments

                new_segments = []
                assignment_map = {}
                for assignment in assignments:
                    if isinstance(assignment, dict) and "idx" in assignment:
                        assignment_map[assignment["idx"]] = assignment

                for i, seg in enumerate(segments):
                    if i >= 50:
                        new_segments.append(seg)
                        continue

                    assignment = assignment_map.get(i)
                    if not assignment:
                        new_segments.append(seg)
                        continue

                    speaker_label = (
                        "Speaker_Q" if assignment.get("speaker") == "A" else "Speaker_W"
                    )

                    if "split_at" in assignment and assignment.get("second_speaker"):
                        split_text = assignment["split_at"]
                        full_text = seg.get("text", "")
                        split_idx = full_text.find(split_text)

                        if split_idx > 0:
                            part1_text = full_text[:split_idx].strip()
                            part2_text = full_text[split_idx:].strip()
                            split_end_ms = seg["start_ms"]

                            if part1_text:
                                seg1 = dict(seg)
                                seg1["speaker_label"] = speaker_label
                                seg1["text"] = part1_text
                                duration = seg["end_ms"] - seg["start_ms"]
                                ratio = len(part1_text) / max(len(full_text), 1)
                                split_end_ms = seg["start_ms"] + int(duration * ratio)
                                seg1["end_ms"] = split_end_ms
                                new_segments.append(seg1)

                            if part2_text:
                                seg2 = dict(seg)
                                second_label = (
                                    "Speaker_Q"
                                    if assignment["second_speaker"] == "A"
                                    else "Speaker_W"
                                )
                                seg2["speaker_label"] = second_label
                                seg2["text"] = part2_text
                                seg2["start_ms"] = split_end_ms if part1_text else seg["start_ms"]
                                new_segments.append(seg2)
                        else:
                            seg_copy = dict(seg)
                            seg_copy["speaker_label"] = speaker_label
                            new_segments.append(seg_copy)
                    else:
                        seg_copy = dict(seg)
                        seg_copy["speaker_label"] = speaker_label
                        new_segments.append(seg_copy)

                log.info("rediarization_complete", original=len(segments), new=len(new_segments))
                return new_segments

            except Exception as e:
                error_str = str(e)
                if "429" in error_str and attempt < 2:
                    import re as _re

                    wait_match = _re.search(r"try again in (\d+\.?\d*)s", error_str)
                    wait_secs = float(wait_match.group(1)) if wait_match else 5.0
                    log.info("rediarize_rate_limited", attempt=attempt, wait=wait_secs)
                    await asyncio.sleep(wait_secs + 1)
                else:
                    log.warning("rediarize_failed", error=error_str)
                    return segments

        return segments

    async def _identify_speakers(
        self, segments: list[dict], video_path: str | None = None
    ) -> list[dict]:
        """Identify speakers from transcript context and public-figure knowledge."""
        if not segments:
            return segments

        merged_segments = self._merge_adjacent_segments(segments)
        unique_speakers = set(seg.get("speaker_label", "") for seg in merged_segments)
        clues = self._extract_speaker_clues(merged_segments)
        all_names_mentioned = self._collect_all_name_mentions(merged_segments)
        onscreen_texts = []
        if video_path:
            onscreen_texts = self._extract_onscreen_text(video_path)
            if onscreen_texts:
                log.info("ocr_texts_found", count=len(onscreen_texts), texts=onscreen_texts[:5])

        face_ids: list[str] = []
        if video_path:
            face_ids = await self._identify_faces_from_video(video_path)

        # For each unique speaker, collect their most distinctive quotes
        speaker_quotes: dict[str, list[str]] = {}
        for speaker_label in unique_speakers:
            speaker_segs = [s for s in merged_segments if s.get("speaker_label") == speaker_label]
            # Sort by length descending so the model sees the most informative utterances.
            speaker_segs.sort(key=lambda s: len(s["text"]), reverse=True)
            quotes = []
            for seg in speaker_segs[:3]:
                text = seg["text"].strip()
                if len(text) > 30:
                    quotes.append(text[:200])
            if quotes:
                speaker_quotes[speaker_label] = quotes

        speaker_map: dict[str, dict] = {}
        # Clues from self-references are high confidence — use directly
        for label, clue_name in clues.items():
            speaker_map[label] = {"name": clue_name, "party": None}
        for label, clue_name in clues.items():
            log.info("speaker_identified_from_clue", label=label, clue=clue_name)

        if not speaker_quotes and not speaker_map:
            return segments

        # Also build context: what does each speaker say and who do they address?
        context_lines = []
        for seg in merged_segments[:30]:
            context_lines.append(f'{seg.get("speaker_label", "?")}: {seg["text"][:100]}')
        context_block = "\n".join(context_lines)

        # Identify ALL unidentified speakers in a single LLM call
        unidentified = {label: quotes for label, quotes in speaker_quotes.items() if label not in speaker_map}

        if unidentified:
            # Build a per-speaker section showing their quotes
            speaker_sections = []
            for label, quotes in unidentified.items():
                quote_block = "\n".join(f'    - "{q}"' for q in quotes)
                clue_note = ""
                if label in clues:
                    clue_note = f"\n    Note: This speaker was addressed as '{clues[label]}' by another speaker."
                speaker_sections.append(f"  {label}:\n{quote_block}{clue_note}")

            all_speakers_block = "\n\n".join(speaker_sections)

            names_text = ""
            if all_names_mentioned:
                names_text = (
                    f"\nNames/titles mentioned in the transcript: {', '.join(all_names_mentioned)}"
                )

            ocr_text = ""
            if onscreen_texts:
                ocr_text = (
                    "\n\nIMPORTANT — On-screen text extracted from the video "
                    "(chyrons, lower-third graphics, name cards):\n"
                    + "\n".join(f'  - "{t}"' for t in onscreen_texts[:10])
                    + "\nThese on-screen graphics are HIGH CONFIDENCE identifiers. "
                    "If a name appears on screen, USE IT."
                )

            face_id_text = ""
            if face_ids:
                face_id_text = (
                    "\n\nPeople VISUALLY IDENTIFIED from video frames (face recognition):\n"
                    + "\n".join(f"  - {person}" for person in face_ids)
                    + "\nThese are HIGH CONFIDENCE visual identifications. Match speakers to these people."
                )

            from datetime import date

            today = date.today().isoformat()

            prompt = f"""Identify ALL speakers in this political broadcast transcript. Today's date is {today} — use CURRENT officeholders only.

Here is the transcript (each line prefixed with the speaker label):
{context_block[:3000]}

Here are distinctive quotes from each speaker:

{all_speakers_block}
{names_text}{ocr_text}{face_id_text}

CRITICAL INSTRUCTIONS for identification:
- The speaker who ASKS QUESTIONS is typically a senator, representative, or committee member
- The speaker who ANSWERS questions and DEFENDS positions/actions) is typically the witness, official, or appointee being questioned
- If on-screen text says "X TESTIFIES AT Y HEARING", then X is the person ANSWERING questions, not asking them
- Do NOT swap the questioner and the witness — pay attention to who asks vs who answers
- If someone says "I ask you..." or "Do you..." — THEY are the questioner, not the person being addressed
- If someone says "Yes sir", "That's correct", "The premise is false" — THEY are the witness answering

Respond with a JSON object mapping each speaker label to their identity:
{{
  "Speaker 0": {{"name": "Full Name with Title", "party": "D or R or null"}},
  "Speaker 1": {{"name": "Full Name with Title", "party": "D or R or null"}}
}}

Include ALL speaker labels from the transcript. Use null for party if unknown or not applicable."""

            import time as _time

            for attempt in range(3):
                try:
                    response = await self.anthropic_client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=1024,
                        messages=[{"role": "user", "content": prompt}],
                    )

                    result_text = response.content[0].text.strip()
                    if result_text.startswith("```"):
                        result_text = result_text.split("\n", 1)[1]
                    if result_text.endswith("```"):
                        result_text = result_text.rsplit("```", 1)[0]
                    result_text = result_text.strip()

                    json_start = result_text.find("{")
                    json_end = result_text.rfind("}") + 1
                    if json_start >= 0 and json_end > json_start:
                        all_ids = json.loads(result_text[json_start:json_end])
                        for label, info in all_ids.items():
                            if label not in speaker_map and isinstance(info, dict):
                                name = info.get("name", "")
                                # Reject generic/unknown labels — let fallbacks handle them
                                if "unknown" in name.lower() or "unidentified" in name.lower():
                                    log.info("speaker_id_rejected_generic", label=label, name=name)
                                    continue
                                speaker_map[label] = info
                                log.info("speaker_identified", label=label, info=info)
                    break

                except Exception as e:
                    error_str = str(e)
                    if "429" in error_str and attempt < 2:
                        # Rate limited — wait and retry
                        import re as _re

                        wait_match = _re.search(r"try again in (\d+\.?\d*)s", error_str)
                        wait_secs = float(wait_match.group(1)) if wait_match else 5.0
                        log.info("speaker_id_rate_limited", attempt=attempt, wait=wait_secs)
                        await asyncio.sleep(wait_secs + 1)
                    else:
                        log.warning("speaker_id_error", error=error_str)
                        break

        # Fallback: use OCR text to identify speakers when LLM failed
        if onscreen_texts:
            import re as _re

            # Look for patterns like "DIRECTOR PATEL TESTIFIES" or "SEN. BOOKER"
            ocr_combined = " ".join(onscreen_texts).upper()

            # Extract names from OCR: look for "TITLE NAME" patterns
            ocr_name_pattern = _re.compile(
                r"(?:DIRECTOR|SENATOR|SEN\.|REP\.|REPRESENTATIVE|SECRETARY|"
                r"ATTORNEY GENERAL|GOVERNOR|CHAIRMAN|CHAIRWOMAN|JUDGE|JUSTICE)\s+"
                r"([A-Z][A-Z]+(?:\s+[A-Z][A-Z]+)?)",
                _re.IGNORECASE,
            )
            ocr_names = []
            for match in ocr_name_pattern.finditer(ocr_combined):
                full_match = match.group(0).strip()
                ocr_names.append(full_match)

            # Also look for "X TESTIFIES" pattern — the person testifying is the witness
            testifies_pattern = _re.compile(
                r"(?:DIRECTOR|SECRETARY|ATTORNEY GENERAL|CHAIRMAN|CHAIRWOMAN)\s+"
                r"([A-Z][A-Z]+)\s+TESTIF",
                _re.IGNORECASE,
            )
            witness_name = None
            for match in testifies_pattern.finditer(ocr_combined):
                witness_name = match.group(0).split("TESTIF")[0].strip()
                break

            if witness_name or ocr_names:
                log.info("ocr_fallback_names", witness=witness_name, names=ocr_names)

            # If we have a witness and unidentified speakers, assign the witness
            # to the speaker who ANSWERS questions (shorter segments, responds to questions)
            if witness_name:
                for label in list(unique_speakers):
                    if label in speaker_map:
                        continue
                    # Check if this speaker is the witness (answers questions, defends positions)
                    speaker_segs = [
                        s for s in merged_segments if s.get("speaker_label") == label
                    ]
                    answers_questions = any(
                        seg["text"].strip().startswith(
                            (
                                "The premise",
                                "Yes",
                                "No,",
                                "That's",
                                "Absolutely",
                                "I ",
                                "We ",
                            )
                        )
                        for seg in speaker_segs
                    )
                    asks_questions = any("?" in seg["text"] for seg in speaker_segs)
                    question_ratio = sum(
                        1 for seg in speaker_segs if "?" in seg["text"]
                    ) / max(len(speaker_segs), 1)

                    # The witness answers more than they ask
                    if question_ratio < 0.3 and answers_questions:
                        speaker_map[label] = {"name": witness_name.title(), "party": None}
                        log.info(
                            "speaker_assigned_from_ocr_witness",
                            label=label,
                            name=witness_name,
                            asks_questions=asks_questions,
                        )
                        break

            # For remaining unidentified speakers, if OCR found senator names, assign them
            # to the speaker who asks the most questions
            senator_names = [
                n for n in ocr_names if any(t in n.upper() for t in ["SENATOR", "SEN."])
            ]
            if senator_names:
                for label in list(unique_speakers):
                    if label in speaker_map:
                        continue
                    speaker_segs = [
                        s for s in merged_segments if s.get("speaker_label") == label
                    ]
                    question_ratio = sum(
                        1 for seg in speaker_segs if "?" in seg["text"]
                    ) / max(len(speaker_segs), 1)
                    if question_ratio > 0.3:
                        speaker_map[label] = {"name": senator_names[0].title(), "party": None}
                        log.info(
                            "speaker_assigned_from_ocr_senator",
                            label=label,
                            name=senator_names[0],
                        )
                        break

        # Fallback: detect introduction-then-handoff patterns
        # E.g., Speaker 0: "...correspondent Trey live in Israel. Good morning, Trey."
        #        Speaker 1: "Yeah, good morning..." → Speaker 1 IS Trey
        import re as _re
        for idx, seg in enumerate(merged_segments[:-1]):
            text = seg.get("text", "")
            speaker = seg.get("speaker_label", "")
            next_seg = merged_segments[idx + 1]
            next_speaker = next_seg.get("speaker_label", "")

            if next_speaker in speaker_map or next_speaker == speaker:
                continue

            # Pattern: "Good morning/evening, [Name]" at end of segment
            greeting_match = _re.search(
                r"(?:good morning|good evening|good afternoon|welcome),?\s+([A-Z][a-z]+)",
                text, _re.IGNORECASE
            )
            if greeting_match:
                greeted_name = greeting_match.group(1)
                # The next speaker who responds is the greeted person
                next_text = next_seg.get("text", "").lower()
                if any(r in next_text[:50] for r in ["yeah", "hey", "good morning", "good evening", "thank", "thanks"]):
                    # Try to find full name from face_ids or all_names_mentioned
                    full_name = greeted_name
                    for fid in face_ids:
                        if greeted_name.lower() in fid.lower():
                            full_name = fid
                            break
                    for nm in all_names_mentioned:
                        if greeted_name.lower() in nm.lower():
                            full_name = nm
                            break
                    speaker_map[next_speaker] = {"name": full_name, "party": None}
                    log.info("speaker_assigned_from_greeting", label=next_speaker, name=full_name)

        # Also try matching names mentioned in transcript to speakers
        remaining_unidentified = [l for l in unique_speakers if l not in speaker_map]
        if remaining_unidentified and all_names_mentioned:
            import re as _re

            # Build a lookup of name → full title from all_names_mentioned
            name_lookup = {}
            for nm in all_names_mentioned:
                # Extract just the last name for matching
                parts = nm.split()
                if len(parts) >= 2:
                    last_name = parts[-1].lower()
                    name_lookup[last_name] = nm

            for label in remaining_unidentified:
                speaker_segs = [s for s in merged_segments if s.get("speaker_label") == label]
                for seg in speaker_segs[:5]:  # Check first few segments
                    text = seg["text"]
                    # Check if any known name appears at the start of this segment
                    # (anchors/hosts often introduce themselves or are introduced)
                    for last_name, full_name in name_lookup.items():
                        if last_name in text.lower()[:100]:
                            speaker_map[label] = {"name": full_name, "party": None}
                            log.info("speaker_assigned_from_transcript_name",
                                     label=label, name=full_name)
                            break
                    if label in speaker_map:
                        break

            # Second pass: if only one speaker remains unidentified and one name is unused,
            # assign by elimination
            still_unidentified = [l for l in unique_speakers if l not in speaker_map]
            used_names = {
                (info.get("name", "") if isinstance(info, dict) else info).lower()
                for info in speaker_map.values()
            }
            unused_names = [
                nm for nm in all_names_mentioned
                if nm.lower() not in used_names
                and not any(nm.lower() in u for u in used_names)
            ]
            if len(still_unidentified) == 1 and len(unused_names) == 1:
                speaker_map[still_unidentified[0]] = {"name": unused_names[0], "party": None}
                log.info("speaker_assigned_by_elimination",
                         label=still_unidentified[0], name=unused_names[0])

        # Brave Search resolution: for speakers with only a first name or still unidentified,
        # search for their full identity using transcript context
        if settings.brave_search_api_key:
            import httpx

            # Collect first names and context from transcript introductions
            intro_pattern = _re.compile(
                r"(?:correspondent|reporter|anchor|host|analyst|commentator|senator|"
                r"representative|secretary|director|governor|attorney general)\s+"
                r"([A-Z][a-z]+)",
                _re.IGNORECASE,
            )
            # Also match "Name, Title" pattern
            name_title_pattern = _re.compile(
                r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?),?\s+"
                r"(?:chief|senior|lead|deputy)?\s*"
                r"(?:foreign |national |political |data |legal )?"
                r"(?:correspondent|reporter|anchor|analyst|commentator|editor)",
                _re.IGNORECASE,
            )

            transcript_text = " ".join(s.get("text", "") for s in merged_segments[:10])
            partial_names: dict[str, str] = {}  # name -> context for search

            for match in intro_pattern.finditer(transcript_text):
                name = match.group(1)
                # Get surrounding context for the search
                start = max(0, match.start() - 30)
                end = min(len(transcript_text), match.end() + 30)
                context = transcript_text[start:end].strip()
                partial_names[name] = context

            for match in name_title_pattern.finditer(transcript_text):
                name = match.group(1)
                context = match.group(0)
                partial_names[name] = context

            # For greeting-assigned speakers with only a first name, resolve via search
            speakers_to_resolve = {}
            for label, info in speaker_map.items():
                name = info.get("name", "") if isinstance(info, dict) else info
                # Single word name = just a first name, needs resolution
                if name and " " not in name and name in partial_names:
                    speakers_to_resolve[label] = (name, partial_names[name])

            # Also try to resolve completely unidentified speakers
            final_unidentified = [l for l in unique_speakers if l not in speaker_map]
            for label in final_unidentified:
                # Check if any partial name from the transcript could be this speaker
                for first_name, context in partial_names.items():
                    if first_name not in [
                        info.get("name", "") if isinstance(info, dict) else info
                        for info in speaker_map.values()
                    ]:
                        speakers_to_resolve[label] = (first_name, context)
                        break

            if speakers_to_resolve:
                try:
                    async with httpx.AsyncClient(timeout=10) as http_client:
                        for label, (first_name, context) in speakers_to_resolve.items():
                            query = f'"{first_name}" {context}'
                            try:
                                resp = await http_client.get(
                                    "https://api.search.brave.com/res/v1/web/search",
                                    params={"q": query, "count": 3},
                                    headers={"X-Subscription-Token": settings.brave_search_api_key},
                                )
                                if resp.status_code == 200:
                                    results = resp.json().get("web", {}).get("results", [])
                                    for r in results:
                                        title = r.get("title", "")
                                        desc = r.get("description", "")
                                        combined = f"{title} {desc}"
                                        # Look for "FirstName LastName" pattern in results
                                        name_match = _re.search(
                                            rf"\b{first_name}\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",
                                            combined,
                                        )
                                        if name_match:
                                            full_name = f"{first_name} {name_match.group(1)}"
                                            speaker_map[label] = {"name": full_name, "party": None}
                                            log.info("speaker_resolved_via_brave",
                                                     label=label, query=query[:80], result=full_name)
                                            break
                            except Exception as e:
                                log.warning("brave_speaker_resolve_failed", error=str(e))
                except Exception as e:
                    log.warning("brave_resolve_session_failed", error=str(e))

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

        for seg in segments:
            label = seg.get("speaker_label", "")
            if "_response" in label:
                seg["speaker_label"] = "Respondent"

        # Give remaining "Speaker N" labels a descriptive role estimate
        for seg in segments:
            label = seg.get("speaker_label", "")
            if not _re.match(r"^Speaker \d+$", label):
                continue
            # Analyze this speaker's segments to guess their role
            speaker_segs = [s for s in segments if s.get("speaker_label") == label]
            all_text = " ".join(s.get("text", "") for s in speaker_segs).lower()
            question_count = sum(1 for s in speaker_segs if "?" in s.get("text", ""))
            total = max(len(speaker_segs), 1)
            question_ratio = question_count / total

            if question_ratio > 0.4:
                role = "Unidentified Interviewer"
            elif any(w in all_text for w in ["we reported", "sources say", "breaking", "back to you"]):
                role = "Unidentified Correspondent"
            elif any(w in all_text for w in ["the president", "the administration", "white house"]):
                role = "Unidentified Political Commentator"
            elif any(w in all_text for w in ["data shows", "numbers", "polling", "percent"]):
                role = "Unidentified Analyst"
            elif any(w in all_text for w in ["i serve", "my district", "legislation", "the bill"]):
                role = "Unidentified Legislator"
            else:
                role = "Unidentified Speaker"

            # Apply to all segments with this label
            for s in segments:
                if s.get("speaker_label") == label:
                    s["speaker_label"] = role
            log.info("speaker_role_estimated", original=label, role=role)

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

        chunk_size = 3500
        overlap_line_count = 3
        transcript_chunks = []
        current_chunk_lines = []
        current_chunk_start = 0
        current_chunk_length = 0

        for i, line in enumerate(numbered_lines):
            next_length = current_chunk_length + len(line) + (1 if current_chunk_lines else 0)
            if current_chunk_lines and next_length > chunk_size:
                transcript_chunks.append(
                    {"start_offset": current_chunk_start, "lines": current_chunk_lines}
                )
                current_chunk_lines = [line]
                current_chunk_start = i
                current_chunk_length = len(line)
                continue

            if not current_chunk_lines:
                current_chunk_start = i
                current_chunk_length = len(line)
            else:
                current_chunk_length = next_length
            current_chunk_lines.append(line)

        if current_chunk_lines:
            transcript_chunks.append(
                {"start_offset": current_chunk_start, "lines": current_chunk_lines}
            )

        # Use Claude to identify checkable claims in batch
        detected = []
        successful_chunks = 0
        for chunk_idx, chunk in enumerate(transcript_chunks):
            chunk_lines = []
            for local_idx, line in enumerate(chunk["lines"]):
                _, _, line_text = line.partition("] ")
                chunk_lines.append(f"[{local_idx}] {line_text or line}")

            chunk_text_parts = []
            if chunk_idx > 0:
                previous_lines = transcript_chunks[chunk_idx - 1]["lines"][-overlap_line_count:]
                if previous_lines:
                    chunk_text_parts.append(
                        "OVERLAP CONTEXT FROM PREVIOUS CHUNK. DO NOT RETURN CLAIMS FROM THESE LINES:"
                    )
                    for overlap_line in previous_lines:
                        _, _, overlap_text = overlap_line.partition("] ")
                        chunk_text_parts.append(f"(overlap) {overlap_text or overlap_line}")
                    chunk_text_parts.append("CURRENT CHUNK:")

            chunk_text_parts.append("\n".join(chunk_lines))
            chunk_text = "\n".join(chunk_text_parts)

            prompt = f"""You are a claim detector for a political fact-checking tool. Analyze this transcript and identify only the most relevant statements that contain checkable factual claims.

A checkable claim is a statement that:
- Asserts something specific happened or is true
- Can be verified with evidence (government data, news reports, court records, etc.)
- Names specific people, events, numbers, dates, or actions

IMPORTANT FILTERING RULES:
- Only flag claims that a voter, journalist, or fact-checker would consider important, misleading, or worth verifying.
- DO NOT flag: routine self-introductions ('I serve on the Armed Services Committee'), uncontested procedural facts, greetings, opinions clearly stated as opinions ('I believe we should...'), or trivial biographical details.
- DO flag: statistics and numbers, policy impact claims, accusations against people or organizations, promises about future actions, claims about disputed events, comparisons or rankings, claims that could mislead voters.
- When in doubt, skip the claim rather than including it.

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
{chunk_text}"""

            try:
                response = await self.anthropic_client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4000,
                    messages=[{"role": "user", "content": prompt}],
                )

                text = response.content[0].text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text.rsplit("```", 1)[0]
                text = text.strip()

                chunk_detected = json.loads(text)
                successful_chunks += 1
                if chunk["start_offset"]:
                    for item in chunk_detected:
                        item["line_index"] = item.get("line_index", 0) + chunk["start_offset"]

                detected.extend(chunk_detected)
                log.info(
                    "llm_claims_detected_chunk",
                    chunk_index=chunk_idx,
                    count=len(chunk_detected),
                )

            except Exception as e:
                log.warning(
                    "llm_claim_detection_error",
                    chunk_index=chunk_idx,
                    error=str(e),
                )
                continue

        if successful_chunks == 0:
            # Fall back to heuristic detection if every chunk failed
            return await self._detect_claims_heuristic(session_id, segments)

        log.info("llm_claims_detected", count=len(detected), chunks=successful_chunks)

        def claim_text_jaccard(left: str, right: str) -> float:
            left_words = set(left.lower().split())
            right_words = set(right.lower().split())
            union = left_words | right_words
            if not union:
                return 0.0
            return len(left_words & right_words) / len(union)

        deduplicated = []
        removed_duplicates = 0
        for item in detected:
            claim_text = item.get("claim_text", "").strip()
            if not claim_text:
                deduplicated.append(item)
                continue

            matched_idx = None
            for idx, kept_item in enumerate(deduplicated):
                kept_claim_text = kept_item.get("claim_text", "").strip()
                if (
                    kept_claim_text
                    and claim_text_jaccard(claim_text, kept_claim_text) > 0.8
                ):
                    matched_idx = idx
                    break

            if matched_idx is None:
                deduplicated.append(item)
                continue

            removed_duplicates += 1
            kept_item = deduplicated[matched_idx]
            kept_claim_text = kept_item.get("claim_text", "").strip()
            if len(claim_text) > len(kept_claim_text):
                deduplicated[matched_idx] = item

        detected = deduplicated
        log.info("llm_claims_deduplicated", removed=removed_duplicates, kept=len(detected))

        filtered_detected = []
        for item in detected:
            score = await self.detector.score_claim_worthiness(item.get("claim_text", ""))
            if score >= 0.4:
                filtered_detected.append(item)
            else:
                log.info(
                    "claim_filtered_low_worthiness",
                    claim=item.get("claim_text", "")[:80],
                    score=score,
                )

        detected = filtered_detected

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

            context_lines = []
            if line_idx > 0:
                context_lines.append(merged[line_idx - 1]["text"])
            if line_idx + 1 < len(merged):
                context_lines.append(merged[line_idx + 1]["text"])
            context_str = " ".join(context_lines)

            # Extract structured claim
            struct = await self.detector.extract_claim_struct(
                claim_text,
                seg.get("speaker_label"),
                context=context_str,
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

                # LLM relevance filter — reject trivial/procedural statements
                if not await self.detector.is_relevant_claim(sentence, seg["text"]):
                    log.info("claim_rejected_by_llm", sentence=sentence[:80])
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
