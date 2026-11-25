"""Structured interpretation of a completed activity's supplied facts."""

from coach.skills.types import CoachSkill

ACTIVITY_REVIEW_SKILL = CoachSkill(
    id="activity_review",
    name="Activity review",
    workflows=("activity_review",),
    instructions=(
        "Review the completed session against its planned intent when present, otherwise its "
        "code-detected intent. Use lap and stream facts to discuss pacing, HR response, aerobic "
        "stimulus, and recovery only when available. Separate recording-quality notes from the "
        "athlete's execution. Compare with prior sessions only when supplied. Do not turn one "
        "session into a trend, infer a physiological cause, diagnose, or judge an easy/recovery "
        "session against a race goal. Every numeric statement must remain verifiable from the "
        "provided facts; code builds evidence after generation. Recommendations are optional "
        "proposals, never direct plan edits."
    ),
)
