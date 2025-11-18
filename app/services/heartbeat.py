from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DeviceHeartbeatEvent, DeviceLatestHeartbeat
from app.schemas import HeartbeatRequest, HeartbeatStatus

STALE_MINUTES = 20


def record_heartbeat(db: Session, heartbeat: HeartbeatRequest) -> DeviceLatestHeartbeat:
    """
    Upsert the latest heartbeat for a device, recording the raw payload for history.
    """
    now = datetime.now(timezone.utc)
    existing = db.get(DeviceLatestHeartbeat, heartbeat.device_id)
    if existing is None:
        existing = DeviceLatestHeartbeat(
            device_id=heartbeat.device_id,
            agent_version=heartbeat.agent_version,
            connectivity=heartbeat.connectivity,
            agent_status=heartbeat.agent_status,
            last_session_at=heartbeat.last_session_at,
            signal_rssi=heartbeat.network.signal_rssi,
            latency_ms=heartbeat.network.latency_ms,
            server_received_at=now,
        )
        db.add(existing)
    else:
        existing.agent_version = heartbeat.agent_version
        existing.connectivity = heartbeat.connectivity
        existing.agent_status = heartbeat.agent_status
        existing.last_session_at = heartbeat.last_session_at
        existing.signal_rssi = heartbeat.network.signal_rssi
        existing.latency_ms = heartbeat.network.latency_ms
        existing.server_received_at = now

    db.add(
        DeviceHeartbeatEvent(
            device_id=heartbeat.device_id,
            raw_payload=heartbeat.model_dump(mode="json", exclude_none=True),
            server_received_at=now,
        )
    )
    return existing


def list_heartbeat_statuses(
    db: Session, *, stale_minutes: int = STALE_MINUTES
) -> Tuple[List[HeartbeatStatus], datetime]:
    """
    Return heartbeat status for all devices ordered by recency, marking stale devices as dead.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=stale_minutes)
    records = db.scalars(select(DeviceLatestHeartbeat).order_by(DeviceLatestHeartbeat.server_received_at.desc())).all()

    statuses = [
        HeartbeatStatus(
            deviceId=hb.device_id,
            status=_compute_status(hb, cutoff),
            lastSeen=_as_utc(hb.server_received_at),
            connectivity=hb.connectivity,
            agentVersion=hb.agent_version,
            signalRssi=hb.signal_rssi,
            latencyMs=hb.latency_ms,
            lastSessionAt=_as_utc(hb.last_session_at),
        )
        for hb in records
    ]
    return statuses, now


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _compute_status(hb: DeviceLatestHeartbeat, cutoff: datetime) -> str:
    last_seen = _as_utc(hb.server_received_at)
    if last_seen is None or last_seen < cutoff:
        return "dead"

    agent_ok = hb.agent_status == "ok"
    latency = hb.latency_ms
    if agent_ok and latency is not None and latency < 300:
        return "healthy"
    return "degraded"
