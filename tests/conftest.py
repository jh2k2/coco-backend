from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("INGEST_SERVICE_TOKEN", "test-ingest-token")
os.environ.setdefault("DASHBOARD_TOKEN_MAP", "dash-token:test-user,admin-token:*")
os.environ.setdefault("DASHBOARD_ORIGIN", "http://dashboard.local")
os.environ.setdefault("APP_ENV", "test")

from app.config import get_settings

get_settings.cache_clear()

import app.database as database_module  # noqa: E402
import app.main as main_module  # noqa: E402

importlib.reload(database_module)
importlib.reload(main_module)

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    with TestClient(app) as test_client:
        yield test_client
