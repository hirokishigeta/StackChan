"""OTA check / provisioning endpoint (Issue #23).

The firmware's ``Ota::CheckVersion`` (firmware/xiaozhi-esp32/main/ota.cc) POSTs
its system-info JSON to ``wifi.ota_url`` (pointed at this backend by #5 /
backend_config.cc). ``Application::InitializeProtocol`` selects WebsocketProtocol
only when the OTA response carries a ``websocket`` section
(``Ota::HasWebsocketConfig()`` sees ``cJSON_GetObjectItem(root, "websocket")``).

This route returns that minimal xiaozhi-compatible shape so the device connects
to the backend's audio WS, and deliberately omits the ``activation`` and
``mqtt`` sections so the cloud activation path is skipped and MQTT (which the
firmware prefers over WebSocket, ``application.cc:480``) is never selected.

Contract read from ota.cc (do not guess keys):

- Request: ``POST`` (body is ``Board::GetSystemInfoJson`` -> non-empty -> POST),
  headers ``Device-Id`` (MAC), ``Client-Id`` (UUID), ``User-Agent``,
  ``Content-Type: application/json``, ``Activation-Version``,
  ``Accept-Language``. Body JSON has ``version`` and ``application.version``.
- Response ``websocket`` keys consumed by ``WebsocketProtocol::OpenAudioChannel``
  (websocket_protocol.cc:84-87): ``url`` (string), ``token`` (string),
  ``version`` (number).
- Optional ``firmware`` section (ota.cc:214-241) is echoed with the device's
  current version and no ``url`` so ``has_new_version_`` stays false (we do not
  serve firmware images here).

This layer is presentation only: it delegates registration to the use case
resolved by the container (CLAUDE.md layer rules).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request

from app.application.use_cases.register_bot import RegisterBotUseCase
from app.config.settings import AppSettings, get_settings
from app.di_container.dependencies import get_register_bot_use_case

router = APIRouter(prefix="/api/ota", tags=["ota"])


def _build_ws_url(settings: AppSettings, device_id: str) -> str:
    """Build the device-facing audio WS URL (config-driven, no hard-coding)."""
    prefix = settings.ota_ws_path_prefix.rstrip("/")
    return (
        f"{settings.ota_ws_scheme}://{settings.ota_ws_host}:{settings.ota_ws_port}"
        f"{prefix}/{device_id}/audio"
    )


@router.post("/check")
async def ota_check(
    request: Request,
    use_case: Annotated[RegisterBotUseCase, Depends(get_register_bot_use_case)],
    settings: Annotated[AppSettings, Depends(get_settings)],
    device_id_header: Annotated[str | None, Header(alias="Device-Id")] = None,
) -> dict[str, Any]:
    """xiaozhi-compatible OTA check (firmware Ota::CheckVersion -> wifi.ota_url).

    Identifies the device by the ``Device-Id`` (MAC) header, registers it if
    unknown (the OTA check is the device's first contact), and returns the
    ``websocket`` section that makes the firmware select WebsocketProtocol.
    """
    body: dict[str, Any] = {}
    try:
        parsed = await request.json()
        if isinstance(parsed, dict):
            body = parsed
    except (ValueError, TypeError):
        # Firmware always sends JSON, but a malformed/empty body must not 500;
        # we still answer with the websocket section from the Device-Id header.
        body = {}

    # Device-Id header is authoritative (backend-protocol.md §5.1). Fall back to
    # the body's mac_address only if the header is absent.
    device_id = (device_id_header or str(body.get("mac_address", ""))).strip()
    if not device_id:
        device_id = "unknown-device"

    current_version = ""
    application = body.get("application")
    if isinstance(application, dict):
        current_version = str(application.get("version", ""))

    # Register (or re-register) the device so an unknown device that only ever
    # does an OTA check still gets a Bot + default settings (integrity with
    # /api/bot/register). Idempotent.
    use_case.execute(device_id=device_id, firmware_version=current_version)

    response: dict[str, Any] = {
        "websocket": {
            "url": _build_ws_url(settings, device_id),
            "token": settings.ota_ws_token,
            "version": settings.ota_ws_version,
        },
    }
    # Echo a firmware section so the device logs a clean "latest version" instead
    # of warning about a missing section. No `url` => Ota never flags an upgrade
    # (ota.cc requires both version and url to set has_new_version_).
    if current_version:
        response["firmware"] = {"version": current_version}
    return response
