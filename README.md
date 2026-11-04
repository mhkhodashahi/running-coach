# Pulse Coach

Pulse Coach is a local-first training dashboard for reviewing activities, recovery, goals, and training plans. It imports Garmin-style CSV data and can optionally sync Garmin Connect. Coaching is optional and can use a local Ollama model or an approved remote provider.

Pulse Coach is not affiliated with Garmin, Strava, OpenAI, or Telegram. It is a training tool, not medical advice.

## What it does

- Shows Today, Activities, Trends, Coach, Training, and Settings.
- Tracks activities, health metrics, goals, effort ratings, and planned sessions.
- Builds deterministic recovery and training-load metrics and daily decisions.
- Offers optional per-activity reviews, coach chat, and Telegram messages.
- Stores application data locally in SQLite.

## Run locally

Requires Python 3.11 or newer. The first run starts with an empty local database; Garmin credentials and AI settings are optional.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m scripts.upgrade_db --db db/running_coach.db
python -m web
```

Open <http://127.0.0.1:8000>. App startup checks the database version but does not run migrations. Before upgrading, stop the web app and worker, then run the backup-first upgrade command above.

## Configuration

The quickstart copies `.env.example` to `.env`, but **no secrets or custom values are required** to start the local web app. Defaults select the local database path, localhost web address, Europe/Berlin timezone, and Ollama. Ollama coaching works only when Ollama is installed, running, and the configured model is available; without a provider, the app can still be used for its data and deterministic features.

Add values to `.env` only for features you enable:

- **Local AI:** no API key is needed. Install and start Ollama; optionally set `OLLAMA_BASE_URL` and `OLLAMA_MODEL` if you use non-default values.
- **OpenAI:** set `OPENAI_API_KEY`, `LLM_PROVIDER=openai`, `ALLOW_REMOTE_LLM=true`, and `REMOTE_ATHLETE_DATA_APPROVED=true`. Both approval flags are required before athlete data can be sent remotely.
- **Garmin Connect sync:** set `GARMIN_EMAIL` and `GARMIN_PASSWORD`. The app creates local Garmin tokens on sync. CSV import needs no Garmin credentials.
- **Telegram:** set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` for bot delivery.
- **Remote web login:** optionally set `WEB_PASSWORD`; the app signs the session cookie. The default bind remains local-only.
- **Optional preferences:** `LOCAL_TIMEZONE`, `SLEEP_GOAL_HOURS`, `HR_ZONES`, and `COACH_DAILY_CALL_LIMIT` have defaults. See comments in `.env.example` before overriding them.

## Data and privacy

- Training records, plans, chat turns, and coaching outputs are stored in the SQLite database selected by `DB_PATH` (default: `db/running_coach.db`).
- The narrative coach memory is kept separately in `data/couch_running_memory.md`. It contains compact coaching cues and recent coaching entries; it is local personal data and is git-ignored.
- Chat history is stored in the database separately from the narrative memory. Training history in SQLite is the primary input to plan suggestions.
- With Ollama, prompt data is sent to the configured Ollama server. With OpenAI, relevant activity, health, goal, plan, chat, and memory context may be sent to OpenAI. Credentials and API keys are not included in prompts. Remote sharing is refused unless both approval settings are enabled.
- Keep `.env`, Garmin tokens, databases, backups, logs, and personal exports private. Review the database and memory file before sharing diagnostic output.

## Backups and scheduled jobs

Run `python -m worker` to enable scheduled syncs, reviews, Telegram delivery, and automatic database backups. Jobs require their relevant settings; Telegram messages require Telegram configuration. The default backup directory is `~/pulse-backups/`, outside the repository.

Stop the worker and web app before restoring a database. Follow the confirmation prompt:

```bash
python -m scripts.restore_db --from ~/pulse-backups/<backup-file>.db
```

## Development

```bash
ruff check .
python -m compileall -q .
pytest
```

The web app uses FastAPI, Jinja templates, and HTMX. Tests use synthetic fixtures; do not add personal athlete data to tracked code, tests, screenshots, or documentation.

## Project layout

```text
coach/       Daily decisions, planning, proposals, workout library, and read-only tools
metrics/     Deterministic training and recovery calculations
db/          SQLite models, repositories, and Alembic migrations
services/    Imports, Garmin sync, coaching, memory, and Telegram integration
web/         FastAPI routes, templates, and self-hosted assets
worker/      Scheduled jobs and notifications
tests/       Automated tests using synthetic data
legacy/      Optional retired Streamlit interface
```

## Contributing and license

Bug reports and improvements are welcome. Please avoid including personal training data in issues. Run the checks above before submitting changes, and never commit credentials or private database files.

Pulse Coach is licensed under the [GNU Affero General Public License v3.0](LICENSE). If you modify it and make it available over a network, the AGPL requires you to offer users the corresponding source code.
