from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models import DeviceLatestHeartbeat
from app.services.heartbeat import STALE_MINUTES


def test_heartbeat_records_and_lists(client):
    now = datetime.now(timezone.utc)
    payload = _heartbeat_payload(
        device_id="hb-device-1",
        connectivity="wifi",
        agent_status="ok",
        last_session_at=now,
        network_latency=43,
    )
    headers = {"Authorization": "Bearer test-ingest-token"}

    recorded = client.post("/internal/heartbeat", json=payload, headers=headers)
    assert recorded.status_code == 200
    assert recorded.json() == {"status": "ok"}

    listing = client.get("/api/heartbeats", headers={"Authorization": "Bearer admin-token"})
    assert listing.status_code == 200
    body = listing.json()

    assert body["staleThresholdMinutes"] == STALE_MINUTES
    assert len(body["devices"]) == 1
    device = body["devices"][0]
    assert device["deviceId"] == payload["device_id"]
    assert device["connectivity"] == payload["connectivity"]
    assert device["agentVersion"] == payload["agent_version"]
    assert device["signalRssi"] == payload["network"]["signal_rssi"]
    assert device["latencyMs"] == payload["network"]["latency_ms"]
    assert _parse_dt(device["lastSessionAt"]) == _parse_dt(payload["last_session_at"])
    assert device["status"] == "healthy"

    last_seen = _parse_dt(device["lastSeen"])
    assert abs((last_seen - datetime.now(timezone.utc)).total_seconds()) < 5


def test_stale_heartbeat_marked_dead(client):
    payload = _heartbeat_payload(
        device_id="hb-device-2",
        connectivity="lte",
        agent_status="ok",
        last_session_at=None,
        network_latency=None,
    )
    headers = {"Authorization": "Bearer test-ingest-token"}
    client.post("/internal/heartbeat", json=payload, headers=headers)

    stale_timestamp = datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES + 5)
    with SessionLocal() as db:
        hb = db.get(DeviceLatestHeartbeat, payload["device_id"])
        hb.server_received_at = stale_timestamp
        db.commit()

    listing = client.get("/api/heartbeats", headers={"Authorization": "Bearer admin-token"})
    assert listing.status_code == 200
    device = listing.json()["devices"][0]
    assert device["status"] == "dead"
    assert _parse_dt(device["lastSeen"]) < datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES)


def test_degraded_when_audio_or_scheduler_fail(client):
    payload = _heartbeat_payload(
        device_id="hb-device-3",
        connectivity="wifi",
        agent_status="ok",
        last_session_at=None,
        network_latency=500,
    )
    headers = {"Authorization": "Bearer test-ingest-token"}
    client.post("/internal/heartbeat", json=payload, headers=headers)

    listing = client.get("/api/heartbeats", headers={"Authorization": "Bearer admin-token"})
    device = listing.json()["devices"][0]
    assert device["status"] == "degraded"


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _heartbeat_payload(
    *,
    device_id: str,
    connectivity: str,
    agent_status: str,
    last_session_at: datetime | None,
    network_latency: int | None,
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "device_id": device_id,
        "agent_version": "1.2.3",
        "connectivity": connectivity,
        "network": {
            "interface": "wlan0",
            "ip": "192.168.0.42",
            "signal_rssi": -62,
            "latency_ms": network_latency,
        },
        "agent_status": agent_status,
        "last_session_at": None if last_session_at is None else last_session_at.isoformat(),
        "timestamp": now.isoformat(),
    }
