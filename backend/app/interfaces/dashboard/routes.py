"""Dashboard routes (design-spec §10). Minimal Bot list / status shell.

Private-network use only (design-spec §10 / §13). This phase renders just
the Bot list + connection status frame; settings panels come in later phases.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.application.use_cases.manage_settings import ManageSettingsUseCase
from app.di_container.dependencies import get_settings_use_case

from .schemas import BotSummary

router = APIRouter(tags=["dashboard"])


def _render(bots: list[BotSummary]) -> str:
    if bots:
        rows = "".join(
            f"<tr><td>{b.device_id}</td><td>{b.name}</td>"
            f"<td>{b.firmware_version}</td><td>{b.connection_status}</td></tr>"
            for b in bots
        )
    else:
        rows = '<tr><td colspan="4">No bots registered yet.</td></tr>'
    return (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
        "<title>StackChan Dashboard</title></head><body>"
        "<h1>StackChan Dashboard</h1>"
        "<p>Private network only.</p>"
        "<h2>Bots</h2>"
        "<table border='1' cellpadding='4'>"
        "<thead><tr><th>device_id</th><th>name</th>"
        "<th>firmware</th><th>status</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        "</body></html>"
    )


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    use_case: Annotated[ManageSettingsUseCase, Depends(get_settings_use_case)],
) -> HTMLResponse:
    """Render the minimal Bot-list dashboard."""
    bots = [
        BotSummary(
            device_id=b.device_id,
            name=b.name,
            firmware_version=b.firmware_version,
            connection_status=b.connection_status.value,
        )
        for b in use_case.list_bots()
    ]
    return HTMLResponse(content=_render(bots))
