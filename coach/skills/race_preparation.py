"""Race-aware context for the existing code-built training phases."""

from coach.skills.types import CoachSkill

RACE_PREPARATION_SKILL = CoachSkill(
    id="race_preparation",
    name="Race preparation",
    workflows=("weekly_plan",),
    required_context=(("running_goal", True),),
    instructions=(
        "Use only the supplied active running goal, target date, distance, goal phase, and "
        "measured pace facts. Relate this week's key session to the stated event distance and "
        "phase when those facts support it. Do not invent race pace, course conditions, race "
        "history, or a finish-time forecast. Do not add a race-day workout or nutrition advice "
        "to a weekly proposal. In sharpen or taper phases, explain only the sessions and reduced "
        "work already present in the code-built proposal; never add intensity or volume. If the "
        "goal date or useful performance data is missing, describe the plan as goal-aware only "
        "to the extent supported and state the limitation."
    ),
)
