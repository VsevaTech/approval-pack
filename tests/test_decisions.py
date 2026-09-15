"""Recording decisions: approve, reject, expiry, finality."""

from __future__ import annotations

import pytest

from app.immutability import SnapshotImmutableError
from app.models import ApprovalStatus, DecisionType
from app.services import (
    AlreadyDecidedError,
    ExpiredError,
    NotFoundError,
    ValidationError,
)
from tests.factories import in_future, in_past, make_text_approval, text_draft


def test_approve_records_decision(service):
    approval = make_text_approval(service)
    original_hash = approval.snapshot_sha256

    decision = service.record_decision(
        approval,
        decision=DecisionType.APPROVED,
        comment="Fine by me",
        reviewer_name="Anna Weber",
        reviewer_email="anna@example.com",
    )

    assert approval.status is ApprovalStatus.APPROVED
    assert approval.effective_status is ApprovalStatus.APPROVED
    assert decision.reviewer_name == "Anna Weber"
    assert decision.reviewer_email == "anna@example.com"
    assert decision.comment == "Fine by me"
    assert decision.decided_at_utc is not None
    assert decision.snapshot_sha256 == original_hash


def test_approve_without_comment_is_allowed(service):
    approval = make_text_approval(service)
    decision = service.record_decision(approval, decision=DecisionType.APPROVED)

    assert approval.status is ApprovalStatus.APPROVED
    assert decision.comment is None


def test_reject_with_comment(service):
    approval = make_text_approval(service)
    decision = service.record_decision(
        approval, decision=DecisionType.REJECTED, comment="Budget too high"
    )

    assert approval.status is ApprovalStatus.REJECTED
    assert decision.decision is DecisionType.REJECTED
    assert decision.comment == "Budget too high"


@pytest.mark.parametrize("comment", [None, "", "   "])
def test_reject_without_comment_is_refused(service, comment):
    approval = make_text_approval(service)

    with pytest.raises(ValidationError, match="comment is required"):
        service.record_decision(
            approval, decision=DecisionType.REJECTED, comment=comment
        )

    assert approval.status is ApprovalStatus.PENDING
    assert approval.decision is None


def test_expired_approval_cannot_be_decided(service, session):
    approval = service.create(text_draft(expires_at=in_future(minutes=1)))
    # Move the deadline into the past without touching snapshot content.
    approval.expires_at = in_past(minutes=5)
    session.commit()

    assert approval.effective_status is ApprovalStatus.EXPIRED

    with pytest.raises(ExpiredError):
        service.record_decision(approval, decision=DecisionType.APPROVED)

    assert approval.status is ApprovalStatus.PENDING
    assert approval.decision is None


def test_decided_approval_ignores_later_expiry(service, session):
    approval = service.create(text_draft(expires_at=in_future(minutes=1)))
    service.record_decision(approval, decision=DecisionType.APPROVED)

    session.expire_all()
    reloaded = service.get(approval.id)
    assert reloaded.effective_status is ApprovalStatus.APPROVED


def test_second_decision_attempt_is_refused(service):
    approval = make_text_approval(service)
    service.record_decision(approval, decision=DecisionType.APPROVED, comment="yes")

    with pytest.raises(AlreadyDecidedError):
        service.record_decision(
            approval, decision=DecisionType.REJECTED, comment="changed my mind"
        )

    assert approval.status is ApprovalStatus.APPROVED
    assert approval.decision is not None
    assert approval.decision.comment == "yes"


def test_decision_falls_back_to_invited_reviewer(service):
    approval = make_text_approval(
        service, reviewer_name="Invited Person", reviewer_email="invited@example.com"
    )
    decision = service.record_decision(approval, decision=DecisionType.APPROVED)

    assert decision.reviewer_name == "Invited Person"
    assert decision.reviewer_email == "invited@example.com"


def test_lookup_by_token(service):
    approval = make_text_approval(service)
    assert service.get_by_token(approval.review_token).id == approval.id


@pytest.mark.parametrize(
    "token",
    ["", "short", "x" * 43, "' OR 1=1 --", "../../etc/passwd"],
)
def test_invalid_token_is_not_found(service, token):
    make_text_approval(service)
    with pytest.raises(NotFoundError):
        service.get_by_token(token)


def test_unknown_approval_id_is_not_found(service):
    with pytest.raises(NotFoundError):
        service.get("0" * 32)


def test_decision_cannot_be_deleted(service, session):
    approval = make_text_approval(service)
    service.record_decision(approval, decision=DecisionType.APPROVED)

    session.delete(approval.decision)
    with pytest.raises(SnapshotImmutableError):
        session.flush()
    session.rollback()
