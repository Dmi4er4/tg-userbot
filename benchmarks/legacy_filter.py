"""Frozen text filter from before the Silero VAD change, for comparison only."""
import re

# Known Whisper hallucination patterns (appears on silence / short audio)
# Sources:
#   https://gist.github.com/waveletdeboshir/8bf52f04bf78018194f25b2390c08309
#   https://github.com/openai/whisper/discussions/2131
#   https://huggingface.co/datasets/sachaarbonel/whisper-hallucinations
_HALLUCINATION_PATTERNS: list[re.Pattern[str]] = [
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

# These labels indicate an empty transcript only when no other words remain.
# Do not delete words such as "музыка" or "смех" from actual speech.
_NON_SPEECH_PATTERN = re.compile(
    r"\b(?:"
    r"(?:(?:вес[её]лая|спокойная|грустная|лирическая|динамичная|таинственная|"
    r"торжественная|интригующая|напряж[её]нная|печальная|тревожная|фоновая|тихая)\s+)?"
    r"(?:музыка|мелодия)|музыкальная\s+заставка|"
    r"аплодисменты|смех|выстрелы?|взрыв|перестрелка|кашель|"
    r"(?:городской\s+)?шум(?:\s+(?:дождя|воды|ветра|двигателя|мотора))?|"
    r"лай\s+собак[аи]?|п[её]с\s+лает|плеск\s+воды|р[её]в\s+мотора|"
    r"(?:гудок|сигнал)\s+(?:поезда|автомобиля|машины)|полицейская\s+сирена|"
    r"(?:стук|звонок)\s+в\s+дверь|"
    r"тишина|пауза|без\s+звука|нет\s+(?:звука|речи)|неразборчиво|"
    r"music|silence|applause|laughter|inaudible|no\s+(?:audio|speech)|blank_audio"
    r")\b",
    re.IGNORECASE,
)


def _strip_hallucinations(text: str) -> str:
    result = text
    for pat in _HALLUCINATION_PATTERNS:
        result = pat.sub("", result)
    remainder = _NON_SPEECH_PATTERN.sub("", result)
    if not any(char.isalnum() for char in remainder):
        # Punctuation, brackets, underscores and music symbols are not speech.
        return ""
    return result.strip()
