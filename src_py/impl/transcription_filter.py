"""Combine independent audio evidence with Groq's segment metadata."""

import logging
import math

from src_py.impl.speech_activity import (
    MIN_SPEECH_SECONDS,
    SpeechActivity,
)

from src_py.impl.transcription_artifacts import strip_boilerplate

logger = logging.getLogger(__name__)


def _number(segment: dict, name: str) -> float:
    value = segment.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Groq segment is missing numeric {name}")
    if not math.isfinite(value):
        raise ValueError(f"Groq segment has invalid {name}")
    return float(value)


def filter_by_audio(payload: dict, activity: SpeechActivity) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        raise ValueError("Groq returned an invalid verbose transcription")
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise ValueError("Groq verbose transcription is missing segments")
    if not segments and payload["text"].strip():
        raise ValueError("Groq returned text without segment metadata")

    kept = []
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            raise ValueError("Groq returned an invalid transcription segment")
        start, end = _number(segment, "start"), _number(segment, "end")
        no_speech = _number(segment, "no_speech_prob")
        logprob = _number(segment, "avg_logprob")
        if start < 0 or end < start or not 0 <= no_speech <= 1:
            raise ValueError("Groq returned invalid segment timing or probability")
        text = segment["text"].strip()
        if not any(char.isalnum() for char in text):
            continue
        # Whisper can extend the last segment into its 30s padding. Clip its
        # end to the real audio; otherwise a hallucinated tail could inherit
        # evidence from unrelated speech earlier in the chunk.
        audio_start, audio_end = min(start, activity.duration), min(end, activity.duration)
        speech = activity.probability(audio_start, audio_end)
        speech_seconds = activity.speech_duration(audio_start, audio_end)
        # Groq may return no_speech_prob=0 for noise, with high decoder
        # confidence. Neither can replace independent sustained audio evidence.
        if speech_seconds < MIN_SPEECH_SECONDS:
            logger.info(
                "Suppressed non-speech segment %.2f-%.2fs: vad=%.3f "
                "speech_duration=%.3f no_speech=%.3f logprob=%.3f",
                start, end, speech, speech_seconds, no_speech, logprob,
            )
            continue
        kept.append(text)
    return " ".join(kept)


def filter_transcription(payload: dict, activity: SpeechActivity) -> str:
    return strip_boilerplate(filter_by_audio(payload, activity))
