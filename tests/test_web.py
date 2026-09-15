"""HTTP-level tests against the real ASGI app."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta

import pytest

REVIEW_LINK = re.compile(r'value="(http://testserver/review/([^"]+))"')


def create_via_http(client, **overrides):
    payload = {
        "title": "Marketing campaign proposal",
        "description": "Q4 launch budget and date.",
        "text": "Budget: EUR 2,500\nLaunch date: 1 October",
    }
    payload.update(overrides)
    response = client.post("/approvals", data=payload, follow_redirects=False)
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    approval_id = location.split("/approvals/")[1].split("?")[0]
    detail = client.get(location)
    match = REVIEW_LINK.search(detail.text)
    assert match, "review link missing from the detail page"
    return approval_id, match.group(2), detail


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_pages_render(client):
    assert client.get("/").status_code == 200
    assert client.get("/approvals/new").status_code == 200


def test_security_headers_are_set(client):
    headers = client.get("/").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in headers["content-security-policy"]
    assert "'unsafe-inline'" not in headers["content-security-policy"]


def test_create_requires_title(client):
    response = client.post("/approvals", data={"title": "", "text": "x"})
    assert response.status_code == 400
    assert "Title is required" in response.text


def test_create_requires_content(client):
    response = client.post("/approvals", data={"title": "Empty", "text": ""})
    assert response.status_code == 400


def test_full_journey_approve(client):
    approval_id, token, detail = create_via_http(client)

    assert "PENDING" in detail.text
    assert approval_id not in f"/review/{token}"

    review = client.get(f"/review/{token}")
    assert review.status_code == 200
    assert "Budget: EUR 2,500" in review.text
    assert "Approve" in review.text and "Reject" in review.text

    decided = client.post(
        f"/review/{token}/decision",
        data={"decision": "APPROVED", "comment": "Go ahead", "reviewer_name": "Anna"},
    )
    assert decided.status_code == 200
    assert "Decision recorded: APPROVED" in decided.text

    detail_after = client.get(f"/approvals/{approval_id}")
    assert "APPROVED" in detail_after.text
    assert "MATCH" in detail_after.text

    evidence = client.get(f"/approvals/{approval_id}/evidence.json").json()
    assert evidence["decision"] == "APPROVED"
    assert evidence["comment"] == "Go ahead"
    assert evidence["reviewer"]["name"] == "Anna"
    assert evidence["decided_snapshot_sha256"] == evidence["snapshot"]["sha256"]
    assert evidence["snapshot"]["sha256"] == hashlib.sha256(
        b"Budget: EUR 2,500\nLaunch date: 1 October"
    ).hexdigest()


def test_full_journey_reject(client):
    approval_id, token, _ = create_via_http(client)

    response = client.post(
        f"/review/{token}/decision",
        data={"decision": "REJECTED", "comment": "Budget too high"},
    )
    assert response.status_code == 200
    assert "Decision recorded: REJECTED" in response.text

    evidence = client.get(f"/approvals/{approval_id}/evidence.json").json()
    assert evidence["status"] == "REJECTED"
    assert evidence["comment"] == "Budget too high"


def test_reject_without_comment_returns_400(client):
    approval_id, token, _ = create_via_http(client)

    response = client.post(
        f"/review/{token}/decision", data={"decision": "REJECTED", "comment": ""}
    )
    assert response.status_code == 400
    assert "comment is required" in response.text.lower()

    evidence = client.get(f"/approvals/{approval_id}/evidence.json").json()
    assert evidence["status"] == "PENDING"


def test_second_decision_returns_409(client):
    _, token, _ = create_via_http(client)
    client.post(f"/review/{token}/decision", data={"decision": "APPROVED"})

    response = client.post(
        f"/review/{token}/decision", data={"decision": "REJECTED", "comment": "no"}
    )
    assert response.status_code == 409
    assert "already approved" in response.text.lower()


def test_unknown_decision_value_returns_400(client):
    _, token, _ = create_via_http(client)
    response = client.post(f"/review/{token}/decision", data={"decision": "MAYBE"})
    assert response.status_code == 400


def test_expired_review_link_cannot_decide(client):
    soon = datetime.now(UTC) + timedelta(seconds=1)
    _, token, _ = create_via_http(
        client, expires_at=soon.strftime("%Y-%m-%dT%H:%M:%S")
    )
    import time

    time.sleep(1.1)

    page = client.get(f"/review/{token}")
    assert "EXPIRED" in page.text
    assert "Your decision" not in page.text

    response = client.post(
        f"/review/{token}/decision", data={"decision": "APPROVED"}
    )
    assert response.status_code == 410


def test_expiration_in_the_past_is_refused(client):
    past = datetime.now(UTC) - timedelta(hours=1)
    response = client.post(
        "/approvals",
        data={
            "title": "Late",
            "text": "x",
            "expires_at": past.strftime("%Y-%m-%dT%H:%M"),
        },
    )
    assert response.status_code == 400
    assert "future" in response.text


@pytest.mark.parametrize(
    "token", ["x" * 43, "nope", "../../etc/passwd", "%2e%2e%2fadmin"]
)
def test_invalid_review_token_returns_404(client, token):
    response = client.get(f"/review/{token}")
    assert response.status_code == 404
    assert "not found" in response.text.lower()


def test_unknown_approval_id_returns_404(client):
    assert client.get("/approvals/" + "0" * 32).status_code == 404
    assert client.get(f"/approvals/{'0' * 32}/evidence.json").status_code == 404


def test_htmx_request_swaps_only_the_decision_fragment(client):
    _, token, _ = create_via_http(client)
    response = client.post(
        f"/review/{token}/decision",
        data={"decision": "APPROVED"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "Decision recorded: APPROVED" in response.text
    assert "<html" not in response.text


def test_snapshot_text_is_escaped_in_the_review_page(client):
    _, token, _ = create_via_http(
        client, text="<script>alert('xss')</script>", title="XSS attempt"
    )
    page = client.get(f"/review/{token}")
    assert "<script>alert('xss')</script>" not in page.text
    assert "&lt;script&gt;" in page.text


def test_file_upload_journey(client):
    response = client.post(
        "/approvals",
        data={"title": "Vendor quote", "description": "", "text": ""},
        files={"file": ("quote v1.pdf", b"%PDF-1.4 quote", "application/pdf")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    approval_id = response.headers["location"].split("/approvals/")[1].split("?")[0]
    detail = client.get(f"/approvals/{approval_id}")
    token = REVIEW_LINK.search(detail.text).group(2)

    assert "quote_v1.pdf" in detail.text

    download = client.get(f"/review/{token}/file")
    assert download.status_code == 200
    assert download.content == b"%PDF-1.4 quote"
    assert download.headers["content-disposition"].startswith("attachment")
    assert download.headers["x-content-type-options"] == "nosniff"

    evidence = client.get(f"/approvals/{approval_id}/evidence.json").json()
    assert evidence["snapshot"]["sha256"] == hashlib.sha256(b"%PDF-1.4 quote").hexdigest()


def test_uploaded_html_is_refused_over_http(client):
    response = client.post(
        "/approvals",
        data={"title": "Payload", "text": ""},
        files={"file": ("payload.html", b"<script>steal()</script>", "text/html")},
    )
    assert response.status_code == 400
    assert "not accepted" in response.text


def test_uploaded_file_is_never_served_as_html(client):
    response = client.post(
        "/approvals",
        data={"title": "Notes", "text": ""},
        files={"file": ("notes.txt", b"<h1>hi</h1>", "text/html")},
        follow_redirects=False,
    )
    approval_id = response.headers["location"].split("/approvals/")[1].split("?")[0]
    download = client.get(f"/approvals/{approval_id}/file")

    assert "text/html" not in download.headers["content-type"]
    assert download.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in download.headers["content-security-policy"]


def test_oversized_upload_is_refused_over_http(client, settings):
    response = client.post(
        "/approvals",
        data={"title": "Huge", "text": ""},
        files={"file": ("big.txt", b"x" * (settings.max_upload_bytes + 10), "text/plain")},
    )
    assert response.status_code == 400
    assert "larger than" in response.text


def test_evidence_html_downloads_as_attachment(client):
    approval_id, token, _ = create_via_http(client)
    client.post(f"/review/{token}/decision", data={"decision": "APPROVED"})

    response = client.get(f"/approvals/{approval_id}/evidence.html")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert "Approval evidence" in response.text
    assert "not an electronic signature" in response.text


def test_listing_shows_the_approval(client):
    approval_id, _, _ = create_via_http(client)
    listing = client.get("/")
    assert approval_id in listing.text
    assert "Marketing campaign proposal" in listing.text
