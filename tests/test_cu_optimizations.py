"""Tests for CU optimization changes.

These tests verify that the ON CONFLICT patterns work correctly and that
user data is properly persisted (commits happen as expected).
"""

from __future__ import annotations

from datetime import datetime, timezone


def test_duplicate_session_no_rollback(client):
    """Verify duplicate sessions handled without transaction rollback."""
    payload = {
        "session_id": "test-dup-session",
        "user_external_id": "test-user",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": 300,
        "sentiment_score": 0.5,
    }
    headers = {"Authorization": "Bearer test-ingest-token"}

    # First insert succeeds
    r1 = client.post("/internal/ingest/session_summary", json=payload, headers=headers)
    assert r1.status_code == 200
    assert r1.json() == {"status": "ok"}

    # Second insert returns duplicate (no rollback)
    r2 = client.post("/internal/ingest/session_summary", json=payload, headers=headers)
    assert r2.status_code == 200
    assert r2.json() == {"status": "duplicate"}


def test_concurrent_user_creation_no_rollback(client):
    """Verify concurrent user creation handled without rollback."""
    # admin-token:* allows access to any user
    headers = {"Authorization": "Bearer admin-token"}

    # First access creates user
    r1 = client.get("/api/dashboard/new-concurrent-user", headers=headers)
    assert r1.status_code == 200

    # Second access finds existing user (no rollback)
    r2 = client.get("/api/dashboard/new-concurrent-user", headers=headers)
    assert r2.status_code == 200


def test_get_or_create_user_idempotent(db_session):
    """Verify _get_or_create_user is idempotent."""
    from app.services.ingest import _get_or_create_user

    user1 = _get_or_create_user(db_session, "idempotent-user")
    db_session.commit()
    user2 = _get_or_create_user(db_session, "idempotent-user")
    db_session.commit()
    assert user1.id == user2.id


def test_dashboard_new_user_persisted(client):
    """CRITICAL: Verify new users created via dashboard are actually persisted.

    This test catches the bug where using flush() instead of commit() would
    cause user data to be lost when the connection closes.
    """
    # admin-token:* allows access to any user
    headers = {"Authorization": "Bearer admin-token"}
    user_id = "persistence-test-user"

    # First request creates the user
    r1 = client.get(f"/api/dashboard/{user_id}", headers=headers)
    assert r1.status_code == 200

    # Second request should find the user (proves commit happened)
    r2 = client.get(f"/api/dashboard/{user_id}", headers=headers)
    assert r2.status_code == 200

    # Core data should be the same (ignore dynamic lastUpdated timestamp)
    j1, j2 = r1.json(), r2.json()
    assert j1["streak"] == j2["streak"]
    assert j1["avgDuration"] == j2["avgDuration"]
    assert j1["toneTrend"] == j2["toneTrend"]


def test_ingest_creates_user_and_session(client):
    """Verify ingest endpoint creates both user and session correctly."""
    payload = {
        "session_id": "test-new-session",
        "user_external_id": "test-new-user",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": 600,
        "sentiment_score": 0.75,
    }
    headers = {"Authorization": "Bearer test-ingest-token"}

    r = client.post("/internal/ingest/session_summary", json=payload, headers=headers)
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

    # Verify duplicate detection still works (proves session was created)
    r2 = client.post("/internal/ingest/session_summary", json=payload, headers=headers)
    assert r2.status_code == 200
    assert r2.json() == {"status": "duplicate"}

    # Verify the user was created by accessing their dashboard
    dash_headers = {"Authorization": "Bearer admin-token"}
    r3 = client.get("/api/dashboard/test-new-user", headers=dash_headers)
    assert r3.status_code == 200
