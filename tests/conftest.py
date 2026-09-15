"""Test fixtures: every test gets a throwaway database and storage directory.

Configuration flows through the real environment variables, so tests exercise
exactly the settings path production uses.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db as db_module
from app.config import Settings, get_settings
from app.services import ApprovalService
from app.storage import SnapshotStorage

ENV = {
    "APPROVAL_PACK_BASE_URL": "http://testserver",
    "APPROVAL_PACK_MAX_UPLOAD_BYTES": str(64 * 1024),
    "APPROVAL_PACK_MAX_TEXT_CHARS": "5000",
    "APPROVAL_PACK_OWNER_PASSWORD": "",
    "APPROVAL_PACK_SECRET_KEY": "test-secret",
}


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    monkeypatch.chdir(tmp_path)
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APPROVAL_PACK_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("APPROVAL_PACK_STORAGE_DIR", str(tmp_path / "snapshots"))

    get_settings.cache_clear()
    db_module.reset_state()

    current = get_settings()
    SnapshotStorage(current.storage_dir).ensure_ready()
    db_module.init_db()

    yield current

    db_module.reset_state()
    get_settings.cache_clear()


@pytest.fixture
def session(settings: Settings) -> Iterator[Session]:  # noqa: ARG001
    factory = db_module.get_session_factory()
    with factory() as db_session:
        yield db_session


@pytest.fixture
def service(session: Session, settings: Settings) -> ApprovalService:
    return ApprovalService(session, settings)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app(settings)) as test_client:
        yield test_client
