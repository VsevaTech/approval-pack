"""Small helpers shared by the tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Approval
from app.services import ApprovalDraft, ApprovalService, UploadedFile

SAMPLE_TEXT = "Budget: EUR 2,500\nLaunch date: 1 October"


def text_draft(**overrides: object) -> ApprovalDraft:
    values: dict[str, object] = {
        "title": "Marketing campaign proposal",
        "description": "Q4 launch budget and date.",
        "text": SAMPLE_TEXT,
    }
    values.update(overrides)
    return ApprovalDraft(**values)  # type: ignore[arg-type]


def file_draft(
    filename: str = "proposal.pdf", content: bytes = b"%PDF-1.4 fake pdf bytes", **overrides: object
) -> ApprovalDraft:
    values: dict[str, object] = {
        "title": "Signed proposal",
        "description": "Vendor quote.",
        "upload": UploadedFile(filename=filename, content=content),
    }
    values.update(overrides)
    return ApprovalDraft(**values)  # type: ignore[arg-type]


def make_text_approval(service: ApprovalService, **overrides: object) -> Approval:
    return service.create(text_draft(**overrides))


def in_future(minutes: int = 60) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


def in_past(minutes: int = 60) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)
