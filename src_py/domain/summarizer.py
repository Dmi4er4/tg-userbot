from typing import Protocol


class Summarizer(Protocol):
    async def summarize(self, text: str) -> str | None:
        """Return a short TL;DR for the text, or None if it could not be built."""
        ...
