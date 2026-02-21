import asyncio
import io
import logging

import speech_recognition as sr
from pydub import AudioSegment

from src_py.domain.transcriber import TranscribeOptions

logger = logging.getLogger(__name__)

LANGUAGE_MAP = {
    "Russian": "ru-RU",
    "English": "en-US",
}


class SpeechRecognitionTranscriber:
    def __init__(self) -> None:
        self._recognizer = sr.Recognizer()

    async def transcribe_ogg_file(
        self, file_path: str, options: TranscribeOptions | None = None
    ) -> str:
        return await self.transcribe_file(file_path, "audio/ogg", options)

    async def transcribe_file(
        self, file_path: str, mime_type: str, options: TranscribeOptions | None = None
    ) -> str:
        opts = options or TranscribeOptions()
        lang = LANGUAGE_MAP.get(opts.language, "ru-RU")
        return await asyncio.to_thread(self._transcribe_sync, file_path, mime_type, lang)

    def _transcribe_sync(self, file_path: str, mime_type: str, lang: str) -> str:
        wav_data = self._convert_to_wav(file_path, mime_type)
        audio_file = sr.AudioFile(wav_data)
        with audio_file as source:
            audio = self._recognizer.record(source)
        try:
            return self._recognizer.recognize_google(audio, language=lang)
        except sr.UnknownValueError:
            return "(не удалось распознать речь)"
        except sr.RequestError as e:
            raise RuntimeError(f"Speech recognition service error: {e}") from e

    def _convert_to_wav(self, file_path: str, mime_type: str) -> io.BytesIO:
        fmt = self._mime_to_format(mime_type)
        segment = AudioSegment.from_file(file_path, format=fmt)
        buf = io.BytesIO()
        segment.export(buf, format="wav")
        buf.seek(0)
        return buf

    @staticmethod
    def _mime_to_format(mime_type: str) -> str:
        mapping = {
            "audio/ogg": "ogg",
            "audio/mpeg": "mp3",
            "audio/mp4": "mp4",
            "audio/wav": "wav",
            "video/mp4": "mp4",
        }
        return mapping.get(mime_type, mime_type.split("/")[-1])
