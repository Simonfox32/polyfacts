"""ASR pipeline: transcribe audio using Deepgram Nova-2 with speaker diarization."""

import structlog
from deepgram import AsyncDeepgramClient

from app.config import settings

log = structlog.get_logger()


class ASRPipeline:
    def __init__(self):
        self.client = AsyncDeepgramClient(api_key=settings.deepgram_api_key)

    async def transcribe_file(self, audio_file_path: str) -> list[dict]:
        """Transcribe an audio file and return timestamped segments with speaker labels.

        Returns:
            List of dicts: [{speaker_label, text, start_ms, end_ms}]
        """
        log.info("asr_transcribe_start", file=audio_file_path)

        with open(audio_file_path, "rb") as audio:
            audio_bytes = audio.read()

        response = await self.client.listen.v1.media.transcribe_file(
            request=audio_bytes,
            model="nova-2",
            language="en",
            smart_format=True,
            diarize=True,
            utterances=True,
            punctuate=True,
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

        log.info("asr_transcribe_done", segments=len(segments))
        return segments
