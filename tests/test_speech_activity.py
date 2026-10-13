import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from pydub import AudioSegment

from src_py.impl.groq_whisper_transcriber import GroqWhisperTranscriber
from src_py.impl.speech_activity import SileroSpeechDetector, SpeechActivity

FIXTURES = Path(__file__).parents[1] / "benchmarks" / "vad_audio"


class SpeechEvidenceTest(unittest.TestCase):
    def test_minimum_speech_duration_and_threshold(self):
        self.assertTrue(SpeechActivity(1, (0.5,) * 4).has_possible_speech)
        self.assertFalse(SpeechActivity(1, (0.99,) * 3).has_possible_speech)
        self.assertFalse(SpeechActivity(1, (0.49,) * 32).has_possible_speech)

    def test_separate_noise_spikes_are_not_accumulated(self):
        self.assertFalse(SpeechActivity(1, (0.9, 0.0) * 16).has_possible_speech)

    def test_last_frame_padding_does_not_extend_short_audio(self):
        activity = SpeechActivity(0.1, (0.99,) * 4)
        self.assertAlmostEqual(activity.speech_duration(), 0.1)
        self.assertFalse(activity.has_possible_speech)


class SileroAudioTest(unittest.TestCase):
    def test_all_speech_fixtures_reach_recognition_including_quiet_and_short(self):
        detector = SileroSpeechDetector()
        for case in json.loads((FIXTURES / "manifest.json").read_text()):
            if not case["expected"]:
                continue
            with self.subTest(file=case["file"]):
                audio = AudioSegment.from_file(FIXTURES / case["file"])
                self.assertGreater(audio.max, 0, "speech fixture must contain actual audio")
                self.assertTrue(detector.analyze(audio).has_possible_speech)

    def test_digital_silence_and_generated_environmental_noise_are_rejected(self):
        detector = SileroSpeechDetector()
        for filename in ("silence_short.ogg", "quiet_noise.ogg", "white_noise.ogg",
                         "wind.ogg", "hum.ogg", "clicks.ogg", "esc10_clock_tick.ogg"):
            with self.subTest(filename=filename):
                activity = detector.analyze(AudioSegment.from_file(FIXTURES / filename))
                self.assertFalse(activity.has_possible_speech)

    def test_model_state_does_not_leak_between_recordings_or_workers(self):
        detector = SileroSpeechDetector()
        speech = AudioSegment.from_file(FIXTURES / "yes_quiet.ogg")
        noise = AudioSegment.from_file(FIXTURES / "white_noise.ogg")
        expected = detector.analyze(speech)
        detector.analyze(noise)
        self.assertEqual(detector.analyze(speech), expected)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(detector.analyze, (speech, noise, speech, noise)))
        self.assertEqual(results[0], expected)
        self.assertEqual(results[2], expected)
        self.assertFalse(results[1].has_possible_speech)
        self.assertFalse(results[3].has_possible_speech)

    def test_non_speech_is_not_encoded_or_sent(self):
        transcriber = GroqWhisperTranscriber("unused")
        for filename in ("quiet_noise.ogg", "esc10_clock_tick.ogg"):
            with self.subTest(filename=filename), patch.object(AudioSegment, "export") as export:
                chunks = transcriber._prepare_audio_chunks(str(FIXTURES / filename), "audio/ogg")
                self.assertEqual(chunks, [])
                export.assert_not_called()

    def test_vad_failure_is_not_silence(self):
        transcriber = GroqWhisperTranscriber("unused")
        transcriber._speech_detector.analyze = Mock(side_effect=RuntimeError("model unavailable"))
        with self.assertRaisesRegex(RuntimeError, "model unavailable"):
            transcriber._prepare_audio_chunks(str(FIXTURES / "yes.ogg"), "audio/ogg")

    def test_preprocessing_keeps_original_audio_level(self):
        transcriber = GroqWhisperTranscriber("unused")
        audio = AudioSegment.from_file(FIXTURES / "thanks_quiet.ogg")
        exported = []

        def capture_export(chunk, buffer, **_kwargs):
            exported.append(chunk.raw_data)
            buffer.write(b"encoded")

        with patch.object(AudioSegment, "export", new=capture_export):
            chunks = transcriber._prepare_audio_chunks(str(FIXTURES / "thanks_quiet.ogg"), "audio/ogg")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(exported, [audio.raw_data])
