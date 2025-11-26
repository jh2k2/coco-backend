"""Tests for the device command system."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import DeviceCommand, DeviceLogSnapshot


# -----------------------------------------------------------------------------
# Admin Endpoints
# -----------------------------------------------------------------------------


def test_create_command_success(client):
    """POST /admin/commands creates a pending command."""
    headers = {"Authorization": "Bearer test-admin-token"}
    payload = {"device_id": "coco-living-room", "command": "REBOOT"}

    response = client.post("/admin/commands", json=payload, headers=headers)

    assert response.status_code == 201
    data = response.json()
    assert data["device_id"] == "coco-living-room"
    assert data["command_type"] == "REBOOT"
    assert data["status"] == "PENDING"
    assert "id" in data
    assert "created_at" in data

    # Verify in database
    with SessionLocal() as db:
        cmd = db.get(DeviceCommand, uuid.UUID(data["id"]))
        assert cmd is not None
        assert cmd.device_id == "coco-living-room"
        assert cmd.command_type == "REBOOT"
        assert cmd.status == "PENDING"


def test_create_command_all_types(client):
    """POST /admin/commands accepts all valid command types."""
    headers = {"Authorization": "Bearer test-admin-token"}
    command_types = ["REBOOT", "RESTART_SERVICE", "UPLOAD_LOGS", "UPDATE_NOW"]

    for cmd_type in command_types:
        payload = {"device_id": f"device-{cmd_type.lower()}", "command": cmd_type}
        response = client.post("/admin/commands", json=payload, headers=headers)
        assert response.status_code == 201, f"Failed for {cmd_type}"
        assert response.json()["command_type"] == cmd_type


def test_create_command_unauthorized_no_token(client):
    """POST /admin/commands without token returns 401."""
    payload = {"device_id": "coco-living-room", "command": "REBOOT"}

    response = client.post("/admin/commands", json=payload)

    assert response.status_code == 401


def test_create_command_unauthorized_wrong_token(client):
    """POST /admin/commands with wrong token returns 401."""
    headers = {"Authorization": "Bearer wrong-token"}
    payload = {"device_id": "coco-living-room", "command": "REBOOT"}

    response = client.post("/admin/commands", json=payload, headers=headers)

    assert response.status_code == 401


def test_create_command_invalid_command_type(client):
    """POST /admin/commands with invalid command type returns 422."""
    headers = {"Authorization": "Bearer test-admin-token"}
    payload = {"device_id": "coco-living-room", "command": "INVALID_COMMAND"}

    response = client.post("/admin/commands", json=payload, headers=headers)

    assert response.status_code == 422


def test_create_command_empty_device_id(client):
    """POST /admin/commands with empty device_id returns 422."""
    headers = {"Authorization": "Bearer test-admin-token"}
    payload = {"device_id": "", "command": "REBOOT"}

    response = client.post("/admin/commands", json=payload, headers=headers)

    assert response.status_code == 422


def test_get_logs_with_data(client):
    """GET /admin/logs/{device_id} returns the most recent log snapshot."""
    headers = {"Authorization": "Bearer test-admin-token"}

    # First upload some logs
    ingest_headers = {"Authorization": "Bearer test-ingest-token"}
    log_content = "2024-11-25 14:32:01 [INFO] Agent started..."
    upload_response = client.post(
        "/internal/ingest/logs",
        json={"device_id": "coco-living-room", "content": log_content},
        headers=ingest_headers,
    )
    assert upload_response.status_code == 200

    # Now fetch logs via admin endpoint
    response = client.get("/admin/logs/coco-living-room", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["snapshot"] is not None
    assert data["snapshot"]["device_id"] == "coco-living-room"
    assert data["snapshot"]["log_content"] == log_content
    assert "id" in data["snapshot"]
    assert "created_at" in data["snapshot"]


def test_get_logs_no_data(client):
    """GET /admin/logs/{device_id} returns null snapshot when no logs exist."""
    headers = {"Authorization": "Bearer test-admin-token"}

    response = client.get("/admin/logs/device-without-logs", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["snapshot"] is None


def test_get_logs_returns_most_recent(client):
    """GET /admin/logs/{device_id} returns only the most recent snapshot."""
    headers = {"Authorization": "Bearer test-admin-token"}
    ingest_headers = {"Authorization": "Bearer test-ingest-token"}

    # Upload multiple log snapshots
    client.post(
        "/internal/ingest/logs",
        json={"device_id": "coco-test", "content": "First log"},
        headers=ingest_headers,
    )
    client.post(
        "/internal/ingest/logs",
        json={"device_id": "coco-test", "content": "Second log"},
        headers=ingest_headers,
    )
    client.post(
        "/internal/ingest/logs",
        json={"device_id": "coco-test", "content": "Third log (most recent)"},
        headers=ingest_headers,
    )

    response = client.get("/admin/logs/coco-test", headers=headers)

    assert response.status_code == 200
    assert response.json()["snapshot"]["log_content"] == "Third log (most recent)"


def test_get_logs_unauthorized(client):
    """GET /admin/logs/{device_id} without valid token returns 401."""
    response = client.get("/admin/logs/coco-living-room")
    assert response.status_code == 401

    response = client.get(
        "/admin/logs/coco-living-room",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


# -----------------------------------------------------------------------------
# Device Endpoints (Internal)
# -----------------------------------------------------------------------------


def test_poll_pending_command_success(client):
    """GET /internal/commands/pending returns oldest pending command."""
    admin_headers = {"Authorization": "Bearer test-admin-token"}
    device_headers = {
        "Authorization": "Bearer test-ingest-token",
        "X-Device-ID": "coco-living-room",
    }

    # Create a command
    client.post(
        "/admin/commands",
        json={"device_id": "coco-living-room", "command": "REBOOT"},
        headers=admin_headers,
    )

    # Poll for it
    response = client.get("/internal/commands/pending", headers=device_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["command"] is not None
    assert data["command"]["command_type"] == "REBOOT"
    assert "id" in data["command"]
    assert "created_at" in data["command"]


def test_poll_pending_command_no_commands(client):
    """GET /internal/commands/pending returns null when no commands pending."""
    device_headers = {
        "Authorization": "Bearer test-ingest-token",
        "X-Device-ID": "coco-living-room",
    }

    response = client.get("/internal/commands/pending", headers=device_headers)

    assert response.status_code == 200
    assert response.json()["command"] is None


def test_poll_pending_command_marks_picked_up(client):
    """GET /internal/commands/pending transitions status to PICKED_UP."""
    admin_headers = {"Authorization": "Bearer test-admin-token"}
    device_headers = {
        "Authorization": "Bearer test-ingest-token",
        "X-Device-ID": "coco-living-room",
    }

    # Create a command
    create_response = client.post(
        "/admin/commands",
        json={"device_id": "coco-living-room", "command": "REBOOT"},
        headers=admin_headers,
    )
    command_id = create_response.json()["id"]

    # Poll for it
    client.get("/internal/commands/pending", headers=device_headers)

    # Verify status changed in database
    with SessionLocal() as db:
        cmd = db.get(DeviceCommand, uuid.UUID(command_id))
        assert cmd.status == "PICKED_UP"


def test_poll_pending_command_fifo_order(client):
    """GET /internal/commands/pending returns commands in FIFO order."""
    admin_headers = {"Authorization": "Bearer test-admin-token"}
    device_headers = {
        "Authorization": "Bearer test-ingest-token",
        "X-Device-ID": "coco-living-room",
    }

    # Create multiple commands
    client.post(
        "/admin/commands",
        json={"device_id": "coco-living-room", "command": "REBOOT"},
        headers=admin_headers,
    )
    client.post(
        "/admin/commands",
        json={"device_id": "coco-living-room", "command": "RESTART_SERVICE"},
        headers=admin_headers,
    )
    client.post(
        "/admin/commands",
        json={"device_id": "coco-living-room", "command": "UPLOAD_LOGS"},
        headers=admin_headers,
    )

    # Poll should return REBOOT first
    response1 = client.get("/internal/commands/pending", headers=device_headers)
    assert response1.json()["command"]["command_type"] == "REBOOT"

    # Then RESTART_SERVICE
    response2 = client.get("/internal/commands/pending", headers=device_headers)
    assert response2.json()["command"]["command_type"] == "RESTART_SERVICE"

    # Then UPLOAD_LOGS
    response3 = client.get("/internal/commands/pending", headers=device_headers)
    assert response3.json()["command"]["command_type"] == "UPLOAD_LOGS"

    # Then none
    response4 = client.get("/internal/commands/pending", headers=device_headers)
    assert response4.json()["command"] is None


def test_poll_pending_command_device_isolation(client):
    """GET /internal/commands/pending only returns commands for the requesting device."""
    admin_headers = {"Authorization": "Bearer test-admin-token"}

    # Create command for device A
    client.post(
        "/admin/commands",
        json={"device_id": "device-a", "command": "REBOOT"},
        headers=admin_headers,
    )

    # Device B polls - should get nothing
    device_b_headers = {
        "Authorization": "Bearer test-ingest-token",
        "X-Device-ID": "device-b",
    }
    response = client.get("/internal/commands/pending", headers=device_b_headers)
    assert response.json()["command"] is None

    # Device A polls - should get the command
    device_a_headers = {
        "Authorization": "Bearer test-ingest-token",
        "X-Device-ID": "device-a",
    }
    response = client.get("/internal/commands/pending", headers=device_a_headers)
    assert response.json()["command"] is not None
    assert response.json()["command"]["command_type"] == "REBOOT"


def test_poll_pending_command_missing_device_id(client):
    """GET /internal/commands/pending without X-Device-ID returns null command."""
    headers = {"Authorization": "Bearer test-ingest-token"}

    response = client.get("/internal/commands/pending", headers=headers)

    assert response.status_code == 200
    assert response.json()["command"] is None


def test_poll_pending_command_unauthorized(client):
    """GET /internal/commands/pending without valid token returns 401."""
    device_headers = {"X-Device-ID": "coco-living-room"}

    response = client.get("/internal/commands/pending", headers=device_headers)
    assert response.status_code == 401

    device_headers["Authorization"] = "Bearer wrong-token"
    response = client.get("/internal/commands/pending", headers=device_headers)
    assert response.status_code == 401


def test_report_command_status_completed(client):
    """POST /internal/commands/{id}/status marks command as COMPLETED."""
    admin_headers = {"Authorization": "Bearer test-admin-token"}
    device_headers = {
        "Authorization": "Bearer test-ingest-token",
        "X-Device-ID": "coco-living-room",
    }

    # Create and pick up command
    create_response = client.post(
        "/admin/commands",
        json={"device_id": "coco-living-room", "command": "REBOOT"},
        headers=admin_headers,
    )
    command_id = create_response.json()["id"]
    client.get("/internal/commands/pending", headers=device_headers)

    # Report completion
    response = client.post(
        f"/internal/commands/{command_id}/status",
        json={"status": "COMPLETED"},
        headers={"Authorization": "Bearer test-ingest-token"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    # Verify in database
    with SessionLocal() as db:
        cmd = db.get(DeviceCommand, uuid.UUID(command_id))
        assert cmd.status == "COMPLETED"
        assert cmd.error_message is None


def test_report_command_status_failed(client):
    """POST /internal/commands/{id}/status marks command as FAILED with error."""
    admin_headers = {"Authorization": "Bearer test-admin-token"}
    device_headers = {
        "Authorization": "Bearer test-ingest-token",
        "X-Device-ID": "coco-living-room",
    }

    # Create and pick up command
    create_response = client.post(
        "/admin/commands",
        json={"device_id": "coco-living-room", "command": "REBOOT"},
        headers=admin_headers,
    )
    command_id = create_response.json()["id"]
    client.get("/internal/commands/pending", headers=device_headers)

    # Report failure
    error_msg = "Permission denied: sudo requires password"
    response = client.post(
        f"/internal/commands/{command_id}/status",
        json={"status": "FAILED", "error": error_msg},
        headers={"Authorization": "Bearer test-ingest-token"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    # Verify in database
    with SessionLocal() as db:
        cmd = db.get(DeviceCommand, uuid.UUID(command_id))
        assert cmd.status == "FAILED"
        assert cmd.error_message == error_msg


def test_report_command_status_not_found(client):
    """POST /internal/commands/{id}/status returns 404 for nonexistent command."""
    fake_id = str(uuid.uuid4())

    response = client.post(
        f"/internal/commands/{fake_id}/status",
        json={"status": "COMPLETED"},
        headers={"Authorization": "Bearer test-ingest-token"},
    )

    assert response.status_code == 404


def test_report_command_status_invalid_status(client):
    """POST /internal/commands/{id}/status rejects invalid status values."""
    admin_headers = {"Authorization": "Bearer test-admin-token"}

    create_response = client.post(
        "/admin/commands",
        json={"device_id": "coco-living-room", "command": "REBOOT"},
        headers=admin_headers,
    )
    command_id = create_response.json()["id"]

    response = client.post(
        f"/internal/commands/{command_id}/status",
        json={"status": "INVALID_STATUS"},
        headers={"Authorization": "Bearer test-ingest-token"},
    )

    assert response.status_code == 422


def test_report_command_status_unauthorized(client):
    """POST /internal/commands/{id}/status without valid token returns 401."""
    fake_id = str(uuid.uuid4())

    response = client.post(
        f"/internal/commands/{fake_id}/status",
        json={"status": "COMPLETED"},
    )
    assert response.status_code == 401

    response = client.post(
        f"/internal/commands/{fake_id}/status",
        json={"status": "COMPLETED"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_upload_logs_success(client):
    """POST /internal/ingest/logs creates a log snapshot."""
    headers = {"Authorization": "Bearer test-ingest-token"}
    log_content = "2024-11-25 14:32:01 [INFO] Agent started...\n2024-11-25 14:32:02 [INFO] Connected to backend"

    response = client.post(
        "/internal/ingest/logs",
        json={"device_id": "coco-living-room", "content": log_content},
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "snapshot_id" in data

    # Verify in database
    with SessionLocal() as db:
        snapshot = db.get(DeviceLogSnapshot, uuid.UUID(data["snapshot_id"]))
        assert snapshot is not None
        assert snapshot.device_id == "coco-living-room"
        assert snapshot.log_content == log_content


def test_upload_logs_empty_content(client):
    """POST /internal/ingest/logs rejects empty content."""
    headers = {"Authorization": "Bearer test-ingest-token"}

    response = client.post(
        "/internal/ingest/logs",
        json={"device_id": "coco-living-room", "content": ""},
        headers=headers,
    )

    assert response.status_code == 422


def test_upload_logs_empty_device_id(client):
    """POST /internal/ingest/logs rejects empty device_id."""
    headers = {"Authorization": "Bearer test-ingest-token"}

    response = client.post(
        "/internal/ingest/logs",
        json={"device_id": "", "content": "some logs"},
        headers=headers,
    )

    assert response.status_code == 422


def test_upload_logs_unauthorized(client):
    """POST /internal/ingest/logs without valid token returns 401."""
    response = client.post(
        "/internal/ingest/logs",
        json={"device_id": "coco-living-room", "content": "some logs"},
    )
    assert response.status_code == 401

    response = client.post(
        "/internal/ingest/logs",
        json={"device_id": "coco-living-room", "content": "some logs"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


# -----------------------------------------------------------------------------
# Full Lifecycle Tests
# -----------------------------------------------------------------------------


def test_full_command_lifecycle(client):
    """Test complete command lifecycle: create -> poll -> complete."""
    admin_headers = {"Authorization": "Bearer test-admin-token"}
    device_headers = {
        "Authorization": "Bearer test-ingest-token",
        "X-Device-ID": "coco-living-room",
    }
    service_headers = {"Authorization": "Bearer test-ingest-token"}

    # 1. Admin creates command
    create_response = client.post(
        "/admin/commands",
        json={"device_id": "coco-living-room", "command": "UPLOAD_LOGS"},
        headers=admin_headers,
    )
    assert create_response.status_code == 201
    command_id = create_response.json()["id"]
    assert create_response.json()["status"] == "PENDING"

    # 2. Device polls and gets command
    poll_response = client.get("/internal/commands/pending", headers=device_headers)
    assert poll_response.status_code == 200
    assert poll_response.json()["command"]["id"] == command_id
    assert poll_response.json()["command"]["command_type"] == "UPLOAD_LOGS"

    # 3. Verify status is PICKED_UP
    with SessionLocal() as db:
        cmd = db.get(DeviceCommand, uuid.UUID(command_id))
        assert cmd.status == "PICKED_UP"

    # 4. Device uploads logs (simulating command execution)
    log_upload_response = client.post(
        "/internal/ingest/logs",
        json={"device_id": "coco-living-room", "content": "Log content here..."},
        headers=service_headers,
    )
    assert log_upload_response.status_code == 200

    # 5. Device reports command completion
    status_response = client.post(
        f"/internal/commands/{command_id}/status",
        json={"status": "COMPLETED"},
        headers=service_headers,
    )
    assert status_response.status_code == 200

    # 6. Verify final status
    with SessionLocal() as db:
        cmd = db.get(DeviceCommand, uuid.UUID(command_id))
        assert cmd.status == "COMPLETED"

    # 7. Admin can retrieve the logs
    logs_response = client.get("/admin/logs/coco-living-room", headers=admin_headers)
    assert logs_response.status_code == 200
    assert logs_response.json()["snapshot"]["log_content"] == "Log content here..."


def test_full_command_lifecycle_failure(client):
    """Test command lifecycle with failure: create -> poll -> fail."""
    admin_headers = {"Authorization": "Bearer test-admin-token"}
    device_headers = {
        "Authorization": "Bearer test-ingest-token",
        "X-Device-ID": "coco-living-room",
    }
    service_headers = {"Authorization": "Bearer test-ingest-token"}

    # 1. Admin creates command
    create_response = client.post(
        "/admin/commands",
        json={"device_id": "coco-living-room", "command": "REBOOT"},
        headers=admin_headers,
    )
    command_id = create_response.json()["id"]

    # 2. Device polls and gets command
    client.get("/internal/commands/pending", headers=device_headers)

    # 3. Device reports failure
    error_message = "Failed to execute: permission denied"
    status_response = client.post(
        f"/internal/commands/{command_id}/status",
        json={"status": "FAILED", "error": error_message},
        headers=service_headers,
    )
    assert status_response.status_code == 200

    # 4. Verify final status
    with SessionLocal() as db:
        cmd = db.get(DeviceCommand, uuid.UUID(command_id))
        assert cmd.status == "FAILED"
        assert cmd.error_message == error_message


def test_multiple_devices_independent_queues(client):
    """Test that multiple devices have independent command queues."""
    admin_headers = {"Authorization": "Bearer test-admin-token"}

    # Create commands for multiple devices
    devices = ["device-a", "device-b", "device-c"]
    commands = {}

    for device in devices:
        response = client.post(
            "/admin/commands",
            json={"device_id": device, "command": "REBOOT"},
            headers=admin_headers,
        )
        commands[device] = response.json()["id"]

    # Each device polls and gets only their own command
    for device in devices:
        device_headers = {
            "Authorization": "Bearer test-ingest-token",
            "X-Device-ID": device,
        }
        response = client.get("/internal/commands/pending", headers=device_headers)
        assert response.json()["command"]["id"] == commands[device]

        # Second poll should return nothing
        response = client.get("/internal/commands/pending", headers=device_headers)
        assert response.json()["command"] is None
