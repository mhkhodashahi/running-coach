from coach.guardrails import (
    GuardrailContext,
    diagnosis_sentences,
    enforce_guardrails,
    guardrail_errors,
    plan_change_question,
)


def test_illness_blocks_hard_advice_and_replaces_it_with_rest():
    context = GuardrailContext(True, 1.0, False)
    assert guardrail_errors("Run intervals tomorrow.", context)
    assert "see a doctor" in enforce_guardrails("Run intervals tomorrow.", context)


def test_high_load_blocks_hard_but_allows_easy():
    context = GuardrailContext(False, 1.6, False)
    assert guardrail_errors("Do a tempo session.", context)
    assert not guardrail_errors("Keep it easy or rest.", context)
    assert "easy or rest" in enforce_guardrails("Do a tempo session.", context)


def test_diagnosis_is_removed_and_plan_request_remains_a_proposal():
    context = GuardrailContext(False, None, False)
    assert diagnosis_sentences("You have anemia. Take it easy.") == ("You have anemia.",)
    assert enforce_guardrails("You have anemia. Take it easy.", context) == "Take it easy."
    assert plan_change_question("Change my plan so Saturday is a rest day")
    proposal = enforce_guardrails("I changed your plan.", GuardrailContext(False, None, True))
    assert "proposals" in proposal and "cannot apply" in proposal
