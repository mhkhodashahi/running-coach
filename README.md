# Running Coach

Local running coach application that uses Garmin-style training data, recovery metrics, analytics, and optional LLM guidance to coach against active goals such as a 5K PB, half running PB, or running PB.

## Features

- Streamlit dashboard with a motivational, Strava-inspired running design
- Hero summary, focus cards, and key metrics for weekly mileage, readiness, recovery, VO2max, and predicted finish
- Weekly and monthly running progress chart for distance, time, and activity count
- Recent running log with activity-sized circles for quick visual training review
- Runalyze-inspired analysis page for quality sessions, training load, strain, performance curves, streaks, distributions, and efficiency
- Streamlit goal management and digest history pages
- SQLite-backed storage for users, activities, health metrics, and LLM memory
- First-class goal tracking for 5K, 10K, half running, and running targets
- CSV Garmin import pipeline with mock-data fallback
- Live Garmin sync can store activity names, GPS/chart points, and laps/splits for detailed activity views
- Per-run LLM coach opinions on the activity detail page, generated once and then served from SQLite
- Prediction snapshots after each run so predicted finish history can be reviewed over time
- Rule-based fatigue and recovery checks
- LLM coaching with either OpenAI or Ollama
- Explainable daily and weekly coaching that states why a recommendation is better and whether current training looks effective
- End-of-day digest drafting with optional Telegram delivery
- Plotly charts for mileage, pace, heart rate, VO2max, recovery, training load, and goal pace
- Manual notes for training sessions

## Project Structure

```text
.codex/      Codex agent guide and project skills
app/          Streamlit navigation entry point, dashboard page, and pages
analytics/    Training and recovery analytics
data/         Mock Garmin CSV data
db/           SQLite models, session, and repositories
llm/          OpenAI and Ollama adapters
services/     Import, goal, coaching, and Telegram services
ui/           Plotly charts and reusable Streamlit components
utils/        Bootstrap, CLI workflows, and formatting helpers
```

`app/main.py` owns Streamlit navigation with `st.navigation`, while `app/dashboard.py` contains the dashboard page content. Repository-specific agent guidance lives in `.codex/agent.md`.

## Setup

1. Create a virtual environment or use Poetry.
2. Install dependencies:

```bash
pip install -e ".[dev]"
```

or

```bash
poetry install
```

3. Create your environment file:

```bash
cp .env.example .env
```

4. Set the feature flags and providers you want in `.env`.

## Environment Settings

Add only the services you plan to use to `.env`. The most common settings are:

```bash
# OpenAI coaching
LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-5-mini

# Local Ollama coaching
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:14b

# Garmin sync
GARMIN_EMAIL=your_garmin_email@example.com
GARMIN_PASSWORD=your_garmin_password
GARMIN_SYNC_DAYS=90
GARMIN_HEALTH_SYNC_DAYS=21
```

Create an OpenAI API key from your OpenAI platform account, then paste it into `OPENAI_API_KEY`. Use the same Garmin username/email and password you use to sign in to Garmin Connect for `GARMIN_EMAIL` and `GARMIN_PASSWORD`.

If you want OpenAI coaching, set `OPENAI_API_KEY` and `LLM_PROVIDER=openai`. If you want local coaching with Ollama, set `LLM_PROVIDER=ollama` and make sure Ollama is running.

If you want Telegram delivery, configure your bot token and chat id:

```bash
TELEGRAM_BOT_TOKEN=123456:your_bot_token
TELEGRAM_CHAT_ID=123456789
```

If you want exact GPS route polylines on the `Activity Detail` page, configure Google Maps:

```bash
GOOGLE_MAPS_API_KEY=your_google_maps_javascript_api_key
GOOGLE_MAPS_MAP_ID=your_optional_vector_map_id
```

Without this key, the page still embeds Google Maps centered on the activity start when GPS points exist, but it cannot draw the exact route polyline. `GOOGLE_MAPS_MAP_ID` is optional, but recommended for the 3D-style tilted hybrid route map.

## Run

```bash
streamlit run app/main.py
```

On first launch the app creates `db/running_coach.db` and loads the bundled mock data if no activities or health metrics exist yet.

## Dashboard Design

The main dashboard uses a Strava-inspired visual direction without depending on Strava branding:

- Orange-accented run visuals, dark hero card, rounded metric cards, and warmer background gradients
- Focus cards that translate current training into an immediate weekly target, main focus, and intensity balance
- `Running Progress` chart with weekly distance bars and monthly distance trend line
- `Recent Running Log` chart where each run is shown as a circle sized and colored by distance
- `Prediction Trend` chart built from per-run prediction snapshots
- Existing recovery, VO2max, training load, and goal pace charts restyled to match the same design system

Streamlit navigation is implemented in `app/main.py`, the dashboard page lives in `app/dashboard.py`, reusable layout components live in `ui/components.py`, and Plotly chart builders live in `ui/charts.py`.

## Streamlit Pages

- `Dashboard`: motivational overview, weekly/monthly running progress, recent running log, active goal projection, prediction trend, Garmin sync, and profile management
- `Goal Achievement Readiness`: active-goal confidence, pace gap, goal-specific training interpretation, and scenario planning
- `AI Coach`: generate daily or weekly coaching digests and preview the Telegram message
- `Goals and Digests`: create goals, switch the active goal, and review digest/delivery history
- `Analysis`: Runalyze-inspired quality sessions, training condition, acute/chronic load, strain and monotony, pace curve, streak heatmap, longest streaks, HR-vs-pace efficiency, histograms, boxplots, and latest activity table
- `Quality Sessions`: focused Runalyze-inspired quality-workout page with workload chart, type breakdown, and detected session table
- `Activity Detail`: Strava-inspired single-activity view with Garmin activity name, summary hero, effort stats, route map, context chart, prediction after this run, one-time stored LLM coach opinion, notes, and similar activities

## Prediction Snapshots

Goal predictions are recalculated after every imported or synced run and stored in `prediction_snapshots`. The dashboard uses those saved rows to show how predicted finish time changes over time, and the `Activity Detail` page shows the prediction that existed immediately after the selected run.

If old data has no snapshots yet, the app backfills them during bootstrap from the existing activity history.

## Per-Run Coach Opinions

The `Activity Detail` page can generate a high-context LLM coach opinion for each run. The app sends the selected run, athlete profile, active goal, recent activity context, laps, stream points, notes, and recovery context to the configured LLM provider, then saves the structured result in `activity_coaching_insights`.

Each activity is analyzed once. After the result is stored, the page loads the saved coach opinion from SQLite instead of calling the LLM again.

## CSV Import

The dashboard sidebar accepts two CSV files:

- Activities CSV
- Health metrics CSV

The bundled mock files in `data/` are valid examples of the expected schema.

The importer also handles the Garmin activity CSV shape produced by the existing `sport/garmin_data_fetcher.py` export, including fields such as `activityId`, `startTimeLocal`, `averageHR`, and Garmin training-effect columns.

## Direct Garmin Sync

You can sync directly from Garmin Connect in the dashboard sidebar.

1. Set credentials in `.env`:

```bash
GARMIN_EMAIL=your_email
GARMIN_PASSWORD=your_password
GARMIN_TOKEN_DIR=.garmin_tokens
GARMIN_SYNC_DAYS=90
GARMIN_HEALTH_SYNC_DAYS=21
GARMIN_RATE_LIMIT_COOLDOWN_MINUTES=30
```

2. Start the app:

```bash
streamlit run app/main.py
```

3. In the sidebar, use `Sync from Garmin`.

Notes:

- Activities are fetched in one date-range call.
- For each synced activity, the app attempts to fetch Garmin activity details, GPS/chart points, and laps/splits into `activity_track_points` and `activity_laps`.
- Activity detail data is visible on the `Activity Detail` page when present.
- Health metrics are fetched day-by-day, so the health window is intentionally shorter.
- Successful logins are cached in `GARMIN_TOKEN_DIR`, with `garminconnect 0.3.x` storing tokens in `garmin_tokens.json`.
- The first sync after upgrading from `garminconnect 0.2.x` requires a fresh login because the old OAuth token files are no longer reused.
- If Garmin rate-limits the account, the app records a short cooldown locally and shows when you can retry.
- If Garmin rate-limits the account repeatedly, reduce the sync windows and retry later.

### Daily macOS Health Sync

On a Mac, use `launchd` instead of cron.

1. Manual health-only sync:

```bash
./scripts/run_daily_health_sync.sh
```

2. Install the daily 9:00 AM job:

```bash
mkdir -p ~/Library/LaunchAgents
cp launchd/com.runningcoach.health-sync.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.runningcoach.health-sync.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.runningcoach.health-sync.plist
```

3. Optional checks:

```bash
launchctl list | grep com.runningcoach.health-sync
tail -f logs/garmin-health-sync.log
```

The wrapper runs `python -m utils.garmin_sync_cli --health-only --days 1 --health-days 1`, so it writes only health rows to the database.

## Daily Coaching Digest

Generate a goal-aware digest from the command line:

```bash
python -m utils.daily_digest_cli --decision-type daily
```

Generate and send the Telegram message after syncing Garmin:

```bash
python -m utils.daily_digest_cli --decision-type daily --send-telegram
```

Run the private Telegram training chat bot:

```bash
python -m utils.telegram_chat_cli
```

Then message your configured bot from the Telegram chat id in `TELEGRAM_CHAT_ID`. The bot only answers that configured chat and uses your local SQLite training database plus the configured LLM provider to answer questions such as "How is my recovery today?", "What was my weekly mileage?", or "Am I on track for my running goal?".

Generate a weekly coaching digest without syncing first:

```bash
python -m utils.daily_digest_cli --decision-type weekly --skip-sync
```

### Daily macOS Digest Job

Manual digest run:

```bash
./scripts/run_daily_digest.sh
```

Install the daily 8:30 PM job:

```bash
mkdir -p ~/Library/LaunchAgents
cp launchd/com.runningcoach.daily-digest.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.runningcoach.daily-digest.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.runningcoach.daily-digest.plist
```

## LLM Providers

- OpenAI: Uses the Python SDK with the Responses API.
- Ollama: Uses the local `/api/generate` endpoint.

If the configured model is unavailable, the app still works and falls back to deterministic rule-based coaching.

## Notes

- The app stores structured digest history in `coaching_decisions` and keeps legacy LLM history in `llm_memory`.
- Manual athlete notes are stored on activities.
- The mock athlete profile is backfilled into a default running goal when no goals exist yet.
