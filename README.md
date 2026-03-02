# tg-userbot

Telegram userbot with voice transcription, deleted message tracking, and utility commands.

## Features

- **Auto-transcription** — automatically transcribes voice messages in private chats and configurable group chats (via SpeechRecognition)
- `.convert` — transcribe a replied voice message on demand
- `.save [tag]` — save a replied message to the userbot channel with `#tag` (default `#save`)
- `.id` — show the ID of a user (reply) or current chat
- `.sticker` — convert a replied sticker to a regular photo (PNG)
- `.ss [url]` — screenshot a website and send as photo
- `.w [term]` — look up a term on Wikipedia (ru, then en fallback)
- `.g {query}` — generate a Google search link; can combine query with replied message text
- `.n [text]` — edit a message to append a disclaimer
- `.ai [question]` — ask a question to an AI bot (Gemini via @genesis_test_bot); supports reply context
- **Deleted/edited message tracker** — automatically forwards deleted and edited messages to the userbot channel with `#deleted` / `#edited` tags (channels and archived chats are ignored; edits under 3 characters are skipped)
- **Disappearing media** — automatically saves self-destructing photos and media to the channel with `#disappearing` tag

## Setup

### 1. Login

Login mode asks for API credentials interactively and prints a `TG_SESSION` string.

```bash
# Locally:
pip install -r requirements.txt
python -m src_py login

# Or via Docker:
docker compose run --rm dmi4er4-userbot python -m src_py login
```

### 2. Configure

```bash
cp .env.example .env.dmi4er4
```

Paste the `TG_SESSION` value from the login step. Optionally set `USERBOT_CHANNEL_ID`.

### 3. Run

```bash
# Docker:
docker compose up -d dmi4er4-userbot

# Or locally:
python -m src_py
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `TG_API_ID` | Yes | Telegram API ID |
| `TG_API_HASH` | Yes | Telegram API hash |
| `TG_SESSION` | Yes | Session string (run `python -m src_py login` to generate) |
| `USERBOT_CHANNEL_ID` | No | Channel ID for saving messages (default: Saved Messages) |
| `AUTO_TRANSCRIBE_PEER_IDS` | No | Comma-separated peer IDs to auto-transcribe in |
| `TRANSCRIBE_DISABLED_PEER_IDS` | No | Comma-separated peer IDs where auto-transcription is disabled |
| `DELETED_TRACKER_ENABLED` | No | Enable deleted message tracker (default: `true`) |
| `ELIZA_BOT_USERNAME` | No | Telegram bot username for `.ai` command (`.ai` disabled if not set) |

## Deployment

```bash
DEPLOY_HOST=your-server DOCKER_IMAGE=your-registry/tg-userbot bash scripts/deploy.sh
```

## License

[MIT](LICENSE)
