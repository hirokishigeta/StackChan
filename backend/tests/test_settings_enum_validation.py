"""Regression tests for Issue #28: invalid enum handling in settings.

Two paths are deliberately asymmetric (design-spec §13):
- load / deserialize: unknown enum values fall back to defaults (robust reads,
  never 500), so a stale/corrupt persisted value cannot break startup or GET.
- PUT (user input): unknown enum values are rejected with HTTP 422, so a
  configuration mistake is surfaced rather than silently swallowed.
"""

from __future__ import annotations

import json

import pytest
from app.domain.agent.value_objects import AgentType, ResponseMode
from app.domain.settings.entities import BotSettings
from app.domain.vision.value_objects import ProcessingLocation
from app.infrastructure.persistence.serialization import (
    settings_from_dict,
    settings_to_dict,
    validate_enum_inputs,
)
from fastapi.testclient import TestClient


def _register(client: TestClient, device_id: str = "cores3-001") -> None:
    resp = client.post(
        "/api/bot/register",
        json={"device_id": device_id, "firmware_version": "0.1.0"},
    )
    assert resp.status_code == 200


# -- load / deserialize path: unknown enum -> default (no exception) ---------


def test_settings_from_dict_unknown_enum_falls_back_to_default() -> None:
    defaults = BotSettings.default("dev-1")
    data = settings_to_dict(defaults)
    data["agent"]["agent_type"] = "BogusAgent"
    data["agent"]["response_mode"] = "telepathy"
    data["vision"]["processing_location"] = "moon"
    data["vision_stream"]["processing_location"] = "moon"
    # Legacy wake-word fields (removed in ADR-0017) are ignored on load, not
    # errored, for back-compat with older persisted rows.
    data["wake_word"]["detection_method"] = "psychic"
    data["wake_word"]["max_local_active"] = 99

    rebuilt = settings_from_dict("dev-1", data)

    assert rebuilt.agent.agent_type == defaults.agent.agent_type
    assert rebuilt.agent.response_mode == defaults.agent.response_mode
    assert rebuilt.vision.processing_location == defaults.vision.processing_location
    assert rebuilt.vision_stream.processing_location == defaults.vision_stream.processing_location
    assert not hasattr(rebuilt.wake_word, "detection_method")


def test_get_settings_with_corrupt_db_enum_returns_defaults_not_500(
    client: TestClient,
) -> None:
    """(a) A persisted row with a bad enum must not 500 the GET endpoint."""
    _register(client)
    from app.di_container import container as container_module

    repo = container_module.get_container().repository
    # Corrupt the stored payload directly so the load path sees a bad enum.
    current = repo.get_settings("cores3-001")
    assert current is not None
    payload = settings_to_dict(current)
    payload["agent"]["agent_type"] = "NoSuchAgent"
    _write_raw_payload(repo, "cores3-001", payload)

    resp = client.get("/api/settings/cores3-001")
    assert resp.status_code == 200
    assert resp.json()["agent"]["agent_type"] == BotSettings.default("x").agent.agent_type.value


def _write_raw_payload(repo: object, device_id: str, payload: dict[str, object]) -> None:
    from app.infrastructure.persistence.sqlite_settings_repository import SettingsRow
    from sqlmodel import Session

    engine = repo._engine  # type: ignore[attr-defined]  # noqa: SLF001  (test-only)
    with Session(engine) as session:
        row = session.get(SettingsRow, device_id)
        assert row is not None
        row.payload = json.dumps(payload, ensure_ascii=False)
        session.add(row)
        session.commit()


# -- PUT path: unknown enum -> 422 ------------------------------------------


def test_put_invalid_enum_returns_422(client: TestClient) -> None:
    """(b) An unknown enum in user input must be rejected with 422."""
    _register(client)
    resp = client.put(
        "/api/settings/cores3-001",
        json={"agent": {"agent_type": "NotARealAgent"}},
    )
    assert resp.status_code == 422
    assert "agent.agent_type" in resp.json()["detail"]


def test_put_legacy_detection_method_is_ignored_not_422(client: TestClient) -> None:
    """``detection_method`` was removed (ADR-0017); it is no longer a validated
    enum, so a PUT carrying it (e.g. from an old client) is accepted and the
    field is simply dropped rather than rejected with 422."""
    _register(client)
    resp = client.put(
        "/api/settings/cores3-001",
        json={"wake_word": {"detection_method": "telepathic"}},
    )
    assert resp.status_code == 200
    assert "detection_method" not in resp.json()["wake_word"]


def test_put_valid_enum_returns_200_and_applies(client: TestClient) -> None:
    """(c) A valid enum value is accepted and reflected back."""
    _register(client)
    resp = client.put(
        "/api/settings/cores3-001",
        json={"agent": {"agent_type": AgentType.OPENAI_COMPATIBLE.value}},
    )
    assert resp.status_code == 200
    assert resp.json()["agent"]["agent_type"] == AgentType.OPENAI_COMPATIBLE.value

    get = client.get("/api/settings/cores3-001")
    assert get.json()["agent"]["agent_type"] == AgentType.OPENAI_COMPATIBLE.value


# -- validate_enum_inputs unit coverage -------------------------------------


def test_validate_enum_inputs_accepts_valid_and_omitted() -> None:
    validate_enum_inputs({})  # no enum fields present -> ok
    validate_enum_inputs(
        {
            "agent": {"response_mode": ResponseMode.STREAM.value},
            "vision": {"processing_location": ProcessingLocation.BACKEND.value},
        }
    )


def test_validate_enum_inputs_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="vision.processing_location"):
        validate_enum_inputs({"vision": {"processing_location": "nowhere"}})
