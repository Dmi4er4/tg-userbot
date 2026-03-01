import asyncio
import logging
import re

from telethon import TelegramClient, events
from telethon.tl import types

from src_py import messages
from src_py.telegram_utils.utils import get_replied_message, send_formatted_reply

logger = logging.getLogger(__name__)

RESPONSE_WAIT_TIMEOUT = 45
RESPONSE_IDLE_TIMEOUT = 5
CONTEXT_MESSAGE_COUNT = 5

_ai_lock = asyncio.Lock()


def _parse_ai_query(text: str | None) -> str:
    raw = (text or "").strip()
    return re.sub(r"^\.ai\s*", "", raw, flags=re.IGNORECASE).strip()


async def command_ai(
    client: TelegramClient,
    message: types.Message,
    *,
    eliza_bot_id: int,
) -> None:
    async with _ai_lock:
        await _command_ai_impl(client, message, eliza_bot_id=eliza_bot_id)


async def _command_ai_impl(
    client: TelegramClient,
    message: types.Message,
    *,
    eliza_bot_id: int,
) -> None:
    original_peer = message.peer_id
    original_reply_to = None

    try:
        user_query = _parse_ai_query(message.message)
        replied = await get_replied_message(client, message)
        if replied:
            original_reply_to = replied.id

        parts: list[str] = []
        if replied and replied.message:
            parts.append(replied.message.strip())
        if user_query:
            parts.append(user_query)

        if not parts:
            await send_formatted_reply(
                client, message.peer_id,
                "Использование: .ai <вопрос> (можно ответом на сообщение)",
                reply_to_msg_id=message.id,
            )
            return

        # Delete the .ai command message
        try:
            await client.delete_messages(message.peer_id, [message.id])
        except Exception:
            logger.warning("Failed to delete .ai command message")

        # Gather context from current chat
        context_text = await _build_context(client, message)

        full_query = "\n".join(parts)
        if context_text:
            full_query = (
                f"Контекст переписки:\n{context_text}\n\nВопрос:\n{full_query}"
            )

        # Step 1: Clear context in bot
        await client.send_message(eliza_bot_id, "/clear")
        await asyncio.sleep(1)

        # Step 2: Select model via /presets
        await client.send_message(eliza_bot_id, "/presets")
        preset_msg = await _wait_for_bot_message(client, eliza_bot_id, timeout=10)

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
        await client.send_message(eliza_bot_id, full_query)

        # Step 5: Collect response(s)
        responses = await _collect_bot_responses(
            client, eliza_bot_id,
            total_timeout=RESPONSE_WAIT_TIMEOUT,
            idle_timeout=RESPONSE_IDLE_TIMEOUT,
        )

        if not responses:
            await send_formatted_reply(
                client, original_peer,
                "AI: (нет ответа от бота)",
                reply_to_msg_id=original_reply_to,
            )
        else:
            response_text = "\n".join(
                r.message for r in responses if r.message
            )
            await send_formatted_reply(
                client, original_peer,
                f"AI:\n{response_text}",
                reply_to_msg_id=original_reply_to,
            )

        # Step 6: Cleanup bot chat
        try:
            bot_messages = await client.get_messages(eliza_bot_id, limit=50)
            msg_ids = [
                m.id for m in bot_messages
                if isinstance(m, types.Message)
            ]
            if msg_ids:
                await client.delete_messages(eliza_bot_id, msg_ids)
        except Exception:
            logger.warning("Failed to clean up bot chat")

    except Exception:
        logger.exception("Error handling .ai command")
        try:
            await send_formatted_reply(
                client, original_peer,
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
            message.peer_id, limit=CONTEXT_MESSAGE_COUNT + 1
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
        sender_id = None
        if isinstance(msg.from_id, types.PeerUser):
            sender_id = msg.from_id.user_id
        elif isinstance(msg.peer_id, types.PeerUser):
            sender_id = msg.peer_id.user_id
        if sender_id == bot_id:
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
    total_timeout: float = 45,
    idle_timeout: float = 5,
) -> list[types.Message]:
    responses: list[types.Message] = []
    loop = asyncio.get_event_loop()
    last_received = loop.time()
    first_received = asyncio.Event()

    async def handler(evt: events.NewMessage.Event) -> None:
        nonlocal last_received
        msg = evt.message
        if not isinstance(msg, types.Message):
            return
        sender_id = None
        if isinstance(msg.from_id, types.PeerUser):
            sender_id = msg.from_id.user_id
        elif isinstance(msg.peer_id, types.PeerUser):
            sender_id = msg.peer_id.user_id
        if sender_id == bot_id:
            responses.append(msg)
            last_received = loop.time()
            first_received.set()

    client.add_event_handler(handler, events.NewMessage)
    try:
        start = loop.time()
        # Wait for first response
        try:
            await asyncio.wait_for(first_received.wait(), timeout=total_timeout)
        except asyncio.TimeoutError:
            return responses
        # Then wait for idle
        while True:
            now = loop.time()
            if now - start > total_timeout:
                break
            if now - last_received > idle_timeout:
                break
            await asyncio.sleep(0.5)
    finally:
        client.remove_event_handler(handler, events.NewMessage)
    return responses
