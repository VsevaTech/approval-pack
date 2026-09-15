"""Application factory, middleware and startup wiring."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import Settings, get_settings
from app.db import init_db
from app.deps import (
    OWNER_COOKIE,
    OwnerRedirect,
    owner_redirect_handler,
    settings_dep,
)
from app.immutability import install_guards
from app.routers import approvals as approvals_router
from app.routers import review as review_router
from app.security import sign_session_value, tokens_equal
from app.storage import SnapshotStorage
from app.templating import TEMPLATES_DIR, templates

STATIC_DIR = TEMPLATES_DIR.parent / "static"

#: Everything is served from our own origin — no CDN, no inline script.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    install_guards()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        init_db()
        SnapshotStorage(settings.storage_dir).ensure_ready()
        yield

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Know exactly what was approved — and which version. "
            "Not an electronic signature."
        ),
        lifespan=lifespan,
    )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        # Snapshot downloads set their own, stricter policy.
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        return response

    app.add_exception_handler(OwnerRedirect, owner_redirect_handler)  # type: ignore[arg-type]

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request) -> Response:
        current = settings_dep()
        if not current.owner_area_protected:
            return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": None, "next_url": request.query_params.get("next", "/")},
        )

    @app.post("/login")
    def login(
        request: Request, password: str = Form(""), next: str = Form("/")
    ) -> Response:
        current = settings_dep()
        if not current.owner_area_protected:
            return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        if not tokens_equal(password, current.owner_password):
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Wrong password.", "next_url": next},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        target = next if next.startswith("/") else "/"
        response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            OWNER_COOKIE,
            sign_session_value(current.secret_key, "owner"),
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            max_age=60 * 60 * 12,
        )
        return response

    @app.post("/logout")
    def logout() -> Response:
        response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        response.delete_cookie(OWNER_COOKIE)
        return response

    app.include_router(review_router.router)
    app.include_router(approvals_router.router)
    return app


app = create_app()
