"""Custom HR zones are optional configuration, not tracked athlete defaults."""

import pytest

from config import _parse_hr_zones


def test_hr_zones_empty_or_valid_json():
    assert _parse_hr_zones("") == ()
    assert _parse_hr_zones('''[{"name":"Invented Easy","lower_bpm":100,"upper_bpm":130},
                              {"name":"Invented Hard","lower_bpm":131,"upper_bpm":null}]''') == (
        ("Invented Easy", 100, 130), ("Invented Hard", 131, None),
    )


@pytest.mark.parametrize("raw", ('{}', '[{"name":"x","lower_bpm":120,"upper_bpm":100}]',
                                      '[{"name":"x","lower_bpm":true,"upper_bpm":null}]', 'not-json'))
def test_hr_zones_invalid_config_fails_clearly(raw):
    with pytest.raises(ValueError, match="HR_ZONES"):
        _parse_hr_zones(raw)
