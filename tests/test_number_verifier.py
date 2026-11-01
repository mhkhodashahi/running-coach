"""Verify-after claims use invented facts only."""

import pytest

from services.number_verifier import derive_difference, derive_sum, extract_numbers, verify_numbers


def fact(name, display):
    return {"id": name, "metric": name, "display": display, "source": f"fixture.{name}"}


@pytest.mark.parametrize("display,claim", [
    ("6:45 /km", "Pace was 6:45 on the first full kilometre."),
    ("1h 23m", "The session lasted 1h 23m."),
    ("27:16", "I ran for 27:16."),
    ("128 bpm", "Heart rate was 128 bpm."),
    ("72% of usual", "Load was 72%."),
    ("4.0 km", "Distance was 4 km."),
    ("4.56 m", "The partial lap was 4.6 m."),
    ("164 spm", "Cadence was 164 spm."),
    ("61 ms", "HRV was 61 ms."),
    ("2.4", "Aerobic effect was 2.4."),
    ("8/10", "Effort was 8/10."),
    ("Wed 23 Sep", "This happened on 23 Sep."),
    ("06:36", "I started at 06:36."),
])
def test_supported_formats(display, claim):
    result = verify_numbers([fact("MEASURE", display)], claim)
    assert result.unmatched == ()
    assert result.verified == result.claims == 1


def test_unit_mismatch_and_unmatched_claim_are_rejected():
    result = verify_numbers([fact("HR", "128 bpm")], "I reached 128 spm and 149 bpm.")
    assert result.verified == 0
    assert result.unmatched == ("128 spm", "149 bpm")


def test_derived_difference_is_code_owned_and_can_be_verified():
    left, right = fact("TODAY", "54 ms"), fact("USUAL", "61 ms")
    delta = derive_difference(left, right, "DELTA")
    assert delta["display"] == "-7 ms"
    assert verify_numbers([left, right, delta], "HRV is 7 ms below usual.").unmatched == ()


def test_derived_sum_is_code_owned_and_can_be_verified():
    total = derive_sum(fact("FIRST", "20 min"), fact("SECOND", "10 min"), "TOTAL")
    assert total["display"] == "30 min"
    assert verify_numbers([total], "Run 30 min.").unmatched == ()


def test_full_date_cannot_be_verified_from_a_yearless_fact():
    assert verify_numbers([fact("DAY", "Wed 23 Sep")], "On 2026-09-23").unmatched == ("2026-09-23",)


def test_composite_claims_and_zone_labels_are_not_split():
    claims = extract_numbers("Z1-Z2 held 90%. The 7h 42m night ended at 06:36.")
    assert [item.text for item in claims] == ["90%", "7h 42m", "06:36"]
