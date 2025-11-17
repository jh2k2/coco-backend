from __future__ import annotations

from datetime import datetime, timezone


def test_ingest_duplicate_detection(client):
    payload = {
        "session_id": "duplicate-session",
        "user_external_id": "ingest-user",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": 600,
        "sentiment_score": 0.5,
    }
    headers = {"Authorization": "Bearer test-ingest-token"}

    first = client.post("/internal/ingest/session_summary", json=payload, headers=headers)
    assert first.status_code == 200
    assert first.json() == {"status": "ok"}

    second = client.post("/internal/ingest/session_summary", json=payload, headers=headers)
    assert second.status_code == 200
    assert second.json() == {"status": "duplicate"}
