"""Evidence records — the downloadable proof of what was approved."""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

from app import __version__
from app.models import Approval

DISCLAIMER = (
    "Approval Pack records an immutable snapshot and the decision made on it. "
    "It is not an electronic signature and carries no legal force as a "
    "qualified/advanced e-signature or certified document-workflow record."
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def build_evidence(approval: Approval, *, review_url: str | None = None) -> dict[str, Any]:
    """The evidence payload. Field names are stable — treat this as an API."""
    decision = approval.decision
    return {
        "schema": "approval-pack/evidence/v1",
        "generator": f"Approval Pack {__version__}",
        "approval_id": approval.id,
        "title": approval.title,
        "description": approval.description,
        "status": approval.effective_status.value,
        "decision": decision.decision.value if decision else None,
        "created_at": _iso(approval.created_at_utc),
        "expires_at": _iso(approval.expires_at_utc),
        "decided_at": _iso(decision.decided_at_utc) if decision else None,
        "reviewer": {
            "name": (decision.reviewer_name if decision else approval.reviewer_name),
            "email": (decision.reviewer_email if decision else approval.reviewer_email),
        },
        "comment": decision.comment if decision else None,
        "snapshot": {
            "kind": approval.snapshot_kind.value,
            "filename": approval.snapshot_filename,
            "media_type": approval.snapshot_media_type,
            "size_bytes": approval.snapshot_size,
            "sha256": approval.snapshot_sha256,
        },
        # Hash captured when the decision was recorded. It must equal
        # snapshot.sha256 — that equality is the whole point of the product.
        "decided_snapshot_sha256": decision.snapshot_sha256 if decision else None,
        "review_url": review_url,
        "disclaimer": DISCLAIMER,
    }


def evidence_json(approval: Approval, *, review_url: str | None = None) -> str:
    return json.dumps(
        build_evidence(approval, review_url=review_url), indent=2, ensure_ascii=False
    )


def _row(label: str, value: Any) -> str:
    shown = "—" if value in (None, "") else html.escape(str(value))
    return f"<tr><th>{html.escape(label)}</th><td>{shown}</td></tr>"


def evidence_html(approval: Approval, *, review_url: str | None = None) -> str:
    """Self-contained HTML evidence: no scripts, no external references."""
    data = build_evidence(approval, review_url=review_url)
    snapshot = data["snapshot"]
    reviewer = data["reviewer"]
    match = (
        data["decided_snapshot_sha256"] == snapshot["sha256"]
        if data["decided_snapshot_sha256"]
        else None
    )
    verdict = {
        True: "MATCH — the decided version is the stored version.",
        False: "MISMATCH — stored content differs from what was decided on.",
        None: "No decision recorded yet.",
    }[match]

    rows = "".join(
        [
            _row("Approval ID", data["approval_id"]),
            _row("Title", data["title"]),
            _row("Description", data["description"]),
            _row("Status", data["status"]),
            _row("Decision", data["decision"]),
            _row("Created at (UTC)", data["created_at"]),
            _row("Expires at (UTC)", data["expires_at"]),
            _row("Decided at (UTC)", data["decided_at"]),
            _row("Reviewer name", reviewer["name"]),
            _row("Reviewer email", reviewer["email"]),
            _row("Comment", data["comment"]),
            _row("Snapshot kind", snapshot["kind"]),
            _row("Snapshot file", snapshot["filename"]),
            _row("Snapshot size (bytes)", snapshot["size_bytes"]),
            _row("SHA-256 of snapshot", snapshot["sha256"]),
            _row("SHA-256 recorded at decision", data["decided_snapshot_sha256"]),
            _row("Hash check", verdict),
        ]
    )

    generator = html.escape(data["generator"])
    schema = html.escape(data["schema"])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Approval evidence — {html.escape(data["title"])}</title>
<style>
  body {{ font: 15px/1.55 -apple-system, "Segoe UI", Roboto, sans-serif;
         margin: 2rem auto; max-width: 52rem; color: #16202c; padding: 0 1rem; }}
  h1 {{ font-size: 1.35rem; margin-bottom: .25rem; }}
  .sub {{ color: #5b6b7d; margin-top: 0; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 1.25rem; }}
  th, td {{ border: 1px solid #d8e0e8; padding: .55rem .7rem; text-align: left;
            vertical-align: top; word-break: break-word; }}
  th {{ width: 16rem; background: #f4f7fa; font-weight: 600; }}
  code {{ font-family: ui-monospace, Menlo, Consolas, monospace; }}
  .note {{ margin-top: 1.5rem; padding: .85rem 1rem; background: #fff8e6;
           border: 1px solid #f0dca8; border-radius: 6px; font-size: .9rem; }}
</style>
</head>
<body>
<h1>Approval evidence</h1>
<p class="sub">{generator} · schema <code>{schema}</code></p>
<table>{rows}</table>
<p class="note"><strong>Disclaimer.</strong> {html.escape(DISCLAIMER)}</p>
</body>
</html>
"""
