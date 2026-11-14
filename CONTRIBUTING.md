# Contributing

Thanks for considering a contribution to Running Coach.

## License

This project is open source under the GNU Affero General Public License v3.0.
See `LICENSE`.

By contributing code, documentation, tests, examples, or other changes, you
agree that your contribution is provided under the same license.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m scripts.upgrade_db --db db/running_coach.db
```

Do not commit `.env`, Garmin tokens, SQLite databases, logs, or personal export
files.

## Checks

Run these before opening a pull request:

```bash
python -m ruff check .
python -m compileall -q analytics coach db llm metrics scripts services utils web worker tests config.py
python -m pytest
```

## Contribution Guidelines

- Keep changes focused and easy to review.
- Add or update tests for behavior changes and bug fixes.
- Keep Garmin credentials, tokens, training data, LLM prompts with personal
  details, and local database files out of commits.
- Prefer deterministic analytics for core training calculations. Use LLMs only
  where the app already has an LLM workflow.
- Do not add telemetry or external network calls without clear user control.
- Put persistence in user-scoped `db/repositories/` modules and keep routes thin.
- Schema changes need an additive Alembic revision, preservation tests and an
  update to [upgrade instructions](docs/upgrade.md). Never migrate on startup.
- Run an installed-artifact check before a release: `poetry build`, then
  `python -m scripts.check_distribution dist/<wheel>.whl`.
- See [architecture](docs/architecture.md) and the [release checklist](docs/release.md).
