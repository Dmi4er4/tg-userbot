import asyncio
import logging
import re

from telethon import TelegramClient, events
from telethon.tl import types

from src_py import messages
from src_py.telegram_utils.utils import get_replied_message, send_formatted_reply

logger = logging.getLogger(__name__)

RESPONSE_WAIT_TIMEOUT = 90
RESPONSE_IDLE_TIMEOUT = 15
CONTEXT_MESSAGE_COUNT = 5

_STATUS_PREFIXES = ("Шлю запрос", "Не нравится ответ")

_ai_lock = asyncio.Lock()
_resolved_bot_entity: object | None = None
_resolved_bot_id: int | None = None


def _parse_ai_query(text: str | None) -> str:
    raw = (text or "").strip()
    return re.sub(r"^\.ai\s*", "", raw, flags=re.IGNORECASE).strip()


def _is_status_message(text: str | None) -> bool:
    if not text:
        return True
    for prefix in _STATUS_PREFIXES:
        if text.startswith(prefix):
            return True
    if "🐞" in text:
        return True
    return False


def _clean_response_text(text: str) -> str:
    lines = text.split("\n")
    cleaned = [
        line for line in lines
        if not line.strip().startswith("©") and not line.strip().startswith("ReqId:")
    ]
    return "\n".join(cleaned).rstrip()


async def command_ai(
    client: TelegramClient,
    message: types.Message,
    *,
    bot_username: str,
) -> None:
    async with _ai_lock:
        await _command_ai_impl(client, message, bot_username=bot_username)


async def _get_bot_entity(
    client: TelegramClient, bot_username: str
) -> tuple[object, int]:
    global _resolved_bot_entity, _resolved_bot_id
    if _resolved_bot_entity is not None and _resolved_bot_id is not None:
        return _resolved_bot_entity, _resolved_bot_id
    entity = await client.get_entity(bot_username)
    _resolved_bot_entity = await client.get_input_entity(entity)
    _resolved_bot_id = entity.id
    return _resolved_bot_entity, _resolved_bot_id


async def _command_ai_impl(
    client: TelegramClient,
    message: types.Message,
    *,
    bot_username: str,
) -> None:
    # Pre-resolve original chat entity BEFORE any other async work
    # This ensures the entity is cached and won't fail later
    original_chat_id = message.chat_id
    try:
        original_input_chat = await client.get_input_entity(original_chat_id)
    except ValueError:
        try:
            await client.get_dialogs()
            original_input_chat = await client.get_input_entity(original_chat_id)
        except Exception:
            logger.warning(
                "Could not resolve chat %s even after fetching dialogs",
                original_chat_id,
            )
            original_input_chat = original_chat_id

    original_reply_to = message.id

    try:
        bot_entity, bot_id = await _get_bot_entity(client, bot_username)
    except Exception:
        logger.exception("Cannot resolve Eliza bot @%s", bot_username)
        await send_formatted_reply(
            client, original_input_chat,
            "Ошибка: не удалось найти бота Eliza",
            reply_to_msg_id=original_reply_to,
        )
        return

    try:
        user_query = _parse_ai_query(message.message)
        replied = await get_replied_message(client, message)

        parts: list[str] = []
        if replied and replied.message:
            parts.append(replied.message.strip())
        if user_query:
            parts.append(user_query)

        if not parts:
            await send_formatted_reply(
                client, original_input_chat,
                "Использование: .ai <вопрос> (можно ответом на сообщение)",
                reply_to_msg_id=message.id,
            )
            return

        # Gather context from current chat
        context_text = await _build_context(client, message)

        full_query = "\n".join(parts)
        if context_text:
            full_query = (
                f"Контекст переписки:\n{context_text}\n\nВопрос:\n{full_query}"
            )

        # Track all message IDs sent/received during this session for cleanup
        session_msg_ids: list[int] = []

        # Step 1: Clear context in bot
        sent = await client.send_message(bot_entity, "/clear")
        session_msg_ids.append(sent.id)
        await asyncio.sleep(1)

        # Step 2: Select model via /presets
        sent = await client.send_message(bot_entity, "/presets")
        session_msg_ids.append(sent.id)
        preset_msg = await _wait_for_bot_message(client, bot_id, timeout=10)
        if preset_msg:
            session_msg_ids.append(preset_msg.id)

        # Step 3: Click Gemini button
        if preset_msg and preset_msg.buttons:
            clicked = False
            for row in preset_msg.buttons:
                for button in row:
                    if "gemini" in (button.text or "").lower():
                        await preset_msg.click(text=button.text)
                        clicked = True
                        break
                if clicked:
                    break
            if not clicked:
                logger.warning("Could not find Gemini button in presets")
        await asyncio.sleep(1)

        # Step 4: Send the query
        sent = await client.send_message(bot_entity, full_query)
        session_msg_ids.append(sent.id)

        # Step 5: Collect response(s) — only real ones reset idle timer
        responses = await _collect_bot_responses(
            client, bot_id,
            total_timeout=RESPONSE_WAIT_TIMEOUT,
            idle_timeout=RESPONSE_IDLE_TIMEOUT,
        )

        # Filter out status messages
        real_responses = [
            r for r in responses
            if r.message and not _is_status_message(r.message)
        ]

        # Collect IDs of all bot responses for cleanup
        session_msg_ids.extend(r.id for r in responses)

        if not real_responses:
            await send_formatted_reply(
                client, original_input_chat,
                "AI: (нет ответа от бота)",
                reply_to_msg_id=original_reply_to,
            )
        else:
            response_text = "\n".join(
                r.message for r in real_responses if r.message
            )
            response_text = _clean_response_text(response_text)
            await send_formatted_reply(
                client, original_input_chat,
                f"AI:\n{response_text}",
                reply_to_msg_id=original_reply_to,
            )

        # Step 6: Cleanup — delete only messages from this session
        # Also grab any bot replies (model confirmations etc.) between our first and last message
        try:
            if session_msg_ids:
                min_id = min(session_msg_ids) - 1
                bot_messages = await client.get_messages(
                    bot_entity, limit=50, min_id=min_id
                )
                all_ids = set(session_msg_ids)
                all_ids.update(
                    m.id for m in bot_messages if isinstance(m, types.Message)
                )
                await client.delete_messages(bot_entity, list(all_ids))
        except Exception:
            logger.warning("Failed to clean up bot chat")

    except Exception:
        logger.exception("Error handling .ai command")
        try:
            await send_formatted_reply(
                client, original_input_chat,
                messages.ERROR,
                reply_to_msg_id=original_reply_to,
            )
        except Exception:
            pass


async def _build_context(
    client: TelegramClient, message: types.Message
) -> str:
    try:
        context_messages = await client.get_messages(
            message.chat_id, limit=CONTEXT_MESSAGE_COUNT + 1
        )
        lines: list[str] = []
        for ctx_msg in reversed(context_messages):
            if not isinstance(ctx_msg, types.Message) or not ctx_msg.message:
                continue
            if ctx_msg.id == message.id:
                continue
            sender_name = "User"
            if isinstance(ctx_msg.from_id, types.PeerUser):
                try:
                    user = await client.get_entity(ctx_msg.from_id)
                    if isinstance(user, types.User):
                        sender_name = user.first_name or f"User {user.id}"
                except Exception:
                    pass
            lines.append(f"{sender_name}: {ctx_msg.message}")
        return "\n".join(lines)
    except Exception:
        logger.warning("Failed to build context")
        return ""


async def _wait_for_bot_message(
    client: TelegramClient,
    bot_id: int,
    timeout: float = 10,
) -> types.Message | None:
    result: list[types.Message] = []
    event = asyncio.Event()

    async def handler(evt: events.NewMessage.Event) -> None:
        msg = evt.message
        if not isinstance(msg, types.Message):
            return
        if _is_from_bot(msg, bot_id):
            result.append(msg)
            event.set()

    client.add_event_handler(handler, events.NewMessage)
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        client.remove_event_handler(handler, events.NewMessage)
    return result[0] if result else None


async def _collect_bot_responses(
    client: TelegramClient,
    bot_id: int,
    total_timeout: float = 90,
    idle_timeout: float = 15,
) -> list[types.Message]:
    responses: list[types.Message] = []
    loop = asyncio.get_event_loop()
    last_real_received: float | None = None
    first_received = asyncio.Event()

    async def handler(evt: events.NewMessage.Event) -> None:
        nonlocal last_real_received
        msg = evt.message
        if not isinstance(msg, types.Message):
            return
        if _is_from_bot(msg, bot_id):
            responses.append(msg)
            first_received.set()
            # Only reset idle timer for non-status messages
            if not _is_status_message(msg.message):
                last_real_received = loop.time()

    client.add_event_handler(handler, events.NewMessage)
    try:
        start = loop.time()
        try:
            await asyncio.wait_for(first_received.wait(), timeout=total_timeout)
        except asyncio.TimeoutError:
            return responses
        while True:
            now = loop.time()
            if now - start > total_timeout:
                break
            # Only apply idle timeout after we got a real (non-status) response
            if last_real_received is not None and now - last_real_received > idle_timeout:
                break
            await asyncio.sleep(0.5)
    finally:
        client.remove_event_handler(handler, events.NewMessage)
    return responses


def _is_from_bot(msg: types.Message, bot_id: int) -> bool:
    if isinstance(msg.from_id, types.PeerUser):
        return msg.from_id.user_id == bot_id
    if isinstance(msg.peer_id, types.PeerUser):
        return msg.peer_id.user_id == bot_id
    return False
