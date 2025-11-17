from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from typing import Sequence
from uuid import uuid4

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import DashboardRollup, Session as SessionModel, User
from app.schemas import SessionSummaryIngestRequest
from app.services.ingest import ingest_session_summary


def _build_payloads(user_external_id: str) -> Sequence[SessionSummaryIngestRequest]:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start_day = now - timedelta(days=6)
    templates = [
        # (hours offset, duration seconds, sentiment score)
        (18, 900, 0.82),
        (17, 1200, 0.74),
        (19, 600, 0.65),
        (18, 900, 0.55),
        (17, 1800, 0.62),
        (16, 1500, 0.48),
        (20, 2100, 0.71),
    ]
    payloads: list[SessionSummaryIngestRequest] = []
    for index, (hour_offset, duration_seconds, sentiment) in enumerate(templates):
        started_at = (start_day + timedelta(days=index)).replace(hour=hour_offset)
        payloads.append(
            SessionSummaryIngestRequest(
                session_id=f"{user_external_id}-{index}-{uuid4()}",
                user_external_id=user_external_id,
                started_at=started_at,
                duration_seconds=duration_seconds,
                sentiment_score=sentiment,
            )
        )
    return payloads


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo session data for dashboard smoke tests.")
    parser.add_argument("--user", dest="user_external_id", default="demo-user", help="External user id to seed.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear existing sessions and rollup data for the selected user before seeding.",
    )
    args = parser.parse_args()

    payloads = _build_payloads(args.user_external_id)

    with SessionLocal() as session:
        stmt = select(User).where(User.external_id == args.user_external_id).limit(1)
        user = session.execute(stmt).scalar_one_or_none()
        if user is None:
            user = User(external_id=args.user_external_id)
            session.add(user)
            session.commit()
        if args.reset:
            session.execute(delete(SessionModel).where(SessionModel.user_id == user.id))
            session.execute(delete(DashboardRollup).where(DashboardRollup.user_id == user.id))
            session.commit()
        for payload in payloads:
            ingest_session_summary(session, payload)
        session.commit()


if __name__ == "__main__":
    main()
