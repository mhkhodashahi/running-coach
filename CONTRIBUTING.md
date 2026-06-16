# Contributing

Thanks for considering a contribution to Running Coach.

## License

This project is source-available for personal, non-commercial use under the
Running Coach Personal Use License 1.0 in `LICENSE`. It is not an OSI-approved
open-source license because business and commercial use are not allowed.

By contributing code, documentation, tests, examples, or other changes, you
agree that your contribution is provided under the same license.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Do not commit `.env`, Garmin tokens, SQLite databases, logs, or personal export
files.

## Checks

Run these before opening a pull request:

```bash
python -m ruff check .
python -m compileall -q app analytics db llm services ui utils tests
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
- For database changes, update `db/models.py`, `db/repository.py`,
  `db/setup.py`, tests, and `docs/upgrade.md` together.
