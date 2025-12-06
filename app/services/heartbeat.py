from __future__ import annotations

import random
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import DeviceHeartbeatEvent, DeviceHeartbeatSummary, DeviceLatestHeartbeat
from app.schemas import HeartbeatRequest, HeartbeatStatus

STALE_MINUTES = 20
RETENTION_DAYS = 7
RAW_RETENTION_HOURS = 2  # Keep raw events for 2 hours before compacting
CLEANUP_PROBABILITY = 0.01  # 1% chance per heartbeat request


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
            boot_time=heartbeat.boot_time,
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
        existing.boot_time = heartbeat.boot_time
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
            bootTime=_as_utc(hb.boot_time),
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
    if agent_ok and latency is not None and latency < 500:
        return "healthy"
    return "degraded"


def cleanup_old_heartbeat_events(db: Session, retention_days: int = RETENTION_DAYS) -> int:
    """
    Delete heartbeat events older than retention_days.
    Returns the number of rows deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = db.execute(
        delete(DeviceHeartbeatEvent).where(DeviceHeartbeatEvent.server_received_at < cutoff)
    )
    return result.rowcount


def maybe_cleanup_old_events(db: Session) -> int | None:
    """
    Probabilistically run cleanup and compaction (1% chance) to avoid impacting every request.
    Returns rows deleted if cleanup ran, None otherwise.
    """
    if random.random() < CLEANUP_PROBABILITY:
        compact_heartbeat_events(db)
        return cleanup_old_heartbeat_events(db)
    return None


def compact_heartbeat_events(db: Session) -> int:
    """
    Aggregate raw heartbeat events older than RAW_RETENTION_HOURS into hourly summaries.
    Returns the number of events compacted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RAW_RETENTION_HOURS)

    # Get all raw events older than cutoff, grouped by device and hour
    old_events = db.scalars(
        select(DeviceHeartbeatEvent)
        .where(DeviceHeartbeatEvent.server_received_at < cutoff)
        .order_by(DeviceHeartbeatEvent.device_id, DeviceHeartbeatEvent.server_received_at)
    ).all()

    if not old_events:
        return 0

    # Group events by device_id and hour bucket
    buckets: dict[tuple[str, datetime], list[DeviceHeartbeatEvent]] = {}
    for event in old_events:
        hour_bucket = event.server_received_at.replace(minute=0, second=0, microsecond=0)
        key = (event.device_id, hour_bucket)
        if key not in buckets:
            buckets[key] = []
        buckets[key].append(event)

    # Aggregate each bucket into a summary
    for (device_id, hour_bucket), events in buckets.items():
        latencies = []
        connectivities = []
        ok_count = 0
        degraded_count = 0

        for event in events:
            payload = event.raw_payload or {}
            network = payload.get("network", {})
            latency = network.get("latency_ms")
            if latency is not None:
                latencies.append(latency)
            connectivities.append(payload.get("connectivity", "unknown"))
            agent_status = payload.get("agent_status", "")
            if agent_status == "ok":
                ok_count += 1
            else:
                degraded_count += 1

        # Calculate aggregates
        avg_latency = int(sum(latencies) / len(latencies)) if latencies else None
        min_latency = min(latencies) if latencies else None
        max_latency = max(latencies) if latencies else None
        connectivity_mode = Counter(connectivities).most_common(1)[0][0] if connectivities else "unknown"

        # Upsert summary
        existing = db.get(DeviceHeartbeatSummary, (device_id, hour_bucket))
        if existing:
            existing.heartbeat_count += len(events)
            if avg_latency is not None:
                if existing.avg_latency_ms is not None:
                    # Weighted average
                    total = (existing.avg_latency_ms * (existing.heartbeat_count - len(events))) + (avg_latency * len(events))
                    existing.avg_latency_ms = int(total / existing.heartbeat_count)
                else:
                    existing.avg_latency_ms = avg_latency
            if min_latency is not None:
                existing.min_latency_ms = min(existing.min_latency_ms or min_latency, min_latency)
            if max_latency is not None:
                existing.max_latency_ms = max(existing.max_latency_ms or max_latency, max_latency)
            existing.agent_status_ok_count += ok_count
            existing.agent_status_degraded_count += degraded_count
        else:
            db.add(DeviceHeartbeatSummary(
                device_id=device_id,
                hour_bucket=hour_bucket,
                heartbeat_count=len(events),
                avg_latency_ms=avg_latency,
                min_latency_ms=min_latency,
                max_latency_ms=max_latency,
                connectivity_mode=connectivity_mode,
                agent_status_ok_count=ok_count,
                agent_status_degraded_count=degraded_count,
            ))

    # Delete compacted raw events
    event_ids = [e.id for e in old_events]
    if event_ids:
        db.execute(delete(DeviceHeartbeatEvent).where(DeviceHeartbeatEvent.id.in_(event_ids)))

    return len(old_events)
