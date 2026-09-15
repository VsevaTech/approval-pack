"""ORM-level guard making a decided approval's snapshot unchangeable.

The service layer already refuses to touch a decided approval, but the guard
below is the backstop: any code path that mutates a frozen column on a decided
approval raises before the UPDATE reaches the database.
"""

from __future__ import annotations

from sqlalchemy import event, inspect
from sqlalchemy.orm import Mapper, Session

from app.models import Approval, ApprovalStatus

#: Columns that define *what was approved*. Frozen once a decision exists.
FROZEN_COLUMNS: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "snapshot_kind",
        "snapshot_text",
        "snapshot_filename",
        "snapshot_stored_name",
        "snapshot_media_type",
        "snapshot_size",
        "snapshot_sha256",
        "review_token",
        "created_at",
        "expires_at",
        "id",
    }
)

DECIDED = (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED)


class SnapshotImmutableError(RuntimeError):
    """Raised when a decided approval's content is modified."""


def _changed_frozen_columns(target: Approval) -> list[str]:
    state = inspect(target)
    changed: list[str] = []
    for name in FROZEN_COLUMNS:
        attribute = state.attrs[name]
        history = attribute.load_history()
        if history.has_changes():
            changed.append(name)
    return sorted(changed)


def _before_update(_mapper: Mapper, _connection, target: Approval) -> None:
    state = inspect(target)
    status_history = state.attrs["status"].load_history()

    # The status column itself flips from PENDING to APPROVED/REJECTED exactly
    # once, in the same flush that records the decision. That transition is the
    # only permitted write to a decided approval.
    was_decided = target.status in DECIDED
    if status_history.has_changes() and status_history.deleted:
        previous = status_history.deleted[0]
        was_decided = previous in DECIDED

    if not was_decided:
        return

    changed = _changed_frozen_columns(target)
    if changed:
        raise SnapshotImmutableError(
            "approval "
            f"{target.id} already has a recorded decision; "
            f"immutable field(s) changed: {', '.join(changed)}"
        )
    if status_history.has_changes():
        raise SnapshotImmutableError(
            f"approval {target.id} already has a recorded decision; status is final"
        )


def _before_delete_decision(session: Session, flush_context, instances) -> None:  # noqa: ARG001
    from app.models import Decision

    for obj in session.deleted:
        if isinstance(obj, Decision) and obj.approval_id is not None:
            approval = session.get(Approval, obj.approval_id)
            if approval is not None and approval.status in DECIDED:
                raise SnapshotImmutableError(
                    f"decision for approval {obj.approval_id} cannot be deleted"
                )


def install_guards() -> None:
    """Idempotently register the immutability listeners."""
    if not event.contains(Approval, "before_update", _before_update):
        event.listen(Approval, "before_update", _before_update)
    if not event.contains(Session, "before_flush", _before_delete_decision):
        event.listen(Session, "before_flush", _before_delete_decision)


install_guards()
