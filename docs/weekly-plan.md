# Weekly Plan and Coach Proposals

Milestone 4b-2 stores a plan for each athlete and Monday-starting week. The
plan is a seven-day map with at most one session per day. A session records
sport, intent, duration, optional running HR cap, and whether it is a fixed
athlete commitment. Logged activities are separate and never modified by a
plan action.

## Flow

1. Open Coach, choose a week, and review its current sessions. Add or remove
   fixed football/volleyball training yourself if needed.
2. Choose **Suggest week** to create an unapplied proposal. It contains one
   change per suggested day, each with a reason and cited facts. No LLM or
   remote provider is called.
3. Accept or reject each change independently. You can also ask for a fresh
   day-level revision in plain words, such as "Make Saturday a rest day" or
   "Put an easy run on Thursday". Ambiguous or multi-day requests are rejected
   rather than guessed.
4. **Undo last coach change** uses the full pre-approval snapshot. Unrelated
   athlete edits are preserved. If the athlete edited the same day afterward,
   undo refuses to overwrite that newer choice.

Telegram exposes the same actions to the configured chat only: `/plan [MONDAY]`,
`/plan-suggest [MONDAY]`, `/plan-accept CHANGE_ID`, `/plan-reject CHANGE_ID`,
`/plan-revise PROPOSAL_ID make Saturday a rest day`, `/plan-undo [MONDAY]`,
`/plan-fixed Saturday football`, and `/plan-unfix Saturday`. The week commands
default to the current week; a Monday date may be supplied to inspect, suggest,
or undo another week. Fixed training also accepts a `YYYY-MM-DD` day.

## Safety and Limits

- All approval, rejection, manual commitment, and undo actions are scoped to
  one athlete and use serialized SQLite transactions. A proposal names its
  base plan revision. Another plan edit marks it stale; stale proposals cannot
  apply. An accepted change snapshots the full plan before and after writing.
- Suggestions fill only open future days, use easy running or light gym, and
  never exceed the previous week's total training minutes. The code also
  limits **projected** TRIMP to 110% of the previous week's observed session
  TRIMP and rechecks this when a change is accepted. Running is estimated at
  its Z2 HR cap; light gym uses the highest recent observed gym load per
  minute with a safety margin. If the baseline or a session estimate is
  missing, it abstains. A current illness signal or rest-level readiness
  excludes the current day, and acceptance rechecks today's recovery.
  Actual future load can differ from the projection, especially for gym and
  team sports; this is not a promise that observed load will stay under cap.
- Fixed team sessions are direct athlete actions, never coach proposals.
  They rank first in the daily decision on non-rest days; on rest days, the
  decision says to skip them or attend skills only. The plan currently holds
  one session per day and does not import external calendar commitments.
- The plan is stored in revision `0006_weekly_plan`. Upgrade only with
  `python -m scripts.upgrade_db --db <path>` after stopping app and jobs. The
  runner backs up the existing database first; see `docs/upgrade.md`.
