"""Clean start, schema bootstrap and the optional owner password."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app import db as db_module
from app.config import get_settings
from app.main import create_app
from app.security import sign_session_value, verify_session_value


def test_clean_start_creates_schema_and_directories(tmp_path, monkeypatch):
    """A brand new deployment needs nothing but the environment variables."""
    db_path = tmp_path / "fresh" / "approval_pack.db"
    storage = tmp_path / "fresh" / "snapshots"
    assert not db_path.exists() and not storage.exists()

    monkeypatch.setenv("APPROVAL_PACK_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APPROVAL_PACK_STORAGE_DIR", str(storage))
    get_settings.cache_clear()
    db_module.reset_state()

    try:
        with TestClient(create_app()) as client:
            assert client.get("/healthz").status_code == 200
            tables = set(inspect(db_module.get_engine()).get_table_names())
            assert {"approvals", "decisions"} <= tables

            response = client.post(
                "/approvals",
                data={"title": "First", "text": "hello"},
                follow_redirects=False,
            )
            assert response.status_code == 303

        assert db_path.exists()
        assert Path(storage).is_dir()
    finally:
        db_module.reset_state()
        get_settings.cache_clear()


def test_owner_area_is_open_when_no_password_is_set(client):
    assert client.get("/").status_code == 200
    assert client.get("/login", follow_redirects=False).status_code == 303


def test_owner_area_requires_login_when_password_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_PACK_DATABASE_URL", f"sqlite:///{tmp_path / 'p.db'}")
    monkeypatch.setenv("APPROVAL_PACK_STORAGE_DIR", str(tmp_path / "snap"))
    monkeypatch.setenv("APPROVAL_PACK_OWNER_PASSWORD", "hunter2")
    monkeypatch.setenv("APPROVAL_PACK_SECRET_KEY", "unit-test-key")
    get_settings.cache_clear()
    db_module.reset_state()

    try:
        with TestClient(create_app()) as client:
            redirected = client.get("/", follow_redirects=False)
            assert redirected.status_code == 303
            assert redirected.headers["location"].startswith("/login")

            wrong = client.post("/login", data={"password": "nope", "next": "/"})
            assert wrong.status_code == 401

            ok = client.post(
                "/login", data={"password": "hunter2", "next": "/"},
                follow_redirects=False,
            )
            assert ok.status_code == 303
            assert client.get("/").status_code == 200

            # The public review route stays open -- reviewers never log in.
            assert client.get("/review/" + "x" * 43).status_code == 404
    finally:
        db_module.reset_state()
        get_settings.cache_clear()


def test_session_cookie_signature_is_verified():
    signed = sign_session_value("k", "owner")
    assert verify_session_value("k", signed) == "owner"
    assert verify_session_value("other-key", signed) is None
    assert verify_session_value("k", "owner.deadbeef") is None
    assert verify_session_value("k", "garbage") is None
