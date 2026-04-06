"""ASR pipeline: transcribe audio using Deepgram Nova-2 with speaker diarization."""

import os
import subprocess
import tempfile

import structlog
from deepgram import AsyncDeepgramClient

from app.config import settings

log = structlog.get_logger()


class ASRPipeline:
    def __init__(self):
        self.client = AsyncDeepgramClient(api_key=settings.deepgram_api_key)

    @staticmethod
    def _fix_diarization_splits(segments: list[dict]) -> list[dict]:
        """Fix false speaker switches that happen mid-sentence.

        Deepgram sometimes splits one speaker's utterance across two different
        speaker labels. Detect this by looking for segments that end without
        sentence-ending punctuation and merge them with the next segment.
        """
        if len(segments) < 2:
            return segments

        fixed = [dict(segments[0])]
        for seg in segments[1:]:
            prev = fixed[-1]
            prev_text = prev["text"].rstrip()

            # Check if previous segment ends mid-sentence (no terminal punctuation)
            ends_mid_sentence = (
                prev_text
                and not prev_text[-1] in ".?!;\""
                and prev_text[-1] != "\u2019"
            )

            # Also check: if the current segment starts with a lowercase word,
            # it's very likely a continuation
            curr_text = seg["text"].lstrip()
            starts_continuation = curr_text and curr_text[0].islower()

            # Check time gap - if there's a big gap, it's probably a real switch
            time_gap_ms = seg["start_ms"] - prev["end_ms"]
            small_gap = time_gap_ms < 1500  # less than 1.5 seconds

            # Merge if: ends mid-sentence AND (starts with lowercase OR small gap)
            # AND different speakers (same-speaker merging is handled elsewhere)
            if ends_mid_sentence and small_gap and (starts_continuation or ends_mid_sentence):
                # Keep the previous speaker label (they were talking first)
                prev["text"] = prev_text + " " + seg["text"].lstrip()
                prev["end_ms"] = seg["end_ms"]
            else:
                fixed.append(dict(seg))

        return fixed

    @staticmethod
    def _extract_audio_if_video(file_path: str) -> tuple[str, bool]:
        """If file is a video, extract audio to temp .wav file. Returns (audio_path, is_temp)."""
        video_exts = {".mp4", ".webm", ".mov", ".mkv"}
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in video_exts:
            return file_path, False

        temp_audio = tempfile.mktemp(suffix=".wav")
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    file_path,
                    "-vn",
                    "-acodec",
                    "pcm_s16le",
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-y",
                    temp_audio,
                ],
                capture_output=True,
                timeout=120,
            )
            if os.path.exists(temp_audio) and os.path.getsize(temp_audio) > 0:
                return temp_audio, True
        except Exception as e:
            log.warning("audio_extraction_failed", error=str(e))
            if os.path.exists(temp_audio):
                os.remove(temp_audio)

        return file_path, False

    async def transcribe_file(self, audio_file_path: str) -> list[dict]:
        """Transcribe an audio file and return timestamped segments with speaker labels.

        Returns:
            List of dicts: [{speaker_label, text, start_ms, end_ms}]
        """
        log.info("asr_transcribe_start", file=audio_file_path)

        audio_path, is_temp = self._extract_audio_if_video(audio_file_path)
        try:
            with open(audio_path, "rb") as audio:
                audio_bytes = audio.read()

            response = await self.client.listen.v1.media.transcribe_file(
                request=audio_bytes,
                model="nova-2",
                language="en",
                smart_format=True,
                diarize=True,
                utterances=True,
                punctuate=True,
                keywords=[
                    "CBO:2",
                    "GAO:2",
                    "OMB:2",
                    "DOJ:2",
                    "FBI:2",
                    "CIA:2",
                    "NSA:2",
                    "ICE:2",
                    "DHS:2",
                    "EPA:2",
                    "IRS:2",
                    "NATO:2",
                    "GOP:2",
                    "DNC:2",
                    "RNC:2",
                    "SCOTUS:1",
                    "POTUS:1",
                    "FLOTUS:1",
                    "Democrat:1",
                    "Republican:1",
                    "bipartisan:1",
                    "filibuster:1",
                    "impeachment:1",
                    "subpoena:1",
                    "gerrymandering:1",
                    "appropriations:1",
                ],
                paragraphs=True,
            )

            segments = []
            utterances = response.results.utterances

            if utterances:
                for utt in utterances:
                    segments.append({
                        "speaker_label": f"Speaker {utt.speaker}" if utt.speaker is not None else "Speaker ?",
                        "text": utt.transcript.strip() if utt.transcript else "",
                        "start_ms": int(utt.start * 1000) if utt.start else 0,
                        "end_ms": int(utt.end * 1000) if utt.end else 0,
                    })

            # Fix false speaker switches mid-sentence
            segments = self._fix_diarization_splits(segments)

            log.info("asr_transcribe_done", segments=len(segments))
            return segments
        finally:
            if is_temp and os.path.exists(audio_path):
                os.remove(audio_path)
