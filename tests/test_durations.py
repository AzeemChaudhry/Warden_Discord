from datetime import timedelta

import pytest

from warden.durations import format_duration, parse_duration


@pytest.mark.parametrize(
    "text, expected",
    [
        ("30", timedelta(minutes=30)),
        ("90s", timedelta(seconds=90)),
        ("10m", timedelta(minutes=10)),
        ("1h30m", timedelta(hours=1, minutes=30)),
        ("1d 12h", timedelta(days=1, hours=12)),
        ("2W", timedelta(weeks=2)),
    ],
)
def test_parse(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "10x", "m10", "0m", "10m abc"])
def test_parse_rejects(text):
    with pytest.raises(ValueError):
        parse_duration(text)


def test_format():
    assert format_duration(timedelta(days=1, hours=2, seconds=5)) == "1d 2h 5s"
    assert format_duration(timedelta(0)) == "0s"
