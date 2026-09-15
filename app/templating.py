"""Jinja2 environment shared by the routers."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.config import get_settings

TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
# Jinja2Templates autoescapes .html by default; be explicit about it anyway.
templates.env.autoescape = True
templates.env.globals["app_name"] = get_settings().app_name
