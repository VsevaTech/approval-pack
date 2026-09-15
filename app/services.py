"""Business rules: creating approvals, recording decisions, reading evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.immutability import SnapshotImmutableError
from app.models import (
    Approval,
    ApprovalStatus,
    Decision,
    DecisionType,
    SnapshotKind,
    utcnow,
)
from app.security import (
    generate_review_token,
    is_allowed_extension,
    media_type_for,
    new_id,
    sanitize_filename,
    sha256_bytes,
    sha256_text,
    tokens_equal,
)
from app.storage import SnapshotStorage


class ApprovalError(RuntimeError):
    """Base class for expected, user-facing failures."""


class ValidationError(ApprovalError):
    pass


class NotFoundError(ApprovalError):
    pass


class AlreadyDecidedError(ApprovalError):
    pass


class ExpiredError(ApprovalError):
    pass


@dataclass(slots=True)
class UploadedFile:
    filename: str | None
    content: bytes


@dataclass(slots=True)
class ApprovalDraft:
    title: str
    description: str = ""
    text: str | None = None
    upload: UploadedFile | None = None
    reviewer_name: str | None = None
    reviewer_email: str | None = None
    expires_at: datetime | None = None


def _clean(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return value[:limit]


class ApprovalService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.storage = SnapshotStorage(settings.storage_dir)

    # ------------------------------------------------------------------
    # creation
    # ------------------------------------------------------------------
    def create(self, draft: ApprovalDraft) -> Approval:
        title = _clean(draft.title, 200)
        if not title:
            raise ValidationError("Title is required.")

        has_text = bool(draft.text and draft.text.strip())
        has_file = bool(draft.upload and draft.upload.content)
        if has_text and has_file:
            raise ValidationError("Provide either text or a file, not both.")
        if not has_text and not has_file:
            raise ValidationError("Add the text or the file you need approved.")

        if draft.expires_at is not None:
            expires_at = draft.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= utcnow():
                raise ValidationError("Expiration date must be in the future.")
        else:
            expires_at = None

        approval_id = new_id()
        approval = Approval(
            id=approval_id,
            review_token=self._unique_token(),
            title=title,
            description=(_clean(draft.description, 10_000) or ""),
            reviewer_name=_clean(draft.reviewer_name, 120),
            reviewer_email=_clean(draft.reviewer_email, 254),
            status=ApprovalStatus.PENDING,
            created_at=utcnow(),
            expires_at=expires_at,
        )

        if has_text:
            text = draft.text or ""
            if len(text) > self.settings.max_text_chars:
                raise ValidationError(
                    f"Text snapshot is larger than the {self.settings.max_text_chars}"
                    " character limit."
                )
            approval.snapshot_kind = SnapshotKind.TEXT
            approval.snapshot_text = text
            approval.snapshot_size = len(text.encode("utf-8"))
            approval.snapshot_media_type = "text/plain; charset=utf-8"
            approval.snapshot_sha256 = sha256_text(text)
        else:
            upload = draft.upload
            assert upload is not None
            payload = upload.content
            if len(payload) > self.settings.max_upload_bytes:
                raise ValidationError(
                    "File is larger than the "
                    f"{self.settings.max_upload_bytes // 1024} KiB limit."
                )
            safe_name = sanitize_filename(upload.filename)
            if not is_allowed_extension(safe_name):
                raise ValidationError(
                    "This file type is not accepted. Executable or scriptable "
                    "formats (html, js, svg, ...) are refused on purpose."
                )
            stored_name = self.storage.stored_name(approval_id, safe_name)
            approval.snapshot_kind = SnapshotKind.FILE
            approval.snapshot_filename = safe_name
            approval.snapshot_stored_name = stored_name
            approval.snapshot_media_type = media_type_for(safe_name)
            approval.snapshot_size = len(payload)
            approval.snapshot_sha256 = sha256_bytes(payload)
            self.storage.write(stored_name, payload)

        self.session.add(approval)
        self.session.commit()
        self.session.refresh(approval)
        return approval

    def _unique_token(self) -> str:
        for _ in range(8):
            token = generate_review_token(self.settings.review_token_bytes)
            exists = self.session.scalar(
                select(Approval.id).where(Approval.review_token == token)
            )
            if exists is None:
                return token
        raise RuntimeError("could not generate a unique review token")  # pragma: no cover

    # ------------------------------------------------------------------
    # lookups
    # ------------------------------------------------------------------
    def list_approvals(self, limit: int = 100) -> list[Approval]:
        stmt = select(Approval).order_by(Approval.created_at.desc()).limit(limit)
        return list(self.session.scalars(stmt))

    def get(self, approval_id: str) -> Approval:
        approval = self.session.get(Approval, approval_id)
        if approval is None:
            raise NotFoundError("Approval not found.")
        return approval

    def get_by_token(self, token: str) -> Approval:
        """Look up a review link.

        The indexed lookup is followed by a constant-time comparison so the
        result never depends on how much of the token was guessed.
        """
        if not token or len(token) < 32:
            raise NotFoundError("Invalid review link.")
        approval = self.session.scalar(
            select(Approval).where(Approval.review_token == token)
        )
        if approval is None or not tokens_equal(approval.review_token, token):
            raise NotFoundError("Invalid review link.")
        return approval

    def review_url(self, approval: Approval) -> str:
        return f"{self.settings.base_url.rstrip('/')}/review/{approval.review_token}"

    # ------------------------------------------------------------------
    # decisions
    # ------------------------------------------------------------------
    def record_decision(
        self,
        approval: Approval,
        *,
        decision: DecisionType,
        comment: str | None = None,
        reviewer_name: str | None = None,
        reviewer_email: str | None = None,
        now: datetime | None = None,
    ) -> Decision:
        now = now or utcnow()

        if approval.is_decided:
            raise AlreadyDecidedError(
                f"This approval was already {approval.status.value.lower()}."
            )
        if approval.is_expired(now):
            raise ExpiredError("This approval link has expired.")

        comment = _clean(comment, 5_000)
        if decision is DecisionType.REJECTED and not comment:
            raise ValidationError("A comment is required when rejecting.")

        record = Decision(
            id=new_id(),
            approval_id=approval.id,
            decision=decision,
            reviewer_name=_clean(reviewer_name, 120) or approval.reviewer_name,
            reviewer_email=_clean(reviewer_email, 254) or approval.reviewer_email,
            comment=comment,
            decided_at=now,
            # Bind the decision to the exact snapshot version that was shown.
            snapshot_sha256=approval.snapshot_sha256,
        )
        approval.status = (
            ApprovalStatus.APPROVED
            if decision is DecisionType.APPROVED
            else ApprovalStatus.REJECTED
        )
        approval.decision = record
        self.session.add(record)
        self.session.commit()
        self.session.refresh(approval)
        return record

    # ------------------------------------------------------------------
    # editing (only ever allowed while PENDING)
    # ------------------------------------------------------------------
    def update_snapshot_text(self, approval: Approval, text: str) -> Approval:
        if approval.is_decided:
            raise AlreadyDecidedError(
                "The snapshot is frozen: a decision has been recorded."
            )
        if approval.snapshot_kind is not SnapshotKind.TEXT:
            raise ValidationError("This approval does not hold a text snapshot.")
        approval.snapshot_text = text
        approval.snapshot_size = len(text.encode("utf-8"))
        approval.snapshot_sha256 = sha256_text(text)
        self.session.commit()
        self.session.refresh(approval)
        return approval

    # ------------------------------------------------------------------
    # integrity
    # ------------------------------------------------------------------
    def snapshot_bytes(self, approval: Approval) -> bytes:
        if approval.snapshot_kind is SnapshotKind.TEXT:
            return (approval.snapshot_text or "").encode("utf-8")
        if not approval.snapshot_stored_name:
            raise NotFoundError("Snapshot file is missing.")
        return self.storage.read(approval.snapshot_stored_name)

    def verify_integrity(self, approval: Approval) -> bool:
        """Recompute the hash from stored content and compare."""
        return sha256_bytes(self.snapshot_bytes(approval)) == approval.snapshot_sha256


__all__ = [
    "AlreadyDecidedError",
    "ApprovalDraft",
    "ApprovalError",
    "ApprovalService",
    "ExpiredError",
    "NotFoundError",
    "SnapshotImmutableError",
    "UploadedFile",
    "ValidationError",
]
