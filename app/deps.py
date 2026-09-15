"""FastAPI dependencies shared by the routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.security import verify_session_value
from app.services import ApprovalService

OWNER_COOKIE = "approval_pack_owner"


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]
SessionDep = Annotated[Session, Depends(get_db)]


def service_dep(session: SessionDep, settings: SettingsDep) -> ApprovalService:
    return ApprovalService(session, settings)


ServiceDep = Annotated[ApprovalService, Depends(service_dep)]


class OwnerRedirect(Exception):
    """Raised when an unauthenticated owner request should go to /login."""

    def __init__(self, next_url: str) -> None:
        self.next_url = next_url


def is_owner(request: Request, settings: Settings) -> bool:
    if not settings.owner_area_protected:
        return True
    cookie = request.cookies.get(OWNER_COOKIE)
    if not cookie:
        return False
    return verify_session_value(settings.secret_key, cookie) == "owner"


def require_owner(request: Request, settings: SettingsDep) -> None:
    """Guard the owner area when APPROVAL_PACK_OWNER_PASSWORD is configured."""
    if is_owner(request, settings):
        return
    if request.headers.get("accept", "").startswith("application/json"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Owner login required."
        )
    raise OwnerRedirect(request.url.path)


OwnerDep = Annotated[None, Depends(require_owner)]


def owner_redirect_handler(_request: Request, exc: OwnerRedirect) -> RedirectResponse:
    return RedirectResponse(f"/login?next={exc.next_url}", status_code=303)
