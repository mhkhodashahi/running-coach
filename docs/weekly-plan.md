# Weekly Plan and Coach Proposals

Milestone 4b-2 uses `fixed_commitments` for recurring team training,
`protected_habits` for athlete-owned sessions, and `plan_sessions` for dated
sessions. Protected habits are projected into each week without seeding dated
rows. They use separate days, preferring non-team days. A week may contain multiple sessions per
day. Logged activities remain separate. Matching imported activities link to a
planned session and mark it done; the import never rewrites the activity.

## Flow

1. Open **Plan** to add a recurring football or volleyball commitment, or a
   protected habit with a weekly frequency. Neither is shortened or removed
   by weekly proposals. Editing a protected habit versions the plan.
2. **Suggest week** builds the sessions in code from the prior four complete
   weeks' median running and gym sessions per week. The LLM only explains the
   code-built changes. Nothing is applied automatically. Every change has a
   reason and cited fact IDs.
3. Select groups, then apply the selected groups in one transaction. Changes
   that depend on one another share a group and cannot be accepted separately.
   Unselected changes are rejected. **Apply nothing** or **Dismiss** leaves the
   plan unchanged. A plain-word revision creates a new proposal and supersedes
   the old one.
   An accepted removal marks a plan session skipped, retaining its row for
   audit and undo.
4. **Undo last coach changes** restores only the rows affected by the latest
   coach approval. If one of those rows was edited afterward, undo refuses
   rather than overwrite the newer choice. Unrelated manual edits survive.

Telegram `/plan [MONDAY]` is read-only and points to the app for review and
approval. No Telegram command applies a plan change.

## Load Estimate

For each of the athlete's prior activities, the metrics engine computes
session TRIMP. Code divides that session load by
duration in minutes, then takes the median rate for its sport and planned
intent. When that combination has no history, the sport median is used.
The estimated load of a planned training session is
`duration_min * median TRIMP/min`. Planned training estimates are summed;
walking is excluded. Expected walking is shown separately as the last 28
days' walking TRIMP divided by four, never as a training recommendation.
The cap is `1.10 * median(last eight complete weeks with recorded training)`.
Walking-only and empty weeks, the unfinished current week, and weeks with
unresolved session load are excluded. With fewer than three qualifying weeks
there is no load cap; hard-day rules still apply. See `docs/metrics.md`.
Historical session duration is not bucketed: the median is a TRIMP-per-minute
rate per sport and intent, multiplied by each proposed duration. If a session
lacks HR load, code estimates it from the athlete's own sport/intent median
and records the count in the facts. An unresolved load makes that reference
week ineligible rather than zero. Team
sports' HR-based load may miss jumps and sprints until effort ratings arrive
in milestone 4c.

Code also enforces at most two hard days, no adjacent hard days, and today's
and tomorrow's daily decisions, plus one rest day. Tempo and race, plus team
training/matches, count as hard. Fixed sessions are counted first and are
immutable to the weekly planner, including matches. When load is tight, code
shortens flexible sessions to 15 minutes before dropping them; it never
shortens or removes fixed or protected sessions. A longer easy run is included
for an active running goal only when it fits. If the reference habits have no
running and a running goal is active, the planner instead tries one 30-minute
easy run with a Z2 cap and a `rebuild` note; if it cannot fit, the summary
suggests trying it next week. When flexible training is dropped, the proposal
may add 15-minute mobility items on open days. Those use the non-training
`mobility` sport and zero planned training TRIMP; optional walking is an
advisory, not a training session. Mobility rows live in the additive
`plan_mobility_sessions` table, not the constrained `plan_sessions` table,
and cannot be linked to gym activity imports. Fixed and protected sessions
always remain; a warning says "heavier than any recent week" only if their
load exceeds the highest selected reference week. If no safe
addition exists it explains why; a complete safe week is labeled
`already_planned`, not `no_safe_change`. Only a separate same-day daily-decision
proposal may suggest lighter participation, with athlete approval.

The label `lighter week` is used only when the week-start daily decision has
load ratio above 1.3 or readiness below 50. Otherwise a crowded plan says
"full week: your team sessions and protected habits use this week's budget".

The Plan page shows each day's estimated TRIMP and the weekly total against
the cap. The exact accepted group set is revalidated before any plan write;
unsafe selections leave the proposal and plan unchanged.

`plan_versions` increments on plan edits. A proposal whose base version no
longer matches is stale. `plan_snapshots` holds undo state. Revision
`0006_weekly_plan`, additive `0007_proposal_groups`, and additive
`0008_protected_habits` and `0009_mobility_sessions` are backup-first through
`python -m scripts.upgrade_db --db <path>`; see `docs/upgrade.md`.
