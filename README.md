# tg-userbot

Telegram userbot that auto-transcribes voice messages and provides AI-powered commands, using Google GenAI.

## Features

- **Auto-transcription** — automatically transcribes voice messages in private chats and configurable group chats
- `/convert` — transcribe a replied voice message on demand
- `/ai {prompt}` — ask AI a question; supports reply to text or voice for additional context
- `/tldr` — summarize a replied message (text or voice)
- `/summary {count} [prompt]` — summarize the last N messages in a group chat (supports forum topics)
- `/g {query}` — generate a Google search link; can combine query with replied message text
- `/n [text]` — edit a message to append a disclaimer (edits replied message or the command message itself)

## Setup

### Prerequisites

- Node.js 22+
- pnpm 10+

### Get Telegram API credentials

1. Go to [my.telegram.org](https://my.telegram.org)
2. Log in and go to **API development tools**
3. Create an application to get your `API_ID` and `API_HASH`

### Get a Google API key

1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Create an API key

### Run locally

```bash
cp .env.example .env
# Fill in .env with your credentials
pnpm install
pnpm dev
```

On first login the bot will prompt for your phone number and auth code. After login it prints a `TG_SESSION` string — save it to `.env` so future runs skip the login prompt.

### Run with Docker

```bash
cp .env.example .env
# Fill in .env with your credentials

# First run — interactive login (prompts for phone code):
docker compose run --rm tg-userbot

# After saving TG_SESSION to .env, run in background:
docker compose up -d
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `TG_API_ID` | Yes | Telegram API ID (number) |
| `TG_API_HASH` | Yes | Telegram API hash |
| `GOOGLE_API_KEY` | Yes | Google GenAI API key |
| `TG_SESSION` | No | Session string (printed on first login) |
| `TG_PHONE_NUMBER` | No | Phone number for non-interactive login |
| `TG_PASSWORD` | No | 2FA password for non-interactive login |
| `TG_PHONE_CODE` | No | Auth code for non-interactive login |
| `GOOGLE_MODEL` | No | Model for transcription (default: `gemini-2.5-flash`) |
| `GOOGLE_TEXT_MODEL` | No | Model for text AI commands (default: same as `GOOGLE_MODEL`) |
| `AUTO_TRANSCRIBE_PEER_IDS` | No | Comma-separated peer IDs to auto-transcribe in (besides private chats) |
| `TRANSCRIBE_DISABLED_PEER_IDS` | No | Comma-separated peer IDs where auto-transcription is disabled |
| `GOOGLE_API_BASE_URL` | No | Custom base URL for Google API (for proxying in unsupported regions) |

## Architecture

- **Domain** — `Transcriber`, `AI` interfaces
- **Impl** — Google GenAI adapters (`@google/genai`)
- **Application** — use cases (private auto-transcribe, `/convert`, `/ai`, `/tldr`, `/summary`, `/g`, `/n`)
- **Presentation** — ordered handlers registry and bot event loop

## Deployment

See `scripts/deploy.sh`. Requires `DEPLOY_HOST` and optionally `DOCKER_IMAGE` / `DEPLOY_PATH` env vars.

## License

[MIT](LICENSE)
