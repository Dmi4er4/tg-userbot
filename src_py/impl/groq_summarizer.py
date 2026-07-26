import logging

import aiohttp

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = (
    "Ты сжимаешь расшифровки голосовых сообщений. "
    "Отвечай на русском. Выдай от 1 до 4 пунктов, каждый с новой строки, "
    "каждый начинается с «• ». Только суть: факты, просьбы, договорённости, "
    "вопросы, требующие ответа. Без вступлений, без выводов, без воды. "
    "Не пересказывай дословно и не добавляй ничего, чего нет в тексте."
)

REQUEST_TIMEOUT_S = 30
MAX_INPUT_CHARS = 40_000


class GroqSummarizer:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def summarize(self, text: str) -> str | None:
        payload = {
            "model": MODEL,
            "temperature": 0.2,
            "max_tokens": 400,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text[:MAX_INPUT_CHARS]},
            ],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    GROQ_CHAT_URL, headers=headers, json=payload
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error("Groq chat API error %s: %s", resp.status, body)
                        return None
                    data = await resp.json()
        except Exception:
            logger.exception("Groq summarization request failed")
            return None

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            logger.error("Unexpected Groq chat response shape: %s", data)
            return None

        cleaned = (content or "").strip()
        return cleaned or None
