"""Use repeated athlete feedback to inform safe, reviewable plan changes."""

from coach.skills.types import CoachSkill

PLAN_ADAPTATION_SKILL = CoachSkill(
    id="plan_adaptation",
    name="Plan adaptation",
    workflows=("plan_change", "training_response_extraction"),
    instructions=(
        "Compare planned and completed sessions only where the supplied records link them. "
        "Use repeated observations on distinct dates, effort ratings, and next-day recovery "
        "when present. A single missed, shortened, or difficult session is not a durable pattern. "
        "Separate athlete-stated preferences from measured outcomes; never infer motivation, "
        "injury, or a medical cause. For a direct plan request, preserve its intent where safe "
        "and explain the concrete trade-off from supplied facts. For training-response review, "
        "suggest a memory or adjustment only through the existing athlete-review flow. Never "
        "apply a plan change, weaken a code safety rule, or silently retire an existing memory."
    ),
)
