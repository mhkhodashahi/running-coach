"""Provider-neutral coaching skills loaded by the workflows that need them."""

from __future__ import annotations

from coach.skills.activity_review import ACTIVITY_REVIEW_SKILL
from coach.skills.athlete_assessment import ATHLETE_ASSESSMENT_SKILL
from coach.skills.endurance_planning import ENDURANCE_PLANNING_SKILL
from coach.skills.gym_session_guidance import GYM_SESSION_GUIDANCE_SKILL
from coach.skills.plan_adaptation import PLAN_ADAPTATION_SKILL
from coach.skills.race_preparation import RACE_PREPARATION_SKILL
from coach.skills.types import CoachSkill

SKILLS: tuple[CoachSkill, ...] = (
    ATHLETE_ASSESSMENT_SKILL,
    ENDURANCE_PLANNING_SKILL,
    PLAN_ADAPTATION_SKILL,
    RACE_PREPARATION_SKILL,
    ACTIVITY_REVIEW_SKILL,
    GYM_SESSION_GUIDANCE_SKILL,
)


def skills_for_workflow(workflow: str, context: dict[str, str | bool] | None = None
                        ) -> tuple[CoachSkill, ...]:
    """Return playbooks scoped to a workflow and any required context."""
    context = context or {}
    return tuple(
        skill for skill in SKILLS
        if workflow in skill.workflows and
        all(context.get(key) == expected for key, expected in skill.required_context)
    )


def compose_skill_prompt(base_prompt: str, workflow: str,
                         context: dict[str, str | bool] | None = None) -> str:
    """Append only the playbooks registered for this specific workflow."""
    skills = skills_for_workflow(workflow, context)
    if not skills:
        return base_prompt
    blocks = "\n\n".join(f"## Skill: {skill.name}\n{skill.instructions}" for skill in skills)
    return f"{base_prompt}\n\n# Applicable coaching skills\n{blocks}"
