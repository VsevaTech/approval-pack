"""Owner-facing routes: create, list, inspect, download evidence."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, File, Form, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import OwnerDep, ServiceDep, SettingsDep
from app.evidence import evidence_html, evidence_json
from app.security import ALLOWED_EXTENSIONS
from app.services import (
    ApprovalDraft,
    ApprovalError,
    NotFoundError,
    UploadedFile,
    ValidationError,
)
from app.templating import templates

router = APIRouter()


def _render_error(
    request: Request, heading: str, message: str, code: int
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "error.html",
        {"heading": heading, "message": message},
        status_code=code,
    )


def _parse_expires(raw: str | None) -> datetime | None:
    if not raw or not raw.strip():
        return None
    value = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("Expiration date is not a valid date/time.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


@router.get("/", response_class=HTMLResponse)
def index(request: Request, service: ServiceDep, _owner: OwnerDep) -> Response:
    return templates.TemplateResponse(
        request, "index.html", {"approvals": service.list_approvals()}
    )


@router.get("/approvals/new", response_class=HTMLResponse)
def new_approval_form(
    request: Request, settings: SettingsDep, _owner: OwnerDep
) -> Response:
    return templates.TemplateResponse(
        request,
        "new.html",
        {
            "form": {},
            "error": None,
            "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
            "max_upload_kib": settings.max_upload_bytes // 1024,
        },
    )


@router.post("/approvals")
async def create_approval(
    request: Request,
    service: ServiceDep,
    settings: SettingsDep,
    _owner: OwnerDep,
    title: str = Form(""),
    description: str = Form(""),
    text: str = Form(""),
    reviewer_name: str = Form(""),
    reviewer_email: str = Form(""),
    expires_at: str = Form(""),
    file: UploadFile | None = File(None),
) -> Response:
    form_values = {
        "title": title,
        "description": description,
        "text": text,
        "reviewer_name": reviewer_name,
        "reviewer_email": reviewer_email,
        "expires_at": expires_at,
    }

    upload: UploadedFile | None = None
    if file is not None and file.filename:
        # Read with a hard ceiling so an oversized body never lands on disk.
        payload = await file.read(settings.max_upload_bytes + 1)
        upload = UploadedFile(filename=file.filename, content=payload)

    try:
        draft = ApprovalDraft(
            title=title,
            description=description,
            text=text or None,
            upload=upload,
            reviewer_name=reviewer_name,
            reviewer_email=reviewer_email,
            expires_at=_parse_expires(expires_at),
        )
        approval = service.create(draft)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "new.html",
            {
                "form": form_values,
                "error": str(exc),
                "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
                "max_upload_kib": settings.max_upload_bytes // 1024,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(
        f"/approvals/{approval.id}?created=1", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/approvals/{approval_id}", response_class=HTMLResponse)
def approval_detail(
    request: Request, approval_id: str, service: ServiceDep, _owner: OwnerDep
) -> Response:
    try:
        approval = service.get(approval_id)
    except NotFoundError as exc:
        return _render_error(request, "Not found", str(exc), 404)

    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "approval": approval,
            "review_url": service.review_url(approval),
            "integrity_ok": service.verify_integrity(approval),
            "just_created": request.query_params.get("created") == "1",
        },
    )


@router.get("/approvals/{approval_id}/file")
def download_snapshot_file(
    approval_id: str, service: ServiceDep, _owner: OwnerDep
) -> Response:
    from app.routers.review import snapshot_file_response

    try:
        approval = service.get(approval_id)
    except NotFoundError:
        return Response(status_code=404)
    return snapshot_file_response(service, approval, inline=False)


@router.get("/approvals/{approval_id}/evidence.json")
def evidence_json_route(
    approval_id: str, service: ServiceDep, _owner: OwnerDep
) -> Response:
    try:
        approval = service.get(approval_id)
    except NotFoundError as exc:
        return Response(content=str(exc), status_code=404, media_type="text/plain")
    body = evidence_json(approval, review_url=service.review_url(approval))
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="approval-{approval.id}-evidence.json"'
            )
        },
    )


@router.get("/approvals/{approval_id}/evidence.html")
def evidence_html_route(
    approval_id: str, service: ServiceDep, _owner: OwnerDep
) -> Response:
    try:
        approval = service.get(approval_id)
    except NotFoundError as exc:
        return Response(content=str(exc), status_code=404, media_type="text/plain")
    body = evidence_html(approval, review_url=service.review_url(approval))
    return Response(
        content=body,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="approval-{approval.id}-evidence.html"'
            )
        },
    )


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


__all__ = ["ApprovalError", "router"]
