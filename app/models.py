"""SQLAlchemy 2.0 models.

Design notes
------------
* ``Approval.id`` is a random UUID4 hex string: never a sequential integer, so
  nothing guessable ever ends up in a URL.
* ``Approval.review_token`` is a separate, independently random capability used
  for the public ``/review/<token>`` URL.
* Once a :class:`Decision` exists for an approval, the snapshot columns are
  frozen by an ORM-level guard (see :mod:`app.immutability`).
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Timezone-aware UTC now (SQLite stores naive values, so we normalise)."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ApprovalStatus(enum.StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class DecisionType(enum.StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SnapshotKind(enum.StrEnum):
    TEXT = "TEXT"
    FILE = "FILE"


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_review_token", "review_token", unique=True),
        CheckConstraint("length(review_token) >= 32", name="ck_token_length"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    review_token: Mapped[str] = mapped_column(String(128), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    reviewer_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewer_email: Mapped[str | None] = mapped_column(String(254), nullable=True)

    snapshot_kind: Mapped[SnapshotKind] = mapped_column(
        Enum(SnapshotKind, native_enum=False, length=8), nullable=False
    )
    #: Populated for TEXT snapshots.
    snapshot_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Sanitised original file name, shown to the reviewer (FILE snapshots).
    snapshot_filename: Mapped[str | None] = mapped_column(String(160), nullable=True)
    #: Name on disk. Derived from the approval id only — never from user input.
    snapshot_stored_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_media_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    snapshot_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Lowercase hex SHA-256 of the exact snapshot bytes.
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, native_enum=False, length=8),
        nullable=False,
        default=ApprovalStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    decision: Mapped["Decision | None"] = relationship(
        back_populates="approval",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # -- derived helpers -------------------------------------------------

    @staticmethod
    def _aware(value: datetime | None) -> datetime | None:
        """SQLite hands back naive datetimes; treat them as UTC."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    @property
    def created_at_utc(self) -> datetime:
        return self._aware(self.created_at)  # type: ignore[return-value]

    @property
    def expires_at_utc(self) -> datetime | None:
        return self._aware(self.expires_at)

    def is_expired(self, now: datetime | None = None) -> bool:
        expires = self.expires_at_utc
        if expires is None:
            return False
        return (now or utcnow()) >= expires

    @property
    def effective_status(self) -> ApprovalStatus:
        """Status as seen by users.

        A pending approval past its expiry reads as ``EXPIRED`` without needing
        a background job; a decided approval keeps its decision forever.
        """
        if self.status is ApprovalStatus.PENDING and self.is_expired():
            return ApprovalStatus.EXPIRED
        return self.status

    @property
    def is_decided(self) -> bool:
        return self.status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    approval_id: Mapped[str] = mapped_column(
        ForeignKey("approvals.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    decision: Mapped[DecisionType] = mapped_column(
        Enum(DecisionType, native_enum=False, length=8), nullable=False
    )
    reviewer_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewer_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    #: Hash of the snapshot at the moment the decision was made. Compared with
    #: ``Approval.snapshot_sha256`` this proves which version was decided on.
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    approval: Mapped[Approval] = relationship(back_populates="decision")

    @property
    def decided_at_utc(self) -> datetime:
        value = self.decided_at
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
