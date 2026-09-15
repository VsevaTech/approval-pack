"""File validation, filename sanitising, path traversal, token entropy."""

from __future__ import annotations

import pytest

from app.security import (
    generate_review_token,
    is_allowed_extension,
    media_type_for,
    sanitize_filename,
    tokens_equal,
)
from app.services import ValidationError
from app.storage import SnapshotStorage, StorageError
from tests.factories import file_draft, text_draft

# -- filenames -----------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("../../../../etc/shadow", "shadow"),
        ("C:\\Windows\\System32\\cmd.txt", "cmd.txt"),
        ("/absolute/path/report.pdf", "report.pdf"),
        ("..%2f..%2fboot.txt", "2f._2fboot.txt"),
        ("....//....//x.txt", "x.txt"),
        ("normal name (v2).pdf", "normal_name_v2_.pdf"),
        ("\u0441\u043c\u0435\u0442\u0430.pdf", "pdf"),
        ("", "snapshot"),
        (None, "snapshot"),
        ("...", "snapshot"),
        ("file\x00.txt", "file.txt"),
    ],
)
def test_sanitize_filename(raw, expected):
    result = sanitize_filename(raw)
    assert result == expected
    assert "/" not in result and "\\" not in result and ".." not in result


def test_sanitize_filename_length_is_bounded():
    result = sanitize_filename("a" * 400 + ".txt")
    assert len(result) <= 120


# -- upload allowlist ----------------------------------------------------

@pytest.mark.parametrize("name", ["a.pdf", "a.PNG", "a.docx", "a.csv", "a.txt"])
def test_allowed_extensions(name):
    assert is_allowed_extension(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "evil.html", "evil.htm", "evil.xhtml", "evil.js", "evil.mjs",
        "evil.svg", "evil.xml", "evil.sh", "evil.exe", "evil.php", "noext",
    ],
)
def test_executable_and_scriptable_extensions_are_refused(name):
    assert is_allowed_extension(name) is False


def test_uploading_html_is_refused(service):
    with pytest.raises(ValidationError, match="not accepted"):
        service.create(file_draft(filename="payload.html", content=b"<script>x()</script>"))


def test_uploading_svg_is_refused(service):
    with pytest.raises(ValidationError, match="not accepted"):
        service.create(file_draft(filename="logo.svg", content=b"<svg onload=alert(1)>"))


def test_traversal_filename_cannot_escape_storage(service, settings):
    approval = service.create(
        file_draft(filename="../../../../tmp/owned.txt", content=b"data")
    )
    stored = service.storage.path_for(approval.snapshot_stored_name)

    assert stored.parent.resolve() == settings.storage_dir.resolve()
    assert approval.snapshot_filename == "owned.txt"
    assert approval.snapshot_stored_name == f"{approval.id}.txt"


def test_oversized_upload_is_refused(service, settings):
    payload = b"x" * (settings.max_upload_bytes + 1)
    with pytest.raises(ValidationError, match="larger than"):
        service.create(file_draft(content=payload))


def test_upload_at_the_limit_is_accepted(service, settings):
    payload = b"x" * settings.max_upload_bytes
    approval = service.create(file_draft(filename="big.txt", content=payload))
    assert approval.snapshot_size == settings.max_upload_bytes


def test_oversized_text_is_refused(service, settings):
    with pytest.raises(ValidationError, match="character limit"):
        service.create(text_draft(text="x" * (settings.max_text_chars + 1)))


def test_client_supplied_media_type_is_ignored(service):
    approval = service.create(file_draft(filename="notes.txt", content=b"hi"))
    assert approval.snapshot_media_type == "text/plain"
    assert media_type_for("notes.txt") == "text/plain"


# -- storage -------------------------------------------------------------

@pytest.mark.parametrize(
    "name", ["../escape.txt", "sub/dir.txt", "..\\win.txt", "", "a/../../b.txt"]
)
def test_storage_rejects_unsafe_stored_names(tmp_path, name):
    storage = SnapshotStorage(tmp_path)
    with pytest.raises(StorageError):
        storage.path_for(name)


def test_storage_refuses_non_allowlisted_extension(tmp_path):
    storage = SnapshotStorage(tmp_path)
    with pytest.raises(StorageError):
        storage.stored_name("abc123", "thing.exe")


# -- tokens --------------------------------------------------------------

def test_token_entropy_floor():
    with pytest.raises(ValueError):
        generate_review_token(8)


def test_tokens_equal_is_exact():
    token = generate_review_token()
    assert tokens_equal(token, token) is True
    assert tokens_equal(token, token[:-1] + "x") is False
    assert tokens_equal(token, token + "x") is False
