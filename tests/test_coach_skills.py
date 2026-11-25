from coach.skills import SKILLS, compose_skill_prompt, skills_for_workflow
from coach.skills.endurance_planning import ENDURANCE_PLANNING_SKILL


def test_all_coaching_skills_are_registered_with_expected_workflows():
    assert {skill.id for skill in SKILLS} == {
        "endurance_planning", "athlete_assessment", "plan_adaptation",
        "race_preparation", "activity_review", "gym_session_guidance",
    }
    assert ENDURANCE_PLANNING_SKILL.id == "endurance_planning"
    assert ENDURANCE_PLANNING_SKILL.workflows == ("weekly_plan",)
    weekly = skills_for_workflow("weekly_plan", {"running_goal": True})
    assert {skill.id for skill in weekly} == {
        "endurance_planning", "athlete_assessment", "race_preparation",
    }
    assert {skill.id for skill in skills_for_workflow("weekly_plan", {"running_goal": False})} == {
        "endurance_planning", "athlete_assessment",
    }
    assert {skill.id for skill in skills_for_workflow("activity_review")} == {"activity_review"}
    assert {skill.id for skill in skills_for_workflow("plan_change", {"running_goal": True})} == {
        "plan_adaptation",
    }
    assert {skill.id for skill in skills_for_workflow("training_response_extraction")} == {
        "plan_adaptation",
    }
    assert skills_for_workflow("chat") == ()
    assert {skill.id for skill in skills_for_workflow("chat", {"sport": "gym"})} == {
        "gym_session_guidance",
    }


def test_weekly_plan_prompt_adds_skill_without_replacing_response_contract():
    prompt = compose_skill_prompt("Return JSON with summary and reasons.", "weekly_plan")

    assert "Return JSON with summary and reasons." in prompt
    assert "Skill: Endurance planning" in prompt
    assert "110% usual-week limit" in prompt
    assert "proposal for the athlete to review" in prompt


def test_unregistered_workflows_keep_the_base_prompt_unchanged():
    base = "Explain this activity from the supplied facts."

    assert compose_skill_prompt(base, "settings") == base


def test_skill_avoids_unverified_history_and_foreign_load_models():
    guidance = ENDURANCE_PLANNING_SKILL.instructions

    assert "Missing history is uncertainty" in guidance
    assert "TSS/CTL formulas" in guidance
    assert "never an applied plan" in guidance


def test_specialized_skills_are_only_loaded_for_their_workflow_and_context():
    generic_chat = compose_skill_prompt("Base", "chat")
    gym_chat = compose_skill_prompt("Base", "chat", {"sport": "gym"})
    plan_without_goal = compose_skill_prompt("Base", "weekly_plan", {"running_goal": False})

    assert "Gym session guidance" not in generic_chat
    assert "Gym session guidance" in gym_chat
    assert "Race preparation" not in plan_without_goal
