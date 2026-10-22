# Milestone 3 Results: Coach Opinion JSON V2

## Scope

Added a strict v2 opinion schema, a read-only legacy mapping, evidence checking,
an explicit regeneration path with transactional history, and a minimal Activity
Detail rendering update. Existing opinion JSON is never backfilled or rewritten
by the migration. The migration adds nullable intent and validation-note fields
and an empty history table. No import, dashboard metric, or coach-chat behavior
was changed.

The v2 prompt receives the athlete profile from the `users` row, the active
goal and activity detail from SQLite, dated metrics from `metrics.get_daily_snapshot`,
and the existing running-memory block. Custom HR zones come only from the
optional `HR_ZONES` config value; empty means no custom zones are asserted.
`HR_ZONES` is a JSON array of objects with `name`, `lower_bpm`, and `upper_bpm`
(the last may be null); `.env.example` leaves it empty. No personal profile or
custom zone values remain in tracked prompt source.

## Data Safety

Revision `0004_coach_opinion_v2` has no backfill. Old opinion rows retain their
stored bytes and are mapped only when read. Regenerate archives the prior JSON,
context, model and timestamps before replacing the current row in one
transaction. Failed validation leaves the current row untouched. When the
evidence retry still contains unsupported numeric claims, the saved v2 opinion
is marked low confidence and the claims are recorded in `validation_notes`.

## Verification

Tests use invented athletes and temporary SQLite files; provider tests mock
the LLM. The actual pre-upgrade database was backed up into a temporary
directory and revision 0004 was applied only to a candidate copy. Existing
table counts, JSON strings, body-scan schemas and rows were identical. The
new fields remained NULL and history was empty. `PRAGMA integrity_check`
passed. Foreign-key violations existed before the upgrade and remained
unchanged; they were not introduced by this revision. A second upgrade left
the candidate file hash unchanged. The working database was not upgraded.

Ruff, compileall and full pytest passed. The configured local Ollama model
timed out for the real-run sample. A smaller installed local model generated
a v2 sample on the candidate copy, but its evidence check marked it low
confidence. Its coaching content still requires athlete review. Any real
opinion JSON is shown only in the reply, never stored in this document.
Streamlit smoke tests on the candidate copy rendered both v2 and legacy
opinions without page exceptions; reading the legacy view left its stored
JSON and version unchanged.
