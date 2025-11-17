from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.main import WINDOW_DAYS


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


@pytest.mark.usefixtures("clean_database")
def test_rollup_math_and_status(client):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    user_id = "test-user"
    ingest_headers = {"Authorization": "Bearer test-ingest-token"}

    sessions = [
        # day offset, duration seconds, sentiment score
        (2, 90, 0.62),   # 1.5 minutes -> 2
        (1, 119, 0.58),  # 1.98 minutes -> 2
        (0, 180, 0.39),  # current day, recent, tone -> negative
    ]

    for offset, duration, sentiment in sessions:
        started_at = (now - timedelta(days=offset)).replace(hour=15, minute=0, second=0)
        payload = {
            "session_id": f"{user_id}-{offset}",
            "user_external_id": user_id,
            "started_at": _iso(started_at),
            "duration_seconds": duration,
            "sentiment_score": sentiment,
        }
        response = client.post("/internal/ingest/session_summary", json=payload, headers=ingest_headers)
        assert response.status_code == 200, response.text
        assert response.json()["status"] in {"ok", "duplicate"}

    dashboard_headers = {"Authorization": "Bearer dash-token"}
    resp = client.get(f"/api/dashboard/{user_id}", headers=dashboard_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["streak"]["days"] == 3
    assert data["toneTrend"]["current"] == "negative"

    daily_activity = data["streak"]["dailyActivity"]
    daily_durations = data["avgDuration"]["dailyDurations"]
    daily_sentiment = data["toneTrend"]["dailySentiment"]

    assert len(daily_activity) == WINDOW_DAYS == 7
    assert len(daily_durations) == WINDOW_DAYS
    assert len(daily_sentiment) == WINDOW_DAYS

    start_day = now.date() - timedelta(days=WINDOW_DAYS - 1)

    expected_minutes = {
        (now.date() - timedelta(days=2)): 2,
        (now.date() - timedelta(days=1)): 2,
        now.date(): 3,
    }
    expected_sentiments = {
        (now.date() - timedelta(days=2)): Decimal("0.62"),
        (now.date() - timedelta(days=1)): Decimal("0.58"),
        now.date(): Decimal("0.39"),
    }

    for idx, day in enumerate((start_day + timedelta(days=i) for i in range(WINDOW_DAYS))):
        if day in expected_minutes:
            assert daily_activity[idx] is True
            assert daily_durations[idx] == expected_minutes[day]
            assert daily_sentiment[idx] == float(expected_sentiments[day])
        else:
            assert daily_activity[idx] is False
            assert daily_durations[idx] == 0
            assert daily_sentiment[idx] is None

    assert data["avgDuration"]["minutes"] == 2

    last_session = data["lastSession"]
    assert last_session["timestamp"] is not None
    assert "status" not in last_session



def test_dashboard_returns_empty_rollup_for_unknown_user(client):
    resp = client.get(
        "/api/dashboard/new-user",
        headers={"Authorization": "Bearer admin-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["streak"]["dailyActivity"] == [False] * WINDOW_DAYS
    assert data["avgDuration"]["dailyDurations"] == [0] * WINDOW_DAYS
    assert data["toneTrend"]["dailySentiment"] == [None] * WINDOW_DAYS
    assert data["toneTrend"]["current"] == "neutral"
    assert data["streak"]["days"] == 0
    assert data["lastSession"]["timestamp"] is None
    assert "status" not in data["lastSession"]
