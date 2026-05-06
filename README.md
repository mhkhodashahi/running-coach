# Marathon Coach

Local running coach application that uses Garmin-style training data, recovery metrics, analytics, and optional LLM guidance to coach against active goals such as a 5K PB, half marathon PB, or marathon PB.

## Features

- Streamlit dashboard with a motivational, Strava-inspired running design
- Hero summary, focus cards, and key metrics for weekly mileage, readiness, recovery, VO2max, and predicted finish
- Weekly and monthly running progress chart for distance, time, and activity count
- Recent running log with activity-sized circles for quick visual training review
- Runalyze-inspired analysis page for quality sessions, training load, strain, performance curves, streaks, distributions, and efficiency
- Reusable body progress timeline with MediaPipe Pose, SAM 3D Body mesh metrics, mesh-based avatar, and LLM scan insights
- Streamlit goal management and digest history pages
- SQLite-backed storage for users, activities, health metrics, and LLM memory
- First-class goal tracking for 5K, 10K, half marathon, and marathon targets
- CSV Garmin import pipeline with mock-data fallback
- Live Garmin sync can store activity GPS/chart points and laps/splits for detailed activity views
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
body_progress/ Reusable body scan timeline, storage, processor, and avatar logic
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

The Body Progress page is hidden unless SAM mode is enabled:

```bash
use_sam=true
```

You can also use uppercase if preferred:

```bash
USE_SAM=true
```

Leave `use_sam=false` to keep the Body Progress page out of the Streamlit navigation.

If you want OpenAI coaching, set `OPENAI_API_KEY` and `LLM_PROVIDER=openai`.
If you want local coaching with Ollama, set `LLM_PROVIDER=ollama` and make sure Ollama is running.

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

The `Body Progress` page is hidden by default. Set `use_sam=true` or `USE_SAM=true` in `.env` and restart Streamlit to show it in the navigation.

## Install SAM 3D Body

SAM 3D Body is optional. Use it when you want Body Progress uploads to generate a local 3D mesh, shape/proportion metrics, and a mesh-based avatar. MediaPipe remains available as the faster fallback with `BODY_SCAN_PROCESSOR=mediapipe`.

1. Clone Meta's SAM 3D Body repo into the expected local path:

```bash
mkdir -p sam
git clone https://github.com/facebookresearch/sam-3d-body.git sam/sam-3d-body
```

If the folder already exists, update it carefully because this app has local CPU/headless patches:

```bash
cd sam/sam-3d-body
git pull
cd ../..
```

After pulling, re-check the local patches if CPU/headless runs break.

2. Install the Python dependencies used by this app and the local SAM runner:

```bash
pip install -e ".[dev]"
pip install fvcore 'iopath>=0.1.7,<0.1.10' black pycocotools tensorboard mediapipe trimesh pyrender
```

3. Log in to Hugging Face after your model access is approved:

```bash
pip install huggingface_hub
huggingface-cli login
```

4. Download the approved SAM 3D Body checkpoint:

```bash
hf download facebook/sam-3d-body-dinov3 \
  --local-dir sam/sam-3d-body/checkpoints/sam-3d-body-dinov3
```

Expected files after download:

```text
sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/model.ckpt
sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/model_config.yaml
sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/assets/mhr_model.pt
```

5. Configure `.env` and enable the Body Progress page:

```bash
use_sam=true
BODY_SCAN_PROCESSOR=sam3d
SAM3D_REPO_DIR=sam/sam-3d-body
SAM3D_CHECKPOINT_PATH=sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/model.ckpt
SAM3D_MHR_PATH=sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/assets/mhr_model.pt
SAM3D_OUTPUT_DIR=data/body_scan_outputs/sam3d
SAM3D_TIMEOUT_SECONDS=900
```

6. Run a headless smoke test with one body photo:

```bash
scripts/run_sam3d_headless.sh /full/path/to/body-photo.jpg
```

Successful output creates:

```text
*_sam3d_preview.jpg
*_person_000.ply
*_sam3d_metadata.json
```

7. Run from the app:

```bash
streamlit run app/main.py
```

Then open `Body Progress`, upload a scan, and click `Save body scan`. The app will run SAM, store the preview/mesh/metrics, update the scan card, and use the metrics in the mesh-based avatar and LLM scan insight flow.

## Run

```bash
streamlit run app/main.py
```

On first launch the app creates `db/marathon_coach.db` and loads the bundled mock data if no activities or health metrics exist yet.

## Dashboard Design

The main dashboard uses a Strava-inspired visual direction without depending on Strava branding:

- Orange-accented run visuals, dark hero card, rounded metric cards, and warmer background gradients
- Focus cards that translate current training into an immediate weekly target, main focus, and intensity balance
- `Running Progress` chart with weekly distance bars and monthly distance trend line
- `Recent Running Log` chart where each run is shown as a circle sized and colored by distance
- Existing recovery, VO2max, training load, and goal pace charts restyled to match the same design system

Streamlit navigation is implemented in `app/main.py`, the dashboard page lives in `app/dashboard.py`, reusable layout components live in `ui/components.py`, and Plotly chart builders live in `ui/charts.py`.

## Streamlit Pages

- `Dashboard`: motivational overview, weekly/monthly running progress, recent running log, active goal projection, Garmin sync, and profile management
- `Goal Achievement Readiness`: active-goal confidence, pace gap, goal-specific training interpretation, and scenario planning
- `AI Coach`: generate daily or weekly coaching digests and preview the Telegram message
- `Goals and Digests`: create goals, switch the active goal, and review digest/delivery history
- `Analysis`: Runalyze-inspired quality sessions, training condition, acute/chronic load, strain and monotony, pace curve, streak heatmap, longest streaks, HR-vs-pace efficiency, histograms, boxplots, and latest activity table
- `Quality Sessions`: focused Runalyze-inspired quality-workout page with workload chart, type breakdown, and detected session table
- `Activity Detail`: Strava-inspired single-activity view with summary hero, effort stats, route placeholder, context chart, notes, and similar activities
- `Body Progress`: private body progress photo timeline, MediaPipe pose metrics, SAM 3D Body mesh metrics, mesh-based avatar, and LLM scan insights. This page is shown only when `use_sam=true` is set in `.env`.

## Body Progress and Avatar Module

The `body_progress/` package is intentionally reusable outside this Streamlit app:

- `domain.py`: portable scan, processor result, and avatar dataclasses
- `storage.py`: local user/date-based upload storage
- `processor.py`: processor interface plus placeholder implementation
- `mediapipe_processor.py`: local photo-to-pose adapter that stores landmarks, annotated previews, and posture metrics
- `sam3d_processor.py`: SAM 3D Body adapter used by the app upload flow
- `sam3d_cli.py`: headless SAM runner used by the app and manual testing
- `mesh_analysis.py`: extracts non-medical shape/proportion metrics from SAM `.ply` meshes
- `multihmr_processor.py`: external adapter hook for future Multi-HMR mesh processing
- `avatar.py`: maps training/recovery context into an avatar state

The current app page stores private progress photos, can run SAM 3D Body or MediaPipe Pose, renders a training-aware avatar, and switches to a SAM mesh-based avatar when mesh metrics are available. Configure the processor with:

```bash
use_sam=true
BODY_SCAN_PROCESSOR=sam3d
SAM3D_REPO_DIR=sam/sam-3d-body
SAM3D_CHECKPOINT_PATH=sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/model.ckpt
SAM3D_MHR_PATH=sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/assets/mhr_model.pt
SAM3D_OUTPUT_DIR=data/body_scan_outputs/sam3d
SAM3D_TIMEOUT_SECONDS=900
```

Use `BODY_SCAN_PROCESSOR=mediapipe` when you want fast local pose metrics without running the heavy SAM model. For future 3D mesh work, set `BODY_SCAN_PROCESSOR=multihmr` after cloning a compatible Multi-HMR repo and configuring `MULTIHMR_REPO_DIR`. The service persists preview images, mesh paths, pose keypoints, shape metrics, and processor metadata through the same processor contract.

SAM 3D Body outputs are used conservatively:

- The app stores a rendered/annotated preview image for the scan card.
- The app stores a `.ply` mesh path and metadata for local inspection.
- `mesh_analysis.py` extracts relative tracking metrics such as height/width/depth proxies, width-to-height ratio, depth-to-height ratio, left/right balance, front/back balance, vertex count, and face count.
- These metrics are coaching/tracking proxies only. They are not medical measurements, body-fat estimates, diagnosis, or injury proof.
- When a SAM scan has shape metrics, the Body Progress avatar panel switches to a mesh-based runner avatar whose proportions are driven by the latest SAM width/depth ratios.

For manual SAM testing, prefer the project headless runner. It avoids the optional ViTDet/MoGe/SAM2 dependencies and avoids macOS OpenGL rendering:

```bash
scripts/run_sam3d_headless.sh /path/to/body-photo.jpg
```

If you run Meta's original `sam/sam-3d-body/demo.py`, pass empty optional modules to avoid `moge`, detector, or segmentor import errors:

```bash
cd sam/sam-3d-body
python demo.py \
  --image_folder /path/to/images \
  --checkpoint_path ./checkpoints/sam-3d-body-dinov3/model.ckpt \
  --mhr_path ./checkpoints/sam-3d-body-dinov3/assets/mhr_model.pt \
  --detector_name "" \
  --segmentor_name sam2 \
  --fov_name ""
```

The Body Progress page can also generate an LLM scan insight. It sends only coaching-relevant scan context to the configured `LLM_PROVIDER`, stores the response in `body_scan_insights`, and reuses recent insight history on the next call so analysis can evolve instead of starting from zero each time.

Data sent to the LLM includes:

- scan date, view, status, and notes
- processor name
- pose quality and posture metrics
- SAM shape metrics such as mesh height/width/depth proxies, ratios, balance, vertex/face counts
- prior scan insight summaries
- the athlete focus question from the page

Data intentionally not sent to the LLM:

- raw image paths
- mesh file paths
- checkpoint paths
- local repo/output paths
- command arrays
- stdout/stderr tails
- metadata file paths

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
cp launchd/com.marathoncoach.health-sync.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.marathoncoach.health-sync.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.marathoncoach.health-sync.plist
```

3. Optional checks:

```bash
launchctl list | grep com.marathoncoach.health-sync
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

Then message your configured bot from the Telegram chat id in `TELEGRAM_CHAT_ID`. The bot only answers that configured chat and uses your local SQLite training database plus the configured LLM provider to answer questions such as "How is my recovery today?", "What was my weekly mileage?", or "Am I on track for my marathon goal?".

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
cp launchd/com.marathoncoach.daily-digest.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.marathoncoach.daily-digest.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.marathoncoach.daily-digest.plist
```

## LLM Providers

- OpenAI: Uses the Python SDK with the Responses API.
- Ollama: Uses the local `/api/generate` endpoint.

If the configured model is unavailable, the app still works and falls back to deterministic rule-based coaching.

## Notes

- The app stores structured digest history in `coaching_decisions` and keeps legacy LLM history in `llm_memory`.
- Manual athlete notes are stored on activities.
- The mock athlete profile is backfilled into a default marathon goal when no goals exist yet.
