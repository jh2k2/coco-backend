from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db_utils import dialect_insert
from ..models import DashboardRollup, Session as SessionModel, User
from ..schemas import SessionSummaryIngestRequest


def ingest_session_summary(db: Session, payload: SessionSummaryIngestRequest, device_id: str | None = None) -> Dict[str, bool]:
    """Ingest a session summary, handling duplicates atomically with ON CONFLICT."""
    settings = get_settings()
    user = _get_or_create_user(db, payload.user_external_id)

    # Use ON CONFLICT DO NOTHING for atomic duplicate detection
    # This eliminates race conditions and avoids transaction rollbacks
    stmt = dialect_insert(db, SessionModel).values(
        user_id=user.id,
        device_id=device_id,
        session_id=payload.session_id,
        started_at=payload.started_at,
        duration_seconds=payload.duration_seconds,
        sentiment_score=_quantize_score(payload.sentiment_score),
        status=payload.status,
    ).on_conflict_do_nothing(index_elements=['session_id'])

    result = db.execute(stmt)
    if result.rowcount == 0:
        return {"duplicate": True}

    db.flush()
    recompute_dashboard_rollup(db, user.id, settings.rollup_window_days)
    return {"duplicate": False}


def _get_or_create_user(db: Session, external_id: str) -> User:
    """Get or create a user, handling concurrent creation atomically with ON CONFLICT."""
    # Use ON CONFLICT DO NOTHING for atomic upsert behavior
    # This eliminates race conditions and avoids transaction rollbacks
    stmt = dialect_insert(db, User).values(
        external_id=external_id
    ).on_conflict_do_nothing(index_elements=['external_id'])
    db.execute(stmt)
    db.flush()

    # Always SELECT to get the user (whether just created or already existed)
    return db.execute(
        select(User).where(User.external_id == external_id)
    ).scalar_one()


def recompute_dashboard_rollup(db: Session, user_id: str, window_days: int) -> None:
    if window_days != 7:
        raise ValueError("window_days must be 7 for the current release")
    now = datetime.now(timezone.utc)
    start_day = (now.date() - timedelta(days=window_days - 1)) if window_days > 0 else now.date()
    window_start = datetime.combine(start_day, time.min, tzinfo=timezone.utc)

    stmt = (
        select(SessionModel)
        .where(SessionModel.user_id == user_id, SessionModel.started_at >= window_start)
        .order_by(SessionModel.started_at.asc())
    )
    sessions = list(db.execute(stmt).scalars())

    day_buckets: Dict[date, List[SessionModel]] = defaultdict(list)
    for session in sessions:
        # Credit every session to the UTC day it started, even if it crosses midnight.
        session_day = session.started_at.astimezone(timezone.utc).date()
        day_buckets[session_day].append(session)

    ordered_days = [start_day + timedelta(days=offset) for offset in range(window_days)]
    daily_activity: List[bool] = []
    daily_durations: List[int] = []
    daily_sentiment: List[Decimal | None] = []

    last_session_at = None
    for day in ordered_days:
        bucket = day_buckets.get(day, [])
        if bucket:
            day_duration_seconds = sum(item.duration_seconds for item in bucket)
            duration_minutes = _round_minutes_from_seconds(day_duration_seconds)
            sentiment_avg = _average_sentiment(bucket)
            daily_activity.append(True)
            daily_durations.append(duration_minutes)
            daily_sentiment.append(sentiment_avg)
            last_in_bucket = max(
                bucket,
                key=lambda item: item.started_at + timedelta(seconds=item.duration_seconds),
            )
            candidate_last = last_in_bucket.started_at + timedelta(seconds=last_in_bucket.duration_seconds)
            if not last_session_at or candidate_last > last_session_at:
                last_session_at = candidate_last
        else:
            daily_activity.append(False)
            daily_durations.append(0)
            daily_sentiment.append(None)

    avg_duration_minutes = _average_nonzero_duration(daily_durations)
    current_tone = _determine_current_tone(daily_sentiment)

    rollup = db.get(DashboardRollup, user_id)
    if rollup is None:
        rollup = DashboardRollup(
            user_id=user_id,
            last_session_at=last_session_at,
            daily_activity=daily_activity,
            daily_durations=daily_durations,
            daily_sentiment=daily_sentiment,
            avg_duration_minutes=avg_duration_minutes,
            current_tone=current_tone,
            updated_at=now,
        )
        db.add(rollup)
    else:
        rollup.last_session_at = last_session_at
        rollup.daily_activity = daily_activity
        rollup.daily_durations = daily_durations
        rollup.daily_sentiment = daily_sentiment
        rollup.avg_duration_minutes = avg_duration_minutes
        rollup.current_tone = current_tone
        rollup.updated_at = now


def _average_sentiment(sessions: List[SessionModel]) -> Decimal:
    total = sum(Decimal(session.sentiment_score) for session in sessions)
    avg = total / Decimal(len(sessions))
    return avg.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _average_nonzero_duration(durations: List[int]) -> int:
    non_zero = [value for value in durations if value > 0]
    if not non_zero:
        return 0
    total = Decimal(sum(non_zero))
    count = Decimal(len(non_zero))
    average = (total / count).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(average)


def _determine_current_tone(daily_sentiment: List[Decimal | None]) -> str:
    for sentiment in reversed(daily_sentiment):
        if sentiment is None:
            continue
        value = float(sentiment)
        if value >= 0.61:
            return "positive"
        if value >= 0.40:
            return "neutral"
        return "negative"
    return "neutral"


def _quantize_score(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _round_minutes_from_seconds(seconds: int) -> int:
    minutes = Decimal(seconds) / Decimal(60)
    return int(minutes.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
