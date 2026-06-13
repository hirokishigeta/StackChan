"""Dashboard routes (design-spec §10).

Serves a single, build-step-free settings page (static HTML + vanilla JS) that
reads/writes settings via the JSON APIs (``/api/settings/{device_id}`` and
``/api/server-settings``). Private-network use only (design-spec §10 / §13).

The known-device list and the default device id are injected into the page as
``window.__KNOWN_DEVICES__`` / ``window.__DEFAULT_DEVICE_ID__`` so the client can
prefill the device picker without hard-coding values (CLAUDE.md).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.application.use_cases.manage_settings import ManageSettingsUseCase
from app.config.settings import AppSettings, get_settings
from app.di_container.dependencies import get_settings_use_case

router = APIRouter(tags=["dashboard"])

_TEMPLATE_PATH = Path(__file__).parent / "static" / "dashboard.html"
# Placeholder replaced once per process with the injected bootstrap script.
_BOOTSTRAP_MARKER = "<script>\n      const DEFAULT_DEVICE_ID"


def _render(known_devices: list[str], default_device_id: str) -> str:
    """Inject the device list / default id into the static dashboard HTML."""
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    bootstrap = (
        "<script>\n"
        f"      window.__DEFAULT_DEVICE_ID__ = {json.dumps(default_device_id)};\n"
        f"      window.__KNOWN_DEVICES__ = {json.dumps(known_devices)};\n"
        "    </script>\n"
        "    <script>\n      const DEFAULT_DEVICE_ID"
    )
    return html.replace(_BOOTSTRAP_MARKER, bootstrap, 1)


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    use_case: Annotated[ManageSettingsUseCase, Depends(get_settings_use_case)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> HTMLResponse:
    """Render the settings dashboard page."""
    known_devices = [bot.device_id for bot in use_case.list_bots()]
    return HTMLResponse(content=_render(known_devices, settings.dashboard_default_device_id))
