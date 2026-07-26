# tg-userbot

Telegram userbot with voice transcription, deleted message tracking, and utility commands.

## Features

- **Auto-transcription** — automatically transcribes voice messages in private chats and configurable group chats (via SpeechRecognition)
- **Transcript TL;DR** — transcripts of 600+ characters get a short summary (Groq LLM) shown above the collapsed full text
- `.convert` — transcribe a replied voice message on demand
- `.dl [url]` — download a video via yt-dlp (YouTube/TikTok/X/…) and send it to the chat; `.dl -a [url]` extracts MP3 audio
- `.q [N]` — render a replied message as a quote sticker (via the public quote API); `N` quotes several consecutive messages
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
| `TRANSCRIBE_SUMMARY_ENABLED` | No | TL;DR for long transcripts (default `true`; needs `GROQ_API_KEY`) |
| `YTDLP_COOKIES_FILE` | No | Path to a Netscape cookies file for `.dl` (needed for Instagram / age-gated YouTube) |
| `QUOTE_API_URL` | No | Renderer endpoint for `.q` (default `http://127.0.0.1:3000/generate`, the `quote-api` sidecar) |

### `.q` renderer

`.q` needs a [LyoSU/quote-api](https://github.com/LyoSU/quote-api) instance. The public one
(`bot.lyo.su`) is unreliable, so `docker-compose.yml` builds a `quote-api` sidecar from source
and the userbots reach it over the host network. First build pulls Node + compiles canvas, so
it takes a few minutes:

```bash
docker compose build quote-api && docker compose up -d quote-api
curl -s http://127.0.0.1:3000/health
```

## Deployment

```bash
DEPLOY_HOST=your-server DOCKER_IMAGE=your-registry/tg-userbot bash scripts/deploy.sh
```

## License

[MIT](LICENSE)
