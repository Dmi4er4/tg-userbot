"""Suppress known subtitle/outro phrase families, even when actually spoken.

This is an extra safeguard for VAD false positives. The audio-based filter is
responsible for unknown non-speech output; ordinary short replies and isolated
words such as "музыка" are not blacklisted here.
"""

import re

# Known Whisper hallucination patterns (appears on silence / short audio)
# Sources:
#   https://gist.github.com/waveletdeboshir/8bf52f04bf78018194f25b2390c08309
#   https://github.com/openai/whisper/discussions/2131
#   https://huggingface.co/datasets/sachaarbonel/whisper-hallucinations
_BOILERPLATE_PATTERNS: list[re.Pattern[str]] = [
    # Subtitle credits
    re.compile(
        r"\bСубтитры\s+(?:сделал|делал|создал|создавал|подготовил|подогнал|добавил)"
        r"\s+[^\s.!?…]+[.!?…]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:Редактор\s+субтитров|Корректор)\s+"
        r"(?:[А-ЯЁ]\s*\.\s*){1,2}[А-ЯЁа-яё-]+[.!?…]*",
        re.IGNORECASE,
    ),
    re.compile(r"\bСпасибо\s+за\s+субтитры\b[.!?…]*", re.IGNORECASE),
    # Subscribe / like / watch
    re.compile(
        r"\b(?:Подпиши(?:сь|тесь)|Подписывай(?:тесь|ся))"
        r"(?:\s+на\s+(?:(?:мой|наш|этот)\s+)?канал)?\b"
        r"(?=\s*(?:$|[.!?…,\])»”]))[.!?…]*",
        re.IGNORECASE,
    ),
    re.compile(r"\bСтавь(?:те)?\s+лайк(?:и)?\b[.!?…]*", re.IGNORECASE),
    # Thanks for watching
    re.compile(
        r"\b(?:Благодарю|Спасибо)\s+за\s+(?:просмотр|внимание|прослушивание)\b[.!?…]*",
        re.IGNORECASE,
    ),
    re.compile(r"\bThanks?\s+for\s+watching\b[.!?…]*", re.IGNORECASE),
    re.compile(r"\bThank\s+you\s+for\s+watching\b[.!?…]*", re.IGNORECASE),
    # Continuation
    re.compile(r"\bПродолжение\s+следует\b[.!?…]*", re.IGNORECASE),
    re.compile(
        r"\bСмотрите\s+продолжение(?:\s+во?\s+(?:следующей|второй|\d+)"
        r"\s+(?:части(?:\s+видео)?|серии))?\b[.!?…]*",
        re.IGNORECASE,
    ),
    # English subtitle credit artifacts
    re.compile(
        r"\bsubtitles\s+(?:(?:created|provided)\s+)?by\s+"
        r"(?:the\s+)?(?:amara\.?org(?:\s+community)?|[^\s.!?…]+)[.!?…]*",
        re.IGNORECASE,
    ),
    re.compile(r"\bamara\.?org\b", re.IGNORECASE),
]


def strip_boilerplate(text: str) -> str:
    result = text
    removed = False
    for pattern in _BOILERPLATE_PATTERNS:
        result, count = pattern.subn("", result)
        removed |= count > 0
    if not removed:
        return result.strip()
    # Removing multiple stock phrases may leave only their conjunctions or
    # wrappers. Do not turn those leftovers into a new bot reply.
    if not any(char.isalnum() for char in re.sub(r"\b(?:и|and)\b", "", result, flags=re.IGNORECASE)):
        return ""
    result = re.sub(r"\(\s*\)|\[\s*\]|«\s*»", "", result)
    result = re.sub(r"\s+", " ", result)
    return result.lstrip(" .,!?…;:—–-«»()[]\"' ").rstrip()
