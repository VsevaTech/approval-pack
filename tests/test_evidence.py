"""Evidence generation, including the hash chain that is the whole point."""

from __future__ import annotations

import hashlib
import json

from app.evidence import build_evidence, evidence_html, evidence_json
from app.models import DecisionType
from tests.factories import SAMPLE_TEXT, file_draft, make_text_approval, text_draft


def test_evidence_for_pending_approval(service):
    approval = make_text_approval(service)
    data = build_evidence(approval)

    assert data["approval_id"] == approval.id
    assert data["status"] == "PENDING"
    assert data["decision"] is None
    assert data["decided_at"] is None
    assert data["decided_snapshot_sha256"] is None
    assert data["snapshot"]["sha256"] == approval.snapshot_sha256


def test_evidence_contains_every_required_field(service):
    approval = make_text_approval(service)
    service.record_decision(
        approval,
        decision=DecisionType.APPROVED,
        comment="Approved for Q4",
        reviewer_name="Anna Weber",
        reviewer_email="anna@example.com",
    )
    data = build_evidence(approval, review_url=service.review_url(approval))

    assert data["approval_id"]
    assert data["title"] == "Marketing campaign proposal"
    assert data["decision"] == "APPROVED"
    assert data["created_at"]
    assert data["decided_at"]
    assert data["reviewer"] == {"name": "Anna Weber", "email": "anna@example.com"}
    assert data["comment"] == "Approved for Q4"
    assert data["snapshot"]["sha256"] == approval.snapshot_sha256


def test_evidence_json_is_valid_json(service):
    approval = make_text_approval(service)
    service.record_decision(approval, decision=DecisionType.APPROVED)

    parsed = json.loads(evidence_json(approval))
    assert parsed["schema"] == "approval-pack/evidence/v1"
    assert "not an electronic signature" in parsed["disclaimer"]


def test_evidence_html_is_self_contained_and_escaped(service):
    approval = service.create(
        text_draft(title="<script>alert(1)</script>", text="<b>bold</b> & co")
    )
    service.record_decision(
        approval, decision=DecisionType.REJECTED, comment="<img src=x onerror=1>"
    )
    html_doc = evidence_html(approval)

    assert "<script>alert(1)</script>" not in html_doc
    assert "&lt;script&gt;" in html_doc
    assert "onerror" not in html_doc.replace("&lt;img src=x onerror=1&gt;", "")
    assert "http://" not in html_doc.split("</head>")[0].replace(
        'xmlns="http://www.w3.org/2000/svg"', ""
    )
    assert "MATCH" in html_doc


def test_evidence_states_rejection_details(service):
    approval = make_text_approval(service)
    service.record_decision(
        approval, decision=DecisionType.REJECTED, comment="Budget too high"
    )
    data = build_evidence(approval)

    assert data["status"] == "REJECTED"
    assert data["decision"] == "REJECTED"
    assert data["comment"] == "Budget too high"


def test_hash_chain_text_snapshot(service):
    """create snapshot -> hash -> approve -> evidence hash == original hash."""
    original_hash = hashlib.sha256(SAMPLE_TEXT.encode("utf-8")).hexdigest()

    approval = make_text_approval(service)
    assert approval.snapshot_sha256 == original_hash

    service.record_decision(approval, decision=DecisionType.APPROVED, comment="go")

    data = build_evidence(approval)
    assert data["snapshot"]["sha256"] == original_hash
    assert data["decided_snapshot_sha256"] == original_hash
    assert data["decided_snapshot_sha256"] == data["snapshot"]["sha256"]
    # And the stored bytes still hash to the same value.
    assert hashlib.sha256(service.snapshot_bytes(approval)).hexdigest() == original_hash


def test_hash_chain_file_snapshot(service):
    payload = b"%PDF-1.4 vendor quote, EUR 2500"
    original_hash = hashlib.sha256(payload).hexdigest()

    approval = service.create(file_draft(content=payload))
    assert approval.snapshot_sha256 == original_hash

    service.record_decision(approval, decision=DecisionType.APPROVED)

    data = build_evidence(approval)
    assert data["decided_snapshot_sha256"] == original_hash
    assert data["snapshot"]["sha256"] == original_hash
    assert service.storage.read(approval.snapshot_stored_name) == payload


def test_hash_chain_survives_an_edit_before_the_decision(service):
    approval = make_text_approval(service)
    service.update_snapshot_text(approval, "Budget: EUR 3,000")
    version_two_hash = hashlib.sha256(b"Budget: EUR 3,000").hexdigest()

    service.record_decision(approval, decision=DecisionType.APPROVED)
    data = build_evidence(approval)

    # The evidence pins version two -- the version actually shown and approved.
    assert data["decided_snapshot_sha256"] == version_two_hash
    assert data["snapshot"]["sha256"] == version_two_hash
