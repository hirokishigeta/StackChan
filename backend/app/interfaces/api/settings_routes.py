"""Settings API (design-spec §10). GET / PUT the per-device settings aggregate.

The aggregate is exchanged as the JSON form produced by
``settings_to_dict`` / consumed by ``settings_from_dict``. Unknown or
omitted keys fall back to defaults, so the dashboard can send partial
updates layered onto current values.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app.application.use_cases.manage_settings import ManageSettingsUseCase
from app.di_container.dependencies import get_settings_use_case
from app.domain.settings.entities import BotSettings
from app.infrastructure.persistence.serialization import (
    settings_from_dict,
    settings_to_dict,
    validate_enum_inputs,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Module-level singleton to avoid a function call in argument defaults (ruff B008).
_SETTINGS_BODY = Body(default_factory=dict)


@router.get("/{device_id}")
def get_settings(
    device_id: str,
    use_case: Annotated[ManageSettingsUseCase, Depends(get_settings_use_case)],
) -> dict[str, Any]:
    """Return the settings aggregate for a device."""
    settings = use_case.get_settings(device_id)
    if settings is None:
        raise HTTPException(status_code=404, detail="device not found")
    return settings_to_dict(settings)


@router.put("/{device_id}")
def update_settings(
    device_id: str,
    use_case: Annotated[ManageSettingsUseCase, Depends(get_settings_use_case)],
    body: dict[str, Any] = _SETTINGS_BODY,
) -> dict[str, Any]:
    """Update (merge over current/defaults) and return the settings aggregate.

    User input is validated strictly: an unknown enum value is rejected with
    HTTP 422 rather than silently coerced to a default (the lenient fallback in
    ``settings_from_dict`` is reserved for the load path, design-spec §13).
    """
    current = use_case.get_settings(device_id) or BotSettings.default(device_id)
    merged = {**settings_to_dict(current), **body}
    try:
        validate_enum_inputs(body)
        # ``settings_from_dict`` rebuilds the frozen domain aggregate, whose value
        # objects validate themselves (e.g. empty wake-word phrase / threshold out
        # of [0, 1]); surface those as 422 rather than a 500.
        rebuilt = settings_from_dict(device_id, merged)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    updated = use_case.update_settings(rebuilt)
    return settings_to_dict(updated)
