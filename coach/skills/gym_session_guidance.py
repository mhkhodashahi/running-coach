"""Bounded guidance for questions about gym sessions and strength workouts."""

from coach.skills.types import CoachSkill

GYM_SESSION_GUIDANCE_SKILL = CoachSkill(
    id="gym_session_guidance",
    name="Gym session guidance",
    workflows=("chat",),
    required_context=(("sport", "gym"),),
    instructions=(
        "Apply this guidance only to a supplied gym activity or planned gym workout. Ground "
        "comments in its stored title, exercise list, rounds, duration, effort rating, and "
        "available HR/load facts. Do not invent exercises, equipment, sets, loads in kilograms, "
        "technique observations, or muscle soreness. Do not infer injury or diagnose. If the "
        "workout details are absent, say so and offer general, non-medical recovery guidance "
        "without pretending to know what the athlete performed. Changes to a planned workout "
        "must go through the proposal flow and athlete approval."
    ),
)
