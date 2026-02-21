from dataclasses import dataclass
from typing import Protocol


@dataclass
class TranscribeOptions:
    language: str = "Russian"
    prompt: str | None = None


class Transcriber(Protocol):
    async def transcribe_ogg_file(
        self, file_path: str, options: TranscribeOptions | None = None
    ) -> str: ...

    async def transcribe_file(
        self, file_path: str, mime_type: str, options: TranscribeOptions | None = None
    ) -> str: ...
