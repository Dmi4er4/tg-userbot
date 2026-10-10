import copy
import unittest

from src_py.impl.speech_activity import SpeechActivity
from src_py.impl.transcription_filter import filter_transcription


def segment(text, start=0, end=1, no_speech=0.01, logprob=-0.2):
    return dict(text=text, start=start, end=end,
                no_speech_prob=no_speech, avg_logprob=logprob)


def payload(*segments):
    return {"text": " ".join(s["text"] for s in segments), "segments": list(segments)}


class MetadataFilterTest(unittest.TestCase):
    def test_ordinary_words_and_short_answers_survive(self):
        activity = SpeechActivity(1, (0.8,) * 32)
        for text in ("Спасибо!", "Музыка.", "Да.", "Нет.", "Стоп.", "Ага.", "Угу."):
            with self.subTest(text=text):
                self.assertEqual(filter_transcription(payload(segment(text)), activity), text)

    def test_boilerplate_is_suppressed_even_with_strong_audio_evidence(self):
        activity = SpeechActivity(1, (0.99,) * 32)
        for text in ("Спасибо за внимание!", "Субтитры сделал Дима.",
                     "Подписывайтесь на мой канал!", "Продолжение следует...",
                     "ПРОДОЛЖЕНИЕ\nСЛЕДУЕТ…", "[Продолжение следует...]",
                     "Thanks for watching!"):
            with self.subTest(text=text):
                self.assertEqual(filter_transcription(payload(segment(text)), activity), "")

    def test_boilerplate_removal_keeps_adjacent_speech(self):
        activity = SpeechActivity(1, (0.9,) * 32)
        for text in ("Спасибо за внимание. Да.", "Да. Продолжение следует...",
                     "Субтитры сделал Дима. Да."):
            with self.subTest(text=text):
                self.assertEqual(filter_transcription(payload(segment(text)), activity), "Да.")

    def test_boilerplate_split_between_segments_is_suppressed(self):
        activity = SpeechActivity(2, (0.9,) * 63)
        self.assertEqual(filter_transcription(payload(segment("Продолжение", 0, 1),
                         segment("следует...", 1, 2)), activity), "")

    def test_clock_tick_response_is_suppressed_despite_vad_false_positive(self):
        activity = SpeechActivity(5, (0.601182,) * 157)
        data = payload(segment("Продолжение следует...", 0, 4.96,
                               no_speech=0.0, logprob=-0.22316153))
        self.assertEqual(filter_transcription(data, activity), "")

    def test_strong_speech_survives_bad_decoder_confidence_and_repetition(self):
        data = payload(segment("Да, да, да, да!", no_speech=0.99, logprob=-2))
        data["segments"][0]["compression_ratio"] = 10
        self.assertEqual(filter_transcription(data, SpeechActivity(1, (0.8,) * 32)), "Да, да, да, да!")

    def test_weak_speech_survives_when_decoder_recognizes_it(self):
        self.assertEqual(filter_transcription(payload(segment("Нет.")),
                         SpeechActivity(1, (0.2,) * 32)), "Нет.")

    def test_both_metadata_signals_are_needed_to_reject_weak_speech(self):
        activity = SpeechActivity(1, (0.2,) * 32)
        for no_speech, logprob in ((0.99, -0.2), (0.01, -2)):
            with self.subTest(no_speech=no_speech, logprob=logprob):
                self.assertEqual(filter_transcription(payload(segment("Да.", no_speech=no_speech,
                                 logprob=logprob)), activity), "Да.")
        self.assertEqual(filter_transcription(payload(segment("Выдуманный текст", no_speech=0.99,
                         logprob=-2)), activity), "")

    def test_only_text_over_silence_is_removed_from_mixed_recording(self):
        activity = SpeechActivity(10, (0.8,) * 32 + (0.001,) * 281)
        data = payload(segment("Встречаемся завтра."), segment("Неизвестная галлюцинация.", 5, 7))
        self.assertEqual(filter_transcription(data, activity), "Встречаемся завтра.")

    def test_boundary_padding_keeps_short_word(self):
        activity = SpeechActivity(2, (0.0,) * 31 + (0.8,) + (0.0,) * 31)
        self.assertEqual(filter_transcription(payload(segment("Да.", 1.1, 1.2)), activity), "Да.")

    def test_out_of_range_timestamps_do_not_prove_silence(self):
        activity = SpeechActivity(1, (0.8,) * 32)
        self.assertEqual(filter_transcription(payload(segment("Нет.", 1.5, 2)), activity), "Нет.")

    def test_whisper_padding_does_not_borrow_earlier_speech_evidence(self):
        activity = SpeechActivity(45.8, (0.0,) * 625 + (0.9,) * 12 + (0.0,) * 795)
        data = payload(segment("Да.", 0, 20.22),
                       segment("Продолжение следует...", 30, 59.98),
                       segment("Еще выдуманный текст", 60, 89.98))
        self.assertEqual(filter_transcription(data, activity), "Да.")

    def test_invalid_metadata_is_an_error_instead_of_an_empty_transcript(self):
        base = payload(segment("Слова"))
        variants = [None, {}, {"text": "Слова", "segments": []}]
        for field in ("start", "end", "no_speech_prob", "avg_logprob"):
            for value in (None, "0", float("nan"), float("inf"), True):
                data = copy.deepcopy(base)
                data["segments"][0][field] = value
                variants.append(data)
        for data in variants:
            with self.subTest(data=data), self.assertRaises(ValueError):
                filter_transcription(data, SpeechActivity(1, (0.8,) * 32))

    def test_valid_empty_and_punctuation_responses_are_empty(self):
        activity = SpeechActivity(1, (0.8,) * 32)
        self.assertEqual(filter_transcription({"text": "", "segments": []}, activity), "")
        self.assertEqual(filter_transcription(payload(segment("... []")), activity), "")
