from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.main import _calculate_streak_days, _is_unique_violation, _to_optional_float
from app.services import ingest as ingest_module


def _integrity_error(message: str, pgcode: str | None = None) -> IntegrityError:
    class DummyOrig:
        def __init__(self, text: str, code: str | None):
            self.pgcode = code
            self._text = text

        def __str__(self) -> str:
            return self._text

    return IntegrityError("INSERT", {}, DummyOrig(message, pgcode))


@pytest.mark.parametrize(
    ("activity", "expected"),
    [
        ([False, False, True], 1),
        ([True, True, True], 3),
        ([True, False, True, True], 2),
        ([False, False, False], 0),
    ],
)
def test_calculate_streak_days(activity, expected):
    assert _calculate_streak_days(activity) == expected


def test_optional_float_rounding_and_none():
    assert _to_optional_float(Decimal("0.6789")) == 0.68
    assert _to_optional_float(None) is None


def test_is_unique_violation_detects_pgcode():
    error = _integrity_error("duplicate key value", pgcode="23505")
    assert _is_unique_violation(error) is True


def test_is_unique_violation_detects_message_keyword():
    error = _integrity_error("UNIQUE constraint failed: sessions.session_id")
    assert _is_unique_violation(error) is True


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, 0),
        (30, 1),
        (90, 2),
        (119, 2),
        (150, 3),
    ],
)
def test_round_minutes_from_seconds(seconds, expected):
    assert ingest_module._round_minutes_from_seconds(seconds) == expected


@pytest.mark.parametrize(
    ("durations", "expected"),
    [
        ([0, 0, 0], 0),
        ([3, 0, 6], 5),
        ([1, 2], 2),
    ],
)
def test_average_nonzero_duration(durations, expected):
    assert ingest_module._average_nonzero_duration(durations) == expected


@pytest.mark.parametrize(
    ("sentiments", "expected"),
    [
        ([Decimal("0.20"), Decimal("0.70")], "positive"),
        ([Decimal("0.70"), Decimal("0.41")], "neutral"),
        ([Decimal("0.90"), Decimal("0.30")], "negative"),
        ([None, None, None], "neutral"),
    ],
)
def test_determine_current_tone(sentiments, expected):
    assert ingest_module._determine_current_tone(sentiments) == expected


def test_average_sentiment_quantizes_half_up():
    sessions = [
        SimpleNamespace(sentiment_score=Decimal("0.62")),
        SimpleNamespace(sentiment_score=Decimal("0.58")),
        SimpleNamespace(sentiment_score=Decimal("0.60")),
    ]
    assert ingest_module._average_sentiment(sessions) == Decimal("0.60")


def test_quantize_score_uses_half_up_rounding():
    assert ingest_module._quantize_score(0.235) == Decimal("0.24")
