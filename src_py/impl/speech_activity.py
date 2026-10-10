"""Silero speech evidence, independent of the transcription model."""

import math
import threading
from array import array
from dataclasses import dataclass

from pydub import AudioSegment

SAMPLE_RATE = 16_000
WINDOW_SAMPLES = 512
FRAME_SECONDS = WINDOW_SAMPLES / SAMPLE_RATE
# A deliberately permissive gate: a single possible speech frame keeps a chunk.
# No minimum utterance length, so short answers are not discarded.
POSSIBLE_SPEECH = 0.15
CONFIDENT_SPEECH = 0.35
SPEECH_PAD_SECONDS = 0.3


@dataclass(frozen=True)
class SpeechActivity:
    duration: float
    probabilities: tuple[float, ...]

    def probability(self, start: float = 0, end: float | None = None) -> float:
        end = self.duration if end is None else end
        left = max(0, math.floor((start - SPEECH_PAD_SECONDS) / FRAME_SECONDS))
        right = min(
            len(self.probabilities),
            math.ceil((end + SPEECH_PAD_SECONDS) / FRAME_SECONDS),
        )
        return max(self.probabilities[left:right], default=0.0)

    @property
    def has_possible_speech(self) -> bool:
        return self.probability() >= POSSIBLE_SPEECH


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
