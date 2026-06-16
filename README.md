# Running Coach

Running Coach is a local-first Streamlit app for reviewing Garmin-style running data, recovery metrics, goals, predictions, and optional LLM coaching. It stores data in SQLite on your machine and can work with mock CSV data, Garmin Connect sync, OpenAI, Ollama, Telegram, and Google Maps.

This project is not affiliated with Garmin, Strava, OpenAI, Telegram, or Google. It is not medical advice.

## License

Running Coach is source-available for personal, non-commercial use under the
Running Coach Personal Use License 1.0. See `LICENSE`.

Business, commercial, professional, SaaS, consultancy, employer, client, or
revenue-generating use is not allowed without separate written permission.

Because commercial use is restricted, this is not an OSI-approved open-source
license.

## Features

- Streamlit dashboard for weekly mileage, readiness, recovery, VO2max, predicted finish, and goal progress
- Garmin-style CSV import and optional live Garmin Connect sync
- Activity detail page with route maps, laps, stream data, HR zones, similar activities, and stored per-run coach opinions
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
streamlit run app/main.py
```

On first launch, the app creates `db/running_coach.db` and loads the bundled mock CSV data if no activities or health metrics exist yet.

## Configuration

Edit `.env` after copying `.env.example`.

```bash
# LLM provider: ollama, openai, or chatgpt
LLM_PROVIDER=ollama

# Local Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:14b

# OpenAI
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini

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

```bash
streamlit run app/main.py
```

The dashboard sidebar can import activity/health CSV files or sync recent Garmin data when credentials are configured.

## Streamlit Pages

- `Dashboard`: weekly/monthly running progress, recent run log, active goal projection, prediction trend, Garmin sync, and profile management
- `Activities`: imported and synced activity table
- `Recovery`: sleep, HRV, resting HR, body battery, stress, and recovery charts
- `Goal Achievement Readiness`: active-goal confidence, pace gap, and scenario planning
- `AI Coach`: daily or weekly coaching digest generation and Telegram preview
- `Goals and Digests`: goal management and digest history
- `Quality Sessions`: quality-workout detection, workload chart, and session table
- `Activity Detail`: single-activity view with route, effort stats, prediction after the run, notes, and one-time stored LLM coach opinion

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
OPENAI_MODEL=gpt-5-mini
```

Ollama:

```bash
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:14b
```

If the configured model is unavailable, some workflows fall back to deterministic rule-based coaching. Ollama prompts are guarded by a local input-size estimate to avoid sending oversized requests.

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

Run checks:

```bash
python -m ruff check .
python -m compileall -q app analytics db llm services ui utils tests
python -m pytest
```

CI runs the same ruff, syntax, and pytest checks.

## Project Structure

```text
app/        Streamlit entry point, dashboard, and pages
analytics/  Training and recovery analytics
data/       Mock CSV data and optional local memory template
db/         SQLAlchemy models, SQLite setup, and repository helpers
llm/        OpenAI and Ollama clients plus response schemas
services/   Garmin import, coaching, goals, Telegram, and prediction services
ui/         Plotly chart builders and Streamlit components
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
- Replace personal files such as `data/couch_running_memory.md` with a generic template or keep them ignored locally.
- Confirm `.env`, `.garmin_tokens/`, `db/*.db`, logs, and personal exports are not tracked.
