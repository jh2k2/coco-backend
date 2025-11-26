from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import authorize_dashboard_access, require_admin_token, require_service_token
from .config import get_settings
from .database import Base, engine
from .dependencies import get_db
from .models import DashboardRollup, User
from .schemas import (
    AvgDuration,
    CommandCreateRequest,
    CommandResponse,
    CommandStatusUpdate,
    DashboardResponse,
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
from .services.heartbeat import STALE_MINUTES, list_heartbeat_statuses, record_heartbeat
from .services.ingest import ingest_session_summary

logger = logging.getLogger("coco.api")
logging.basicConfig(level=logging.INFO)

settings = get_settings()
WINDOW_DAYS = settings.rollup_window_days

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
    db.commit()
    heartbeat_age_seconds: float | None = None
    if payload.timestamp is not None:
        heartbeat_age_seconds = max(
            0.0,
            round((hb.server_received_at - payload.timestamp).total_seconds(), 3),
        )
    status = (
        "dead"
        if hb.server_received_at < datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES)
        else ("healthy" if hb.agent_status == "ok" and hb.latency_ms is not None and hb.latency_ms < 300 else "degraded")
    )

    logger.info(
        json.dumps(
            {
                "event": "heartbeat_ingested",
                "device_id": payload.device_id,
                "agent_version": payload.agent_version,
                "heartbeat_age_seconds": heartbeat_age_seconds,
                "status": status,
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
) -> Dict[str, str]:
    require_service_token(authorization)
    request.state.user_id = payload.user_external_id
    try:
        result = ingest_session_summary(db, payload)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_unique_violation(exc):
            # Treat unique violations on session insert as safe duplicates.
            return {"status": "duplicate"}
        raise
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
        user = User(external_id=user_id)
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            user = db.execute(user_stmt).scalar_one()
        else:
            db.refresh(user)

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


def _is_unique_violation(error: IntegrityError) -> bool:
    if hasattr(error.orig, "pgcode") and error.orig.pgcode == "23505":
        return True
    message = str(error.orig).lower()
    return "unique" in message or "duplicate" in message


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
