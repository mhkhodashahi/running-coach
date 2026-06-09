---
name: review-running
description: Review Running Coach repository changes for bugs, regressions, privacy leaks, missing tests, and risky design choices. Use when Codex is asked to review code, inspect a diff, review a PR-like change, check recent edits, or give findings before merging work in this Streamlit/SQLite running coach project.
---

# Review Running

## Start Here

Read `.codex/agent.md` first. Use `$project-guide` for general repo context.

Default to a code-review stance: findings first, ordered by severity, with file and line references. Keep summaries secondary.

## Review Setup

1. Inspect the current change set or the files the user names.
2. If no diff is available, compare the relevant files against surrounding tests and call out that the review is source-only.
3. Read nearby code, models, repository helpers, service code, and tests before judging behavior.
4. Do not edit files unless the user explicitly asks to fix the findings.

Useful commands:

```bash
git diff -- path/to/file.py
git status --short
rg -n "symbol_or_field_name" relevant_dir

```

If the workspace is not a Git repository, review the named files directly and say that no git diff was available.

## Project Risk Areas

- SQLite persistence: model fields, repository writes, fallback `CREATE TABLE IF NOT EXISTS` SQL, dataframe readers, and commits must stay consistent.
- Streamlit pages: avoid import-time side effects beyond existing page patterns; preserve page names and navigation conventions.
- Body scans: never leak raw image paths, mesh paths, checkpoint paths, command logs, stdout/stderr tails, or local runtime paths to LLM prompts or user-facing insight text unless explicitly requested for debugging.
- LLM workflows: keep schemas, prompts, normalization, fallback payloads, and `services/llm_workflow.py` usage aligned.
- SAM 3D Body: treat metrics as relative proxies only; do not imply diagnosis, exact anthropometry, body fat, or injury certainty.
- Garmin sync/import: avoid breaking activity IDs, GPS points, laps/splits, token handling, mock-data fallback, or the split between `services/garmin_client.py` orchestration and `services/garmin_normalization.py` field/unit rules.
- Goal/coaching logic: keep analytics deterministic and explainable unless the user explicitly asks for LLM behavior.
- UI changes: ensure text fits, preserve practical dashboard styling, and avoid unrelated redesigns.

## What To Check

Look for:

- behavior regressions, data loss, or broken persistence
- schema drift between DB models, SQL strings, repository functions, and tests
- table creation outside `db/setup.py` when lightweight setup should be centralized
- prompt/privacy leaks or overly broad LLM context
- missing error handling around external services or local heavy processors
- brittle path assumptions, especially around SAM paths and local output directories
- tests that assert implementation details while missing user-visible behavior
- missing targeted tests for new branches or privacy boundaries
- dead code, accidental `print`, debug logging, or exposed local paths
- stale references to removed pages such as `app/pages/6_Analysis.py` or `app/performance_dashboard.html`

## Output Format

Lead with findings. Use this shape:

```text
Findings
- High: path/to/file.py:123 - Concrete bug and why it matters.
- Medium: path/to/file.py:45 - Concrete risk and failure case.

Open Questions
- Any uncertainty that affects the review.

Summary
Brief context only after findings.

Tests
- Checks run, or checks not run and why.
```

If there are no issues, say that clearly and mention remaining test gaps or residual risk.

Do not bury findings in prose. Do not spend space praising the code.
