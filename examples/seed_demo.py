#!/usr/bin/env python3
"""Create the demo approval and print its review link.

    python examples/seed_demo.py

Run it against the same configuration the server uses (same .env / same
environment variables), then open the printed link in another browser.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db import get_session_factory, init_db
from app.services import ApprovalDraft, ApprovalService
from app.storage import SnapshotStorage

DEMO_TITLE = "Marketing campaign proposal"
DEMO_DESCRIPTION = (
    "Q4 campaign. Please confirm the budget and the launch date before we book "
    "the media slots."
)
DEMO_TEXT = "Budget: EUR 2,500\nLaunch date: 1 October"


def main() -> int:
    settings = get_settings()
    init_db()
    SnapshotStorage(settings.storage_dir).ensure_ready()

    with get_session_factory()() as session:
        service = ApprovalService(session, settings)
        approval = service.create(
            ApprovalDraft(
                title=DEMO_TITLE,
                description=DEMO_DESCRIPTION,
                text=DEMO_TEXT,
                reviewer_name="Anna Weber",
                reviewer_email="anna@example.com",
            )
        )

        print("Demo approval created.")
        print(f"  Approval ID : {approval.id}")
        print(f"  Status      : {approval.effective_status.value}")
        print(f"  SHA-256     : {approval.snapshot_sha256}")
        print(f"  Owner page  : {settings.base_url.rstrip('/')}/approvals/{approval.id}")
        print(f"  Review link : {service.review_url(approval)}")
        print()
        print("Open the review link in a private window, approve it, then reload")
        print("the owner page and download the evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
