"""Creating approvals: validation, snapshots, tokens."""

from __future__ import annotations

import hashlib

import pytest

from app.models import ApprovalStatus, SnapshotKind
from app.services import ApprovalDraft, ValidationError
from tests.factories import SAMPLE_TEXT, file_draft, in_future, in_past, text_draft


def test_create_text_approval(service):
    approval = service.create(text_draft())

    assert approval.id and len(approval.id) == 32
    assert approval.status is ApprovalStatus.PENDING
    assert approval.effective_status is ApprovalStatus.PENDING
    assert approval.snapshot_kind is SnapshotKind.TEXT
    assert approval.snapshot_text == SAMPLE_TEXT
    assert approval.snapshot_size == len(SAMPLE_TEXT.encode("utf-8"))
    assert approval.decision is None


def test_create_file_approval_stores_snapshot(service):
    approval = service.create(file_draft(content=b"quote v3"))

    assert approval.snapshot_kind is SnapshotKind.FILE
    assert approval.snapshot_filename == "proposal.pdf"
    # Stored name is derived from the approval id, never from user input.
    assert approval.snapshot_stored_name == f"{approval.id}.pdf"
    assert service.storage.read(approval.snapshot_stored_name) == b"quote v3"
    assert approval.snapshot_media_type == "application/pdf"


def test_approval_id_is_not_sequential(service):
    ids = {service.create(text_draft()).id for _ in range(10)}
    assert len(ids) == 10
    assert all(not i.isdigit() for i in ids)


def test_review_token_is_unique_and_unpredictable(service):
    approvals = [service.create(text_draft()) for _ in range(25)]
    tokens = {a.review_token for a in approvals}

    assert len(tokens) == 25
    for token in tokens:
        # 32 random bytes base64url-encoded == 43 characters.
        assert len(token) >= 43
        assert token.isascii()
    # No two tokens share a long prefix -- a crude but effective randomness smoke test.
    prefixes = {t[:12] for t in tokens}
    assert len(prefixes) == 25


def test_sha256_matches_text_content(service):
    approval = service.create(text_draft())
    expected = hashlib.sha256(SAMPLE_TEXT.encode("utf-8")).hexdigest()

    assert approval.snapshot_sha256 == expected
    assert service.verify_integrity(approval) is True


def test_sha256_matches_file_content(service):
    payload = b"binary\x00content\xff"
    approval = service.create(file_draft(content=payload))

    assert approval.snapshot_sha256 == hashlib.sha256(payload).hexdigest()
    assert service.verify_integrity(approval) is True


def test_title_is_required(service):
    with pytest.raises(ValidationError, match="Title"):
        service.create(text_draft(title="   "))


def test_content_is_required(service):
    with pytest.raises(ValidationError, match="Add the text or the file"):
        service.create(ApprovalDraft(title="Empty"))


def test_text_and_file_are_mutually_exclusive(service):
    draft = file_draft()
    draft.text = "also text"
    with pytest.raises(ValidationError, match="not both"):
        service.create(draft)


def test_expiration_must_be_in_the_future(service):
    with pytest.raises(ValidationError, match="future"):
        service.create(text_draft(expires_at=in_past()))


def test_future_expiration_is_accepted(service):
    approval = service.create(text_draft(expires_at=in_future()))
    assert approval.expires_at_utc is not None
    assert approval.is_expired() is False


def test_review_url_uses_token_not_id(service, settings):
    approval = service.create(text_draft())
    url = service.review_url(approval)

    assert url == f"{settings.base_url}/review/{approval.review_token}"
    assert approval.id not in url
