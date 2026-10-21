# Running Coach Agent Notes

## Current stack

- Language: Python `>=3.11,<4.0` (`pyproject.toml`); CI runs Python 3.11. The inspected local virtualenv runs Python 3.13.
- Web framework: Streamlit, with `app/main.py` as the entry point, `app/dashboard.py` for Today, and other pages under `app/pages/`. Plotly renders charts; `ui/` contains shared presentation code.
- Database: local SQLite at `db/running_coach.db` by default, overridable with `DB_PATH` in `.env`. `config.py` resolves the path, `db/session.py` owns the SQLAlchemy engine and sessions, `db/models.py` defines mapped tables, `db/repository.py` owns access helpers, and `db/setup.py` creates tables and applies lightweight compatibility SQL. Back up the database before schema changes; see `docs/upgrade.md`.
- Garmin import: `services/garmin_client.py` implements live Garmin Connect sync through `garminconnect` and CSV import through pandas. `services/garmin_normalization.py` normalizes rows; `services/import_service.py` persists them. Entry points are the sidebar in `ui/sidebar.py`, `utils/garmin_sync_cli.py` (`sync-garmin`), and `utils/daily_digest_cli.py`; bootstrap also imports bundled demo CSVs. There is no FIT file importer or FIT upload path in this checkout.
- LLM providers: `llm/factory.py` selects local Ollama (default) or OpenAI/ChatGPT from `LLM_PROVIDER`; `llm/ollama_client.py` and `llm/openai_client.py` implement JSON generation. `llm/schemas.py` defines response shapes. Rules-based fallback exists for some coaching workflows.
- Run: `python -m venv .venv`, `source .venv/bin/activate`, `pip install -e ".[dev]"`, `cp .env.example .env`, then `streamlit run app/main.py`. Optional local Ollama, Garmin, Telegram, and Maps credentials are configured in `.env`.
- Test: `python -m pytest`; quality checks are `python -m ruff check .` and `python -m compileall -q app analytics db llm services ui utils tests`. The same checks run in GitHub Actions. Local equivalents use `.venv/bin/python -m ...`.

The requested "Target architecture" and "Coach opinion JSON" sections were not present in this checkout when this file was created. `docs/PLAN.md` records the current implementation and a provisional plan; compare it with those sections when their source is available.
