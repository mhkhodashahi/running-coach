# Coach Opinion JSON v2: Pre-implementation Status

This document records the milestone 3 inspection and blocker. Despite its
filename, it does not describe implementation of milestone 4.

## Status

Blocked pending the exact v2 contract. The inspected root `AGENTS.md` contains
the current stack but not the requested "Coach opinion JSON" section, legacy
mapping table, or coach-voice instructions. `docs/PLAN.md` also records those
sections as missing.

Required next input: add those sections to `AGENTS.md` or supply their complete
text. The v2 fields, strict enums, nested structures and legacy mappings must
not be invented when the task requires an exact match.

No application code or databases were changed for milestone 3. No migrations,
tests or live provider calls were run for this request. No real v2 opinion was
generated. This document is a status record, not a completion report.

The preceding milestone 2 follow-up was interrupted before edits and remains
pending: excluded sports and recommendation candidates, expanded comparison
fields, and renaming/redacting the milestone 2 results document.

## Current Response Schema

Source: `llm/schemas.py`.

```python
class ActivityCoachInsightSchema(BaseModel):
    overall_assessment: str = Field(default="")
    what_was_good: list[str] = Field(default_factory=list)
    mistakes_or_inefficiencies: list[str] = Field(default_factory=list)
    pacing_analysis: str = Field(default="")
    aerobic_efficiency_analysis: str = Field(default="")
    recovery_analysis: str = Field(default="")
    mental_performance_insights: str = Field(default="")
    training_recommendations: list[str] = Field(default_factory=list)
    brutally_honest_conclusion: str = Field(default="")
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=100)
```

## Current Activity Prompt

The per-activity prompt builder is
`services/activity_coaching_service.py:build_activity_coaching_prompt`, not
`services/coaching_prompts.py`. It prepends `ELITE_ENDURANCE_COACH_CONTEXT`
from `services/coaching_prompts.py`, followed by the text below.

The shared prefix contains hard-coded athlete details and custom HR zones.
Those private details are not reproduced here and must not become assumed
facts in the new prompt.

```text
# Per-Workout Analysis Task
Analyze exactly one workout using the supplied athlete profile, active goal, selected activity, recent training context, recovery metrics, lap data, and stream summaries.

# Running Memory
Use the running_memory block for durable coaching context. Prefer the selected activity and latest metrics when they conflict with older notes.

# Context Engineering
First decide what kind of workout this most likely was from selected_activity, notes, pace, HR, training effect, lap pattern, and stream_analysis. Then judge whether the execution matched that likely purpose. Use context_engineering.analysis_frame, context_engineering.data_quality, and context_engineering.key_questions to focus your reasoning. Prioritize direct evidence from selected_activity, stream_analysis, lap_analysis, same_day_or_latest_recovery, recent_running_context, and training_snapshot in that order.

You must analyze every workout deeply and give honest feedback, strengths, mistakes, pacing analysis, aerobic efficiency analysis, recovery analysis, mental/performance insights, and training recommendations.

Use the athlete_profile values from the user prompt as the source of truth for age, sex, weight, max HR, training availability, and injury notes. Do not use generic athlete assumptions when profile data is present.

# Output Contract
Return strict JSON only with keys: overall_assessment, what_was_good, mistakes_or_inefficiencies, pacing_analysis, aerobic_efficiency_analysis, recovery_analysis, mental_performance_insights, training_recommendations, brutally_honest_conclusion, evidence, confidence.
what_was_good, mistakes_or_inefficiencies, training_recommendations, and evidence must be arrays of strings. confidence must be 0-100.

# Coaching Rules
- Do not blindly praise the workout.
- Do not just repeat Garmin metrics; interpret them like a coach.
- If the run looks too hard for an easy day, say so directly.
- If the athlete controlled the workout well, reward that discipline.
- Use the custom HR zones in the context, not Garmin default zones.
- If running mechanics data is missing, say it is unavailable instead of inventing it.
- Be specific about what to do in the next run or next 24-48 hours.
- Keep medical language conservative and do not diagnose.
```

The current user prompt is constructed as:

```python
user_prompt = f"{running_memory_block(running_memory)}\n{json.dumps(context, default=_json_default, indent=2)}"
```

## Proposed Files to Change

These are planned changes, not implemented changes:

- `llm/schemas.py`
- `llm/openai_client.py`
- `llm/ollama_client.py`
- `services/activity_coaching_service.py`
- `services/coaching_prompts.py`
- `services/llm_workflow.py`
- New `services/coach_opinion.py` for legacy reading and evidence validation
- `db/models.py`
- `db/repository.py`
- New `db/migrations/versions/0004_coach_opinion_v2.py`
- `app/pages/8_Activity_Detail.py`
- `tests/test_activity_coaching_service.py`
- `tests/test_migrations.py`
- Focused legacy-reader, evidence-validation and provider tests as needed
- `docs/upgrade.md`

## Verification Still Required

After the contract is supplied and implementation is complete:

- Validate v2 schema, exact legacy mapping, structured provider requests,
  bounded retries and numeric evidence checks using mocked providers.
- Verify explicit regeneration archives the existing opinion in the same
  transaction and that failures retain the existing opinion.
- Test planned intent in prompts and legacy rendering without row mutation.
- Apply migration 0004 only to a pre-upgrade copy through the backup-first
  upgrade command and run preservation checks.
- Run Ruff, compileall and the complete pytest suite.
- Generate the requested real latest-run v2 opinion separately from tests,
  and report the JSON and any live-provider limitations honestly.
