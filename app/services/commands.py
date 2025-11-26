import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DeviceCommand, DeviceLogSnapshot


def queue_command(db: Session, device_id: str, command_type: str) -> DeviceCommand:
    """Create a new pending command for a device."""
    command = DeviceCommand(
        device_id=device_id,
        command_type=command_type,
        status="PENDING",
    )
    db.add(command)
    db.flush()
    return command


def get_pending_command(db: Session, device_id: str) -> DeviceCommand | None:
    """
    Get oldest pending command for device and mark as PICKED_UP.
    Uses SELECT FOR UPDATE to prevent race conditions.
    """
    stmt = (
        select(DeviceCommand)
        .where(DeviceCommand.device_id == device_id)
        .where(DeviceCommand.status == "PENDING")
        .order_by(DeviceCommand.created_at.asc())
        .limit(1)
        .with_for_update()
    )
    command = db.execute(stmt).scalar_one_or_none()
    if command:
        command.status = "PICKED_UP"
        db.flush()
    return command


def update_command_status(
    db: Session,
    command_id: uuid.UUID,
    status: str,
    error: str | None = None,
) -> DeviceCommand | None:
    """Update command status after execution."""
    command = db.get(DeviceCommand, command_id)
    if command:
        command.status = status
        command.error_message = error
        db.flush()
    return command


def save_log_snapshot(db: Session, device_id: str, content: str) -> DeviceLogSnapshot:
    """Save uploaded log content."""
    snapshot = DeviceLogSnapshot(
        device_id=device_id,
        log_content=content,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def get_latest_log(db: Session, device_id: str) -> DeviceLogSnapshot | None:
    """Get most recent log snapshot for a device."""
    stmt = (
        select(DeviceLogSnapshot)
        .where(DeviceLogSnapshot.device_id == device_id)
        .order_by(DeviceLogSnapshot.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()
