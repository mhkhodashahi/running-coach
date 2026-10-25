# Running Coach

Pulse Coach is a local-first web app for reviewing Garmin-style training data, recovery metrics, goals, and optional LLM coaching. It stores data in SQLite on your machine and supports CSV import, Garmin Connect sync, OpenAI, Ollama and Telegram.

This project is not affiliated with Garmin, Strava, OpenAI, Telegram, or Google. It is not medical advice.

## License

Running Coach is open source under the GNU Affero General Public License v3.0.
See `LICENSE`.

If you modify the app and make it available over a network, AGPL-3.0 requires
you to make the corresponding source code available to users of that service.

## Features

- Server-rendered Today, Activities, Trends, Coach, Plan and Settings pages
- Garmin-style CSV import and optional live Garmin Connect sync
- Activity detail page with laps, stream data, HR zones, similar activities, and stored per-run coach opinions
- Goal tracking for 5K, 10K, half, and custom running targets
- Deterministic training analytics and prediction snapshots after imported or synced runs
- Daily and weekly coaching digests with optional Telegram delivery
- LLM support through OpenAI or a local Ollama model
- SQLite persistence for activities, health metrics, goals, predictions, digests, LLM memory, and activity coach opinions

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m scripts.upgrade_db --db db/running_coach.db
python -m web
```

The web app checks the database version on startup and never migrates it. Run the backup-first upgrade command before starting it.

## Configuration

Edit `.env` after copying `.env.example`.
Settings can update only `HR_ZONES` and `SLEEP_GOAL_HOURS` in this local file.
It preserves other keys and restricts `.env` permissions to the owner.

```bash
# LLM provider: ollama, openai, or chatgpt
LLM_PROVIDER=ollama

# Local Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:14b

# OpenAI
OPENAI_API_KEY=
OPENAI_MODEL=gpt-6-luna
ALLOW_REMOTE_LLM=
REMOTE_ATHLETE_DATA_APPROVED=

# Garmin Connect sync
GARMIN_EMAIL=
GARMIN_PASSWORD=
GARMIN_SYNC_DAYS=90
GARMIN_HEALTH_SYNC_DAYS=21

# Optional Google Maps route display
GOOGLE_MAPS_API_KEY=
GOOGLE_MAPS_MAP_ID=

# Optional Telegram digest delivery
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Do not commit `.env`, Garmin token files, SQLite databases, logs, or personal exports. The `.gitignore` is set up for the common local outputs, but you should still run a secret scan before publishing forks or releases.

## Running The App

The new server-rendered Today page runs locally with:

```bash
python -m scripts.upgrade_db --db db/running_coach.db
python -m web
```

Open `http://127.0.0.1:8000`. `WEB_HOST` and `WEB_PORT` change the bind address
and port. By default the web UI only binds to the local machine. Set
`WEB_PASSWORD` in `.env` to require a signed-cookie login; a password is
required before binding to a non-local address. Use HTTPS through a trusted
reverse proxy for remote access. Profile, zones, sleep goal, goals, Garmin sync
and CSV import are in Settings. Features deferred or dropped from the old UI are
listed in `docs/milestone-5d-parity.md`.
No fonts, scripts, or styles are fetched from a CDN.

The old Streamlit interface is optional; its startup instructions are in
`legacy/streamlit/README.md`.

## Garmin Sync

Garmin sync uses the `garminconnect` Python package and your own Garmin account credentials.

```bash
GARMIN_EMAIL=your_email
GARMIN_PASSWORD=your_password
GARMIN_TOKEN_DIR=.garmin_tokens
GARMIN_SYNC_DAYS=90
GARMIN_HEALTH_SYNC_DAYS=21
GARMIN_RATE_LIMIT_COOLDOWN_MINUTES=30
```

Notes:

- Activities are fetched in one date-range call.
- Health metrics are fetched day-by-day, so the health window is intentionally shorter.
- Garmin activity details, GPS/chart points, and laps/splits are stored when available.
- Login tokens are cached under `GARMIN_TOKEN_DIR`.
- If Garmin rate-limits the account, the app records a local cooldown and shows when to retry.

## LLM Providers

OpenAI:

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-6-luna
ALLOW_REMOTE_LLM=true
REMOTE_ATHLETE_DATA_APPROVED=true
```

OpenAI uses the Responses API with response storage disabled. Set `LLM_PROVIDER=openai`
to use it; Ollama remains the default. `OPENAI_MODEL` can also be set to
`gpt-6.1-sol` or `gpt-6-astra` for more demanding coaching workloads.

Ollama:

```bash
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:14b
```

If the configured model is unavailable, some workflows fall back to deterministic rule-based coaching. Ollama prompts are guarded by a local input-size estimate to avoid sending oversized requests.

## Privacy and AI Providers

Local Ollama runs on your machine and needs no remote approval; it is supported but can be slower and weaker than a remote model on detailed session opinions. For OpenAI (including the `chatgpt` provider alias), set both `ALLOW_REMOTE_LLM=true` and `REMOTE_ATHLETE_DATA_APPROVED=true` in your private `.env`. If either is absent, the client refuses before sending data.

`COACH_DAILY_CALL_LIMIT` caps coach chat LLM requests per user and local day, including retries. Leave it empty for the default of 20; set a positive integer to change it.

Per-activity opinions send the rounded facts pack, planned and detected intent, code-generated recording notes, and running memory to the selected provider. Other optional AI coaching and chat flows can send relevant activity, health, goal, and message context. With OpenAI selected, that content goes to OpenAI; with Ollama, it stays on the configured local Ollama server. API keys and Garmin credentials are not included in coaching prompts. OpenAI requests use `store=False`.

## Telegram Digest

Generate a digest:

```bash
python -m utils.daily_digest_cli --decision-type daily
python -m utils.daily_digest_cli --decision-type weekly --skip-sync
```

Send the generated Telegram message:

```bash
python -m utils.daily_digest_cli --decision-type daily --send-telegram
```

Run the private Telegram training chat bot:

```bash
python -m utils.telegram_chat_cli
```

The bot only answers the configured `TELEGRAM_CHAT_ID`.

## Development

Install dev dependencies:

```bash
pip install -e ".[dev]"
```

CI installs with Poetry from the committed `poetry.lock` file. If you prefer
Poetry locally, run:

```bash
poetry install --extras dev
```

Run checks:

```bash
python -m ruff check .
python -m compileall -q .
python -m pytest
```

CI runs the same ruff, syntax, and pytest checks.

## Project Structure

```text
web/        FastAPI routes, templates and self-hosted static assets
analytics/  Training and recovery analytics
data/       Mock CSV data and local-only generated memory files
db/         SQLAlchemy models, SQLite setup, and repository helpers
llm/        OpenAI and Ollama clients plus response schemas
services/   Garmin import, coaching, goals, Telegram, and prediction services
legacy/streamlit/  Optional, retired Streamlit UI
utils/      CLI workflows and formatting helpers
tests/      Unit and integration-style regression tests
```

Domain vocabulary lives in `CONTEXT.md`; architecture decisions live in `docs/adr/`.
Database upgrade notes live in `docs/upgrade.md`.

## Privacy And Safety

- The app is local-first and stores data in SQLite.
- Garmin credentials, tokens, logs, and databases must stay out of git.
- LLM prompts include summarized training, recovery, goal, and activity context. Use Ollama if you do not want to send coaching context to an external API.
- The app is for training reflection and planning. It is not a medical device and does not replace professional advice.

## Open Source Checklist

Before publishing your fork or repository:

- Review `LICENSE`, `CONTRIBUTING.md`, and `SECURITY.md` for your preferred contact details.
- Run a git-history secret scan with a tool such as `gitleaks` or `trufflehog`.
- Keep personal files such as `data/couch_running_memory.md` ignored locally.
- Confirm `.env`, `.garmin_tokens/`, `db/*.db`, logs, and personal exports are not tracked.
