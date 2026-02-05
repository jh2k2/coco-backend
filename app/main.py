from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List

import boto3
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func as sa_func, select
from sqlalchemy.orm import Session

from .db_utils import dialect_insert

from .auth import authorize_dashboard_access, require_admin_token, require_service_token
from .config import get_settings
from .database import Base, engine
from .dependencies import get_db
from .models import AudioRecording, DashboardRollup, DeviceHeartbeatSummary, Session as SessionModel, User
from .schemas import (
    AvgDuration,
    CommandCreateRequest,
    CommandResponse,
    CommandStatusUpdate,
    DashboardResponse,
    DeviceUptimeResponse,
    DeviceUptimeStats,
    DeviceUserInfo,
    DeviceUsersResponse,
    HeartbeatRequest,
    HeartbeatSummaryResponse,
    LastSession,
    LogSnapshotListResponse,
    LogSnapshotResponse,
    LogUploadRequest,
    PendingCommandResponse,
    PendingCommandsResponse,
    SessionSummaryIngestRequest,
    Streak,
    ToneTrend,
)
from .services.commands import (
    get_latest_log,
    get_pending_command,
    queue_command,
    save_log_snapshot,
    update_command_status,
)
from .services.heartbeat import STALE_MINUTES, list_heartbeat_statuses, maybe_cleanup_old_events, record_heartbeat
from .services.ingest import ingest_session_summary

logger = logging.getLogger("coco.api")
logging.basicConfig(level=logging.INFO)

settings = get_settings()
WINDOW_DAYS = settings.rollup_window_days

# R2 client for audio storage
r2_client = None
R2_BUCKET = os.environ.get("R2_BUCKET_NAME", "coco-audio-recordings")

def get_r2_client():
    global r2_client
    if r2_client is None and os.environ.get("R2_ENDPOINT"):
        r2_client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("R2_ENDPOINT"),
            aws_access_key_id=os.environ.get("R2_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("R2_SECRET_ACCESS_KEY"),
        )
    return r2_client

docs_enabled = settings.environment != "production"

app = FastAPI(
    title="Family Engagement Dashboard API",
    version="0.1.0",
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
    openapi_url="/openapi.json" if docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.dashboard_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "HEAD"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_logger(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - start_time) * 1000
        entry = {
            "event": "http_request",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": 500,
            "duration_ms": round(duration_ms, 2),
            "user_id": getattr(request.state, "user_id", None),
        }
        logger.exception(json.dumps(entry))
        raise

    duration_ms = (time.perf_counter() - start_time) * 1000
    response.headers["X-Request-ID"] = request_id

    entry = {
        "event": "http_request",
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "duration_ms": round(duration_ms, 2),
        "user_id": getattr(request.state, "user_id", None),
    }
    logger.info(json.dumps(entry))
    return response

# Ensure the schema exists automatically only in non-production environments.
if settings.environment in {"development", "test"}:
    Base.metadata.create_all(bind=engine)


@app.get("/healthz", status_code=status.HTTP_200_OK)
def healthz(db: Session = Depends(get_db)) -> Dict[str, str]:
    db.execute(select(1))
    return {"status": "ok"}


@app.get("/readyz", status_code=status.HTTP_200_OK)
def readyz(db: Session = Depends(get_db)) -> Dict[str, int | str]:
    db.execute(select(User.id).limit(1))
    return {"status": "ready", "windowDays": WINDOW_DAYS}


@app.head("/readyz", status_code=status.HTTP_200_OK)
def readyz_head(db: Session = Depends(get_db)) -> Response:
    readyz(db)  # Reuse readiness checks without returning a JSON payload.
    return Response(status_code=status.HTTP_200_OK)


@app.post("/internal/heartbeat", status_code=status.HTTP_200_OK)
def record_device_heartbeat(
    payload: HeartbeatRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Dict[str, str]:
    require_service_token(authorization)
    hb = record_heartbeat(db, payload)

    # Probabilistic cleanup of old heartbeat events (1% chance)
    deleted_count = maybe_cleanup_old_events(db)

    db.commit()
    heartbeat_age_seconds: float | None = None
    if payload.timestamp is not None:
        heartbeat_age_seconds = max(
            0.0,
            round((hb.server_received_at - payload.timestamp).total_seconds(), 3),
        )
    hb_status = (
        "dead"
        if hb.server_received_at < datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES)
        else ("healthy" if hb.agent_status == "ok" and hb.latency_ms is not None and hb.latency_ms < 500 else "degraded")
    )

    logger.info(
        json.dumps(
            {
                "event": "heartbeat_ingested",
                "device_id": payload.device_id,
                "agent_version": payload.agent_version,
                "heartbeat_age_seconds": heartbeat_age_seconds,
                "status": hb_status,
            }
        )
    )

    if deleted_count is not None and deleted_count > 0:
        logger.info(
            json.dumps(
                {
                    "event": "heartbeat_events_cleanup",
                    "deleted_count": deleted_count,
                }
            )
        )

    return {"status": "ok"}


@app.get("/api/heartbeats", response_model=HeartbeatSummaryResponse, status_code=status.HTTP_200_OK)
def get_device_heartbeats(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> HeartbeatSummaryResponse:
    authorize_dashboard_access("*", authorization)
    devices, as_of = list_heartbeat_statuses(db, stale_minutes=STALE_MINUTES)
    return HeartbeatSummaryResponse(devices=devices, asOf=as_of, staleThresholdMinutes=STALE_MINUTES)


@app.post("/internal/ingest/session_summary", status_code=status.HTTP_200_OK)
def ingest_session_summary_endpoint(
    payload: SessionSummaryIngestRequest,
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
) -> Dict[str, str]:
    require_service_token(authorization)
    request.state.user_id = payload.user_external_id
    device_id = x_device_id or payload.device_id
    # ON CONFLICT DO NOTHING handles duplicates atomically without rollbacks
    result = ingest_session_summary(db, payload, device_id=device_id)
    db.commit()
    if result["duplicate"]:
        return {"status": "duplicate"}
    return {"status": "ok"}


@app.get("/api/dashboard/{user_id}", response_model=DashboardResponse, status_code=status.HTTP_200_OK)
def get_dashboard(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> DashboardResponse:
    authorize_dashboard_access(user_id, authorization)
    request.state.user_id = user_id

    user_stmt = select(User).where(User.external_id == user_id).limit(1)
    user = db.execute(user_stmt).scalar_one_or_none()
    if user is None:
        # Use ON CONFLICT DO NOTHING for atomic user creation without rollbacks
        stmt = dialect_insert(db, User).values(
            external_id=user_id
        ).on_conflict_do_nothing(index_elements=['external_id'])
        db.execute(stmt)
        db.commit()  # Must commit - get_db() doesn't auto-commit
        user = db.execute(user_stmt).scalar_one()

    rollup = db.get(DashboardRollup, user.id)
    now = datetime.now(timezone.utc)

    if rollup is None:
        empty_activity = [False] * WINDOW_DAYS
        empty_durations = [0] * WINDOW_DAYS
        empty_sentiment: List[Decimal | None] = [None] * WINDOW_DAYS
        response = _build_dashboard_response(
            daily_activity=empty_activity,
            daily_durations=empty_durations,
            daily_sentiment=empty_sentiment,
            avg_duration_minutes=0,
            current_tone="neutral",
            last_session_at=None,
            now=now,
        )
    else:
        response = _build_dashboard_response(
            daily_activity=list(rollup.daily_activity),
            daily_durations=list(rollup.daily_durations),
            daily_sentiment=list(rollup.daily_sentiment),
            avg_duration_minutes=rollup.avg_duration_minutes,
            current_tone=rollup.current_tone,
            last_session_at=rollup.last_session_at,
            now=now,
        )
    return response


def _build_dashboard_response(
    *,
    daily_activity: List[bool],
    daily_durations: List[int],
    daily_sentiment: List[Decimal | None],
    avg_duration_minutes: int,
    current_tone: str,
    last_session_at: datetime | None,
    now: datetime,
) -> DashboardResponse:
    streak_days = _calculate_streak_days(daily_activity)
    normalized_sentiment = [_to_optional_float(value) for value in daily_sentiment]

    return DashboardResponse(
        lastSession=LastSession(timestamp=last_session_at),
        streak=Streak(days=streak_days, dailyActivity=daily_activity),
        avgDuration=AvgDuration(minutes=avg_duration_minutes, dailyDurations=daily_durations),
        toneTrend=ToneTrend(current=current_tone, dailySentiment=normalized_sentiment),
        lastUpdated=now,
    )


def _calculate_streak_days(daily_activity: List[bool]) -> int:
    streak = 0
    for active in reversed(daily_activity):
        if active:
            streak += 1
        else:
            break
    return streak


def _to_optional_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


# Admin Endpoints


@app.post("/admin/commands", response_model=CommandResponse, status_code=status.HTTP_201_CREATED)
def create_command(
    payload: CommandCreateRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> CommandResponse:
    """Queue a command for a device."""
    require_admin_token(authorization)
    command = queue_command(db, payload.device_id, payload.command.value)
    db.commit()
    logger.info(
        json.dumps(
            {
                "event": "command_queued",
                "command_id": str(command.id),
                "device_id": payload.device_id,
                "command_type": payload.command.value,
            }
        )
    )
    return CommandResponse(
        id=command.id,
        device_id=command.device_id,
        command_type=command.command_type,
        status=command.status,
        created_at=command.created_at,
    )


@app.get("/admin/logs/{device_id}", response_model=LogSnapshotListResponse, status_code=status.HTTP_200_OK)
def get_device_logs(
    device_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> LogSnapshotListResponse:
    """Retrieve the most recent log snapshot for a device."""
    require_admin_token(authorization)
    snapshot = get_latest_log(db, device_id)
    if snapshot is None:
        return LogSnapshotListResponse(snapshot=None)
    return LogSnapshotListResponse(
        snapshot=LogSnapshotResponse(
            id=snapshot.id,
            device_id=snapshot.device_id,
            log_content=snapshot.log_content,
            created_at=snapshot.created_at,
        )
    )


@app.get("/admin/devices/{device_id}/users", response_model=DeviceUsersResponse, status_code=status.HTTP_200_OK)
def get_device_users(
    device_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> DeviceUsersResponse:
    """List all users who have sessions on a specific device."""
    require_admin_token(authorization)

    # Query users with sessions on this device, aggregating session count and last session time
    stmt = (
        select(
            User.external_id,
            sa_func.max(SessionModel.started_at + timedelta(seconds=1) * SessionModel.duration_seconds).label(
                "last_session_at"
            ),
            sa_func.count(SessionModel.id).label("session_count"),
        )
        .join(SessionModel, User.id == SessionModel.user_id)
        .where(SessionModel.device_id == device_id)
        .group_by(User.external_id)
        .order_by(sa_func.max(SessionModel.started_at).desc())
    )

    results = db.execute(stmt).all()

    users = [
        DeviceUserInfo(
            user_external_id=row.external_id,
            last_session_at=row.last_session_at,
            session_count=row.session_count,
        )
        for row in results
    ]

    return DeviceUsersResponse(device_id=device_id, users=users)


@app.get("/admin/devices/uptime", response_model=DeviceUptimeResponse, status_code=status.HTTP_200_OK)
def get_device_uptime_stats(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> DeviceUptimeResponse:
    """Get 7-day uptime statistics for all devices."""
    require_admin_token(authorization)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)

    # Query aggregated uptime stats per device
    stmt = (
        select(
            DeviceHeartbeatSummary.device_id,
            sa_func.sum(DeviceHeartbeatSummary.uptime_seconds).label("total_uptime"),
            sa_func.sum(DeviceHeartbeatSummary.reboot_count).label("total_reboots"),
            sa_func.count(DeviceHeartbeatSummary.hour_bucket).label("hours_tracked"),
        )
        .where(DeviceHeartbeatSummary.hour_bucket >= cutoff)
        .group_by(DeviceHeartbeatSummary.device_id)
        .order_by(DeviceHeartbeatSummary.device_id)
    )

    results = db.execute(stmt).all()

    # Calculate uptime percentage (max possible = 7 days * 24 hours * 3600 seconds)
    max_seconds = 7 * 24 * 3600

    devices = [
        DeviceUptimeStats(
            device_id=row.device_id,
            uptime_pct_7d=round((row.total_uptime or 0) * 100.0 / max_seconds, 2),
            reboots_7d=row.total_reboots or 0,
            total_hours_tracked=row.hours_tracked or 0,
        )
        for row in results
    ]

    return DeviceUptimeResponse(devices=devices, as_of=now)


# Device Endpoints (Internal)


@app.get("/internal/commands/pending", response_model=PendingCommandsResponse, status_code=status.HTTP_200_OK)
def poll_pending_command(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
) -> PendingCommandsResponse:
    """Poll for pending commands. Returns the oldest pending command and marks it as PICKED_UP."""
    require_service_token(authorization)
    if not x_device_id:
        return PendingCommandsResponse(command=None)

    command = get_pending_command(db, x_device_id)
    db.commit()

    if command is None:
        return PendingCommandsResponse(command=None)

    logger.info(
        json.dumps(
            {
                "event": "command_picked_up",
                "command_id": str(command.id),
                "device_id": x_device_id,
                "command_type": command.command_type,
            }
        )
    )
    return PendingCommandsResponse(
        command=PendingCommandResponse(
            id=command.id,
            command_type=command.command_type,
            payload=command.payload,
            created_at=command.created_at,
        )
    )


@app.post("/internal/commands/{command_id}/status", status_code=status.HTTP_200_OK)
def report_command_status(
    command_id: uuid.UUID,
    payload: CommandStatusUpdate,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Dict[str, str]:
    """Report command execution result."""
    require_service_token(authorization)
    command = update_command_status(db, command_id, payload.status, payload.error)
    if command is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Command not found")
    db.commit()
    logger.info(
        json.dumps(
            {
                "event": "command_status_updated",
                "command_id": str(command_id),
                "status": payload.status,
                "error": payload.error,
            }
        )
    )
    return {"status": "ok"}


@app.post("/internal/ingest/logs", status_code=status.HTTP_200_OK)
def upload_logs(
    payload: LogUploadRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Dict[str, str]:
    """Upload device logs."""
    require_service_token(authorization)
    snapshot = save_log_snapshot(db, payload.device_id, payload.content)
    db.commit()
    logger.info(
        json.dumps(
            {
                "event": "logs_uploaded",
                "snapshot_id": str(snapshot.id),
                "device_id": payload.device_id,
            }
        )
    )
    return {"status": "ok", "snapshot_id": str(snapshot.id)}


@app.post("/internal/ingest/audio", status_code=status.HTTP_200_OK)
async def upload_audio(
    file: UploadFile = File(...),
    metadata: str = Form(...),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Dict[str, str | bool]:
    """Upload audio recording to R2 and store metadata in database.

    Supports both legacy Opus format and new FLAC format.
    Detects format from metadata.codec field (defaults to flac).
    """
    require_service_token(authorization)

    r2 = get_r2_client()
    if r2 is None:
        raise HTTPException(status_code=503, detail="R2 storage not configured")

    meta = json.loads(metadata)

    # Generate recording_id if not provided (for backwards compatibility)
    recording_id = uuid.UUID(meta["recording_id"]) if "recording_id" in meta else uuid.uuid4()
    session_id = uuid.UUID(meta["session_id"])
    device_id = meta["device_id"]
    recorded_at_str = meta["recorded_at"]

    # New fields (with defaults for backwards compatibility)
    role = meta.get("role", "user")
    transcript = meta.get("transcript")
    codec = meta.get("codec", "flac")  # Default to flac for new uploads

    # Parse timestamp
    if recorded_at_str.endswith("Z"):
        recorded_at_str = recorded_at_str[:-1] + "+00:00"
    recorded_at = datetime.fromisoformat(recorded_at_str)

    # Determine file extension and content type based on codec
    if codec == "opus":
        ext = "opus"
        content_type = "audio/opus"
    else:
        ext = "flac"
        content_type = "audio/flac"

    # Generate R2 key with date hierarchy
    key = f"recordings/{device_id}/{recorded_at.year}/{recorded_at.month:02d}/{recorded_at.day:02d}/{recording_id}.{ext}"

    # Read file content
    content = await file.read()

    # Upload to R2
    r2.put_object(
        Bucket=R2_BUCKET,
        Key=key,
        Body=content,
        ContentType=content_type,
        Metadata={
            "session-id": str(session_id),
            "role": role,
            "sha256": meta.get("sha256", ""),
        },
    )

    storage_url = f"https://{R2_BUCKET}.r2.cloudflarestorage.com/{key}"

    # Insert into database
    audio_record = AudioRecording(
        id=recording_id,
        session_id=session_id,
        device_id=device_id,
        participant_id=meta.get("participant_id"),
        turn_number=meta["turn_number"],
        role=role,
        activity_id=meta.get("activity_id"),
        duration_ms=meta["duration_ms"],
        file_size_bytes=len(content),
        codec=codec,
        transcript=transcript,
        storage_url=storage_url,
        sha256=meta.get("sha256"),
        recorded_at=recorded_at,
    )
    db.add(audio_record)
    db.commit()

    logger.info(
        json.dumps(
            {
                "event": "audio_uploaded",
                "recording_id": str(recording_id),
                "session_id": str(session_id),
                "device_id": device_id,
                "role": role,
                "codec": codec,
                "file_size_bytes": len(content),
            }
        )
    )

    return {"success": True, "url": storage_url}


@app.post("/internal/ingest/session_audio", status_code=status.HTTP_200_OK)
async def upload_session_audio(
    file: UploadFile = File(...),
    metadata: str = Form(...),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Dict[str, str | bool]:
    """Upload audio recording with session-based organization and manifest.

    Stores audio in session folders:
    recordings/{device_id}/{year}/{month}/{day}/{session_id}/{turn}_{role}.flac

    Creates/updates manifest.json in the session folder with transcripts.
    """
    require_service_token(authorization)

    r2 = get_r2_client()
    if r2 is None:
        raise HTTPException(status_code=503, detail="R2 storage not configured")

    meta = json.loads(metadata)

    # Required fields
    session_id = uuid.UUID(meta["session_id"])
    device_id = meta["device_id"]
    turn_number = meta["turn_number"]
    role = meta.get("role", "user")  # user or assistant
    recorded_at_str = meta["recorded_at"]
    duration_ms = meta["duration_ms"]

    # Optional fields
    recording_id = uuid.UUID(meta["recording_id"]) if "recording_id" in meta else uuid.uuid4()
    participant_id = meta.get("participant_id")
    activity_id = meta.get("activity_id")
    transcript = meta.get("transcript")
    sha256 = meta.get("sha256", "")

    # Validate role
    if role not in ("user", "assistant"):
        raise HTTPException(status_code=400, detail="role must be 'user' or 'assistant'")

    # Parse timestamp
    if recorded_at_str.endswith("Z"):
        recorded_at_str = recorded_at_str[:-1] + "+00:00"
    recorded_at = datetime.fromisoformat(recorded_at_str)

    # Session folder path
    session_folder = f"recordings/{device_id}/{recorded_at.year}/{recorded_at.month:02d}/{recorded_at.day:02d}/{session_id}"

    # Audio file key: {turn:02d}_{role}.flac
    audio_key = f"{session_folder}/{turn_number:02d}_{role}.flac"

    # Read file content
    content = await file.read()

    # Upload audio to R2
    r2.put_object(
        Bucket=R2_BUCKET,
        Key=audio_key,
        Body=content,
        ContentType="audio/flac",
        Metadata={
            "session-id": str(session_id),
            "role": role,
            "turn": str(turn_number),
            "sha256": sha256,
        },
    )

    storage_url = f"https://{R2_BUCKET}.r2.cloudflarestorage.com/{audio_key}"

    # Update manifest.json
    manifest_key = f"{session_folder}/manifest.json"
    manifest = _get_or_create_manifest(r2, manifest_key, session_id, device_id, participant_id, recorded_at)

    # Add/update turn in manifest
    _update_manifest_turn(
        manifest,
        turn_number=turn_number,
        role=role,
        audio_filepath=f"{turn_number:02d}_{role}.flac",
        duration_ms=duration_ms,
        transcript=transcript,
        activity_id=activity_id,
    )

    # Upload updated manifest
    r2.put_object(
        Bucket=R2_BUCKET,
        Key=manifest_key,
        Body=json.dumps(manifest, indent=2),
        ContentType="application/json",
    )

    # Update participant index for easy data retrieval by participant
    if participant_id:
        try:
            _update_participant_index(
                r2=r2,
                participant_id=participant_id,
                session_id=session_id,
                device_id=device_id,
                recorded_at=recorded_at,
                duration_ms=duration_ms,
                turn_number=turn_number,
                manifest_key=manifest_key,
            )
        except Exception as e:
            # Log but don't fail the upload if index update fails
            logger.warning(f"Failed to update participant index: {e}")

    # Insert into database
    audio_record = AudioRecording(
        id=recording_id,
        session_id=session_id,
        device_id=device_id,
        participant_id=participant_id,
        turn_number=turn_number,
        role=role,
        activity_id=activity_id,
        duration_ms=duration_ms,
        file_size_bytes=len(content),
        codec="flac",
        transcript=transcript,
        storage_url=storage_url,
        sha256=sha256 if sha256 else None,
        recorded_at=recorded_at,
    )
    db.add(audio_record)
    db.commit()

    logger.info(
        json.dumps(
            {
                "event": "session_audio_uploaded",
                "recording_id": str(recording_id),
                "session_id": str(session_id),
                "device_id": device_id,
                "turn_number": turn_number,
                "role": role,
                "file_size_bytes": len(content),
            }
        )
    )

    return {"success": True, "url": storage_url, "manifest_url": f"https://{R2_BUCKET}.r2.cloudflarestorage.com/{manifest_key}"}


def _get_or_create_manifest(r2, manifest_key: str, session_id: uuid.UUID, device_id: str, participant_id: str | None, recorded_at: datetime) -> dict:
    """Get existing manifest or create a new one."""
    try:
        response = r2.get_object(Bucket=R2_BUCKET, Key=manifest_key)
        return json.loads(response["Body"].read().decode("utf-8"))
    except r2.exceptions.ClientError as e:
        # NoSuchKey or other errors - create new manifest
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code != "NoSuchKey":
            logger.warning(f"Error fetching manifest {manifest_key}: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error fetching manifest {manifest_key}: {e}")

    return {
        "session_id": str(session_id),
        "device_id": device_id,
        "participant_id": participant_id,
        "started_at": recorded_at.isoformat(),
        "turns": [],
    }


def _update_manifest_turn(manifest: dict, turn_number: int, role: str, audio_filepath: str, duration_ms: int, transcript: str | None, activity_id: str | None) -> None:
    """Add or update a turn in the manifest."""
    turns = manifest.get("turns", [])

    # Find existing turn or create new one
    turn_entry = None
    for t in turns:
        if t.get("turn") == turn_number:
            turn_entry = t
            break

    if turn_entry is None:
        turn_entry = {"turn": turn_number}
        turns.append(turn_entry)
        # Sort turns by turn number
        turns.sort(key=lambda x: x.get("turn", 0))
        manifest["turns"] = turns

    # Add activity_id if provided
    if activity_id:
        turn_entry["activity_id"] = activity_id

    # Add role data (user or assistant)
    turn_entry[role] = {
        "audio_filepath": audio_filepath,
        "duration_ms": duration_ms,
    }
    if transcript:
        turn_entry[role]["text"] = transcript


def _update_participant_index(
    r2,
    participant_id: str,
    session_id: uuid.UUID,
    device_id: str,
    recorded_at: datetime,
    duration_ms: int,
    turn_number: int,
    manifest_key: str,
) -> None:
    """Update participant index with session reference for easy data retrieval."""
    index_key = f"participants/{participant_id}/index.json"

    # Get existing index or create new one
    try:
        response = r2.get_object(Bucket=R2_BUCKET, Key=index_key)
        index = json.loads(response["Body"].read().decode("utf-8"))
    except r2.exceptions.ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code != "NoSuchKey":
            logger.warning(f"Error fetching participant index {index_key}: {e}")
        index = {
            "participant_id": participant_id,
            "created_at": recorded_at.isoformat(),
            "session_count": 0,
            "total_duration_ms": 0,
            "sessions": [],
        }
    except Exception as e:
        logger.warning(f"Unexpected error fetching participant index {index_key}: {e}")
        index = {
            "participant_id": participant_id,
            "created_at": recorded_at.isoformat(),
            "session_count": 0,
            "total_duration_ms": 0,
            "sessions": [],
        }

    # Find or add session entry
    session_entry = next(
        (s for s in index["sessions"] if s["session_id"] == str(session_id)), None
    )
    if session_entry is None:
        session_entry = {
            "session_id": str(session_id),
            "device_id": device_id,
            "started_at": recorded_at.isoformat(),
            "manifest_path": manifest_key,
            "turn_count": 0,
            "total_duration_ms": 0,
        }
        index["sessions"].append(session_entry)

    # Update session stats (accumulate duration, track max turn)
    session_entry["turn_count"] = max(session_entry["turn_count"], turn_number)
    session_entry["total_duration_ms"] = session_entry.get("total_duration_ms", 0) + duration_ms

    # Update index-level stats
    index["updated_at"] = datetime.utcnow().isoformat()
    index["session_count"] = len(index["sessions"])
    index["total_duration_ms"] = sum(s.get("total_duration_ms", 0) for s in index["sessions"])

    # Upload updated index
    r2.put_object(
        Bucket=R2_BUCKET,
        Key=index_key,
        Body=json.dumps(index, indent=2),
        ContentType="application/json",
    )
