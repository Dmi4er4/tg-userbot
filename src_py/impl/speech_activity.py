"""Silero speech evidence, independent of the transcription model."""

import math
import threading
from array import array
from dataclasses import dataclass

from pydub import AudioSegment

SAMPLE_RATE = 16_000
WINDOW_SAMPLES = 512
FRAME_SECONDS = WINDOW_SAMPLES / SAMPLE_RATE
# A single frame can be a click or microphone noise. Require a sustained
# speech interval at Silero's default threshold. A 120ms minimum keeps short
# replies, including a quiet vowel ending at the recording boundary.
# https://github.com/snakers4/silero-vad/blob/master/src/silero_vad/utils_vad.py
CONFIDENT_SPEECH = 0.5
MIN_SPEECH_SECONDS = 0.12
SPEECH_PAD_SECONDS = 0.3


@dataclass(frozen=True)
class SpeechActivity:
    duration: float
    probabilities: tuple[float, ...]

    def _frame_bounds(self, start: float, end: float | None) -> tuple[int, int]:
        end = self.duration if end is None else end
        left = max(0, math.floor((start - SPEECH_PAD_SECONDS) / FRAME_SECONDS))
        right = min(
            len(self.probabilities),
            math.ceil(self.duration / FRAME_SECONDS),
            math.ceil((end + SPEECH_PAD_SECONDS) / FRAME_SECONDS),
        )
        return left, right

    def probability(self, start: float = 0, end: float | None = None) -> float:
        left, right = self._frame_bounds(start, end)
        return max(self.probabilities[left:right], default=0.0)

    def speech_duration(self, start: float = 0, end: float | None = None) -> float:
        """Longest uninterrupted confident interval near a transcript segment."""
        left, right = self._frame_bounds(start, end)
        longest = 0.0
        run_start = None
        for index in range(left, right):
            if self.probabilities[index] < CONFIDENT_SPEECH:
                run_start = None
                continue
            if run_start is None:
                run_start = index * FRAME_SECONDS
            frame_end = min((index + 1) * FRAME_SECONDS, self.duration)
            longest = max(longest, frame_end - run_start)
        return longest

    @property
    def has_possible_speech(self) -> bool:
        return self.speech_duration() >= MIN_SPEECH_SECONDS


class SileroSpeechDetector:
    def __init__(self) -> None:
        # The streaming model has mutable recurrent state. Each preparation
        # worker gets its own model and resets it for each unrelated chunk.
        self._workers = threading.local()

    def analyze(self, audio: AudioSegment) -> SpeechActivity:
        from silero_vad_lite import SileroVAD

        vad = getattr(self._workers, "model", None)
        if vad is None:
            vad = self._workers.model = SileroVAD(SAMPLE_RATE)
        vad.reset()
        pcm = audio.set_channels(1).set_frame_rate(SAMPLE_RATE).set_sample_width(2)
        samples = pcm.get_array_of_samples()
        peak = max(map(abs, samples), default=0)
        if peak == 0:
            return SpeechActivity(len(audio) / 1000, ())
        # Analyze quiet speech at a useful level, with a bounded gain. This copy
        # is only for VAD: Groq still receives the original, unamplified audio.
        gain = min(100.0, max(1.0, 16384 / peak))
        normalized = array("f", (value * gain / 32768 for value in samples))
        probabilities = []
        for offset in range(0, len(normalized), WINDOW_SAMPLES):
            frame = normalized[offset : offset + WINDOW_SAMPLES]
            frame.extend([0.0] * (WINDOW_SAMPLES - len(frame)))
            probability = float(vad.process(frame))
            if not math.isfinite(probability) or not 0 <= probability <= 1:
                raise ValueError("Silero returned an invalid speech probability")
            probabilities.append(probability)
        return SpeechActivity(len(audio) / 1000, tuple(probabilities))
