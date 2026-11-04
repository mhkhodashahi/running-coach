# Milestone 6l Results

## Audit

The legacy running memory was stored in the ignored file `data/couch_running_memory.md` and read by the coaching workflow, activity-opinion generation, and chat. It contained two Markdown sections with 18 bullet entries: 10 persistent cues and 8 recent coaching entries. Entries were narrative summaries with source/date, headline or summary, positives, limiters, recommendations, and evidence. The file remains untouched.

The database also contains 41 `llm_memory` history rows and 13 chat-turn rows. `llm_memory` is a coaching-history journal, not the persistent running-memory source. The new revision copies the legacy Markdown bullet entries as active `migrated` memories in category `other`; no entry text is reproduced here.

## Implementation

- Migration: `0018_coach_memories`. Adds `coach_memories`, `coach_memory_history`, and an extraction cursor table; adds the default-off `suggest_memories_llm` setting. The migration preserves the legacy file and has an isolated downgrade.
- Athlete-created memories can be added, edited, deactivated, or deleted from Me. Text-triggered `Remember:` and `Merk dir:` messages are stored directly by code. Model extraction creates suggestions only; keeping, editing, or discarding is explicit and history-backed.
- Active memories are escaped and bounded before entering chat, planning, daily brief, and opinion contexts. Structured schedule, avoided-workout, body, and preferred-time rules flow into deterministic planning and daily-decision code. Planning summaries disclose applied rules and update their `last_used_at` timestamps.
- Extraction requires the per-job opt-in, daily call budget, and remote-provider approval. Tests use fake clients; no provider is used by the test suite.

## Verification

- `ruff`: passed.
- `compileall`: passed.
- `pytest`: 743 passed; 7 warnings, no failures.
- The approved live check used two invented chat examples on a fresh temporary database. Three attempts against the configured provider ended with `APIConnectionError` before a response was received, so no extraction result was available. No real athlete data was used for that check.
- Screenshots use invented profile, memory, and proposal data in `docs/private/screenshots/6l/`.

## Gaps

- The idle worker performs extraction after five quiet minutes; a browser page-close signal is not implemented.
- Unavailability weekday rules are enforced conservatively for the whole day. The optional time-window fields are stored and displayed, but the week builder has no session start-time model with which to schedule around a partial-day window.
- Duplicate protection is exact-text based. The extraction prompt compares against active entries, but semantic equivalence is not deterministically provable.
- The legacy Markdown memory remains in use by compatibility paths and may still be refreshed by the legacy coaching workflow. Migration does not alter it.
