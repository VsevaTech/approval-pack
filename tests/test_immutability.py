"""Once decided, the snapshot must not move."""

from __future__ import annotations

import pytest
from sqlalchemy import text as sql_text

from app.immutability import SnapshotImmutableError
from app.models import ApprovalStatus, DecisionType
from app.services import AlreadyDecidedError
from tests.factories import make_text_approval


def test_service_refuses_edit_after_decision(service):
    approval = make_text_approval(service)
    service.record_decision(approval, decision=DecisionType.APPROVED)

    with pytest.raises(AlreadyDecidedError):
        service.update_snapshot_text(approval, "sneaky new budget: EUR 25,000")


def test_edit_is_allowed_while_pending(service):
    approval = make_text_approval(service)
    first_hash = approval.snapshot_sha256

    service.update_snapshot_text(approval, "Budget: EUR 3,000")

    assert approval.snapshot_sha256 != first_hash
    assert service.verify_integrity(approval) is True


def test_orm_guard_blocks_direct_snapshot_mutation(service, session):
    approval = make_text_approval(service)
    service.record_decision(approval, decision=DecisionType.APPROVED, comment="ok")

    approval.snapshot_text = "tampered"
    with pytest.raises(SnapshotImmutableError, match="snapshot_text"):
        session.flush()
    session.rollback()


def test_orm_guard_blocks_hash_rewrite(service, session):
    approval = make_text_approval(service)
    service.record_decision(approval, decision=DecisionType.REJECTED, comment="no")

    approval.snapshot_sha256 = "0" * 64
    with pytest.raises(SnapshotImmutableError, match="snapshot_sha256"):
        session.flush()
    session.rollback()


def test_orm_guard_blocks_status_reset(service, session):
    approval = make_text_approval(service)
    service.record_decision(approval, decision=DecisionType.APPROVED)

    approval.status = ApprovalStatus.PENDING
    with pytest.raises(SnapshotImmutableError, match="status is final"):
        session.flush()
    session.rollback()


def test_orm_guard_blocks_token_rotation_after_decision(service, session):
    approval = make_text_approval(service)
    service.record_decision(approval, decision=DecisionType.APPROVED)

    approval.review_token = "a" * 43
    with pytest.raises(SnapshotImmutableError, match="review_token"):
        session.flush()
    session.rollback()


def test_tampering_underneath_the_app_is_detectable(service, session):
    """Raw SQL bypasses the ORM guard; the hash check still catches it."""
    approval = make_text_approval(service)
    service.record_decision(approval, decision=DecisionType.APPROVED)
    recorded_hash = approval.decision.snapshot_sha256

    session.execute(
        sql_text("UPDATE approvals SET snapshot_text = :t WHERE id = :i"),
        {"t": "Budget: EUR 25,000", "i": approval.id},
    )
    session.commit()
    session.expire_all()

    tampered = service.get(approval.id)
    assert service.verify_integrity(tampered) is False
    assert tampered.decision.snapshot_sha256 == recorded_hash


def test_file_snapshot_tampering_is_detectable(service):
    from tests.factories import file_draft

    approval = service.create(file_draft(content=b"original quote"))
    service.record_decision(approval, decision=DecisionType.APPROVED)

    path = service.storage.path_for(approval.snapshot_stored_name)
    path.write_bytes(b"swapped quote")

    assert service.verify_integrity(approval) is False
