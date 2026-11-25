"""Evidence-bounded assessment of current training form."""

from coach.skills.types import CoachSkill

ATHLETE_ASSESSMENT_SKILL = CoachSkill(
    id="athlete_assessment",
    name="Athlete assessment",
    workflows=("weekly_plan",),
    instructions=(
        "Describe current form separately from long-term athletic foundation. Use supplied "
        "training consistency, sport-specific recent activity, session duration, effort ratings, "
        "recovery, and goal facts. Do not infer race history, years of experience, injury, or "
        "fitness in another sport. Treat missing or sparse records as unknown, not as beginner "
        "status. Distinguish measured data from athlete preferences. When evidence is mixed, say "
        "what is uncertain and keep the explanation conservative. Do not invent a limiter or "
        "claim a cause for performance."
    ),
)
