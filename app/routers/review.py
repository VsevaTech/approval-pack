"""Public, tokenised reviewer routes. No account, no registration."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request, Response, status
from fastapi.responses import HTMLResponse

from app.deps import ServiceDep
from app.models import Approval, DecisionType, SnapshotKind
from app.security import INLINE_MEDIA_TYPES
from app.services import (
    AlreadyDecidedError,
    ApprovalService,
    ExpiredError,
    NotFoundError,
    ValidationError,
)
from app.templating import templates

router = APIRouter(prefix="/review")

#: Headers applied to every snapshot download. `nosniff` plus a locked-down CSP
#: plus `attachment` means an uploaded file can never execute in our origin.
DOWNLOAD_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "X-Frame-Options": "DENY",
    "Cache-Control": "private, no-store",
}


def _not_found(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "heading": "Link not found",
            "message": (
                "This review link is invalid, or the approval it pointed to no "
                "longer exists."
            ),
        },
        status_code=status.HTTP_404_NOT_FOUND,
    )


def snapshot_file_response(
    service: ApprovalService, approval: Approval, *, inline: bool
) -> Response:
    """Serve an uploaded snapshot as safely as we know how."""
    if approval.snapshot_kind is not SnapshotKind.FILE or not approval.snapshot_stored_name:
        return Response(status_code=404)
    try:
        payload = service.storage.read(approval.snapshot_stored_name)
    except (OSError, ValueError):
        return Response(status_code=404)

    media_type = approval.snapshot_media_type or "application/octet-stream"
    # Inline rendering is allowed only for media types that cannot carry script.
    show_inline = inline and media_type in INLINE_MEDIA_TYPES
    disposition = "inline" if show_inline else "attachment"
    filename = approval.snapshot_filename or "snapshot"

    headers = dict(DOWNLOAD_HEADERS)
    headers["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return Response(
        content=payload,
        media_type=media_type if show_inline else "application/octet-stream",
        headers=headers,
    )


def _review_context(
    approval: Approval, token: str, *, error: str | None = None, form: dict | None = None
) -> dict:
    return {
        "approval": approval,
        "token": token,
        "status": approval.effective_status.value,
        "error": error,
        "form": form or {},
        "inline_viewable": (approval.snapshot_media_type or "") in INLINE_MEDIA_TYPES,
    }


@router.get("/{token}", response_class=HTMLResponse)
def review_page(request: Request, token: str, service: ServiceDep) -> Response:
    try:
        approval = service.get_by_token(token)
    except NotFoundError:
        return _not_found(request)
    return templates.TemplateResponse(
        request, "review.html", _review_context(approval, token)
    )


@router.get("/{token}/file")
def review_file(request: Request, token: str, service: ServiceDep) -> Response:
    try:
        approval = service.get_by_token(token)
    except NotFoundError:
        return _not_found(request)
    inline = request.query_params.get("inline") == "1"
    return snapshot_file_response(service, approval, inline=inline)


@router.post("/{token}/decision", response_class=HTMLResponse)
def submit_decision(
    request: Request,
    token: str,
    service: ServiceDep,
    decision: str = Form(...),
    comment: str = Form(""),
    reviewer_name: str = Form(""),
    reviewer_email: str = Form(""),
) -> Response:
    try:
        approval = service.get_by_token(token)
    except NotFoundError:
        return _not_found(request)

    form_values = {
        "comment": comment,
        "reviewer_name": reviewer_name,
        "reviewer_email": reviewer_email,
    }
    is_htmx = request.headers.get("hx-request") == "true"

    def render(error: str | None, code: int) -> Response:
        context = _review_context(approval, token, error=error, form=form_values)
        template = "_decision_form.html" if is_htmx else "review.html"
        return templates.TemplateResponse(
            request, template, context, status_code=code
        )

    try:
        decision_type = DecisionType(decision.strip().upper())
    except ValueError:
        return render("Unknown decision.", status.HTTP_400_BAD_REQUEST)

    try:
        service.record_decision(
            approval,
            decision=decision_type,
            comment=comment,
            reviewer_name=reviewer_name,
            reviewer_email=reviewer_email,
        )
    except ValidationError as exc:
        return render(str(exc), status.HTTP_400_BAD_REQUEST)
    except AlreadyDecidedError as exc:
        return render(str(exc), status.HTTP_409_CONFLICT)
    except ExpiredError as exc:
        return render(str(exc), status.HTTP_410_GONE)

    return render(None, status.HTTP_200_OK)
