"""OTA check / provisioning endpoint tests (Issue #23).

Verify the route returns a xiaozhi-compatible ``websocket`` section, omits
``activation``/``mqtt`` (so the device skips cloud activation and never prefers
MQTT), builds the WS URL from the Device-Id header, and registers unknown
devices. Contract-driven, no native deps (CLAUDE.md).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

# Minimal slice of Board::GetSystemInfoJson (firmware/.../boards/common/board.cc).
_SYSTEM_INFO = {
    "version": 2,
    "flash_size": 4194304,
    "application": {"name": "stackchan", "version": "1.4.2"},
}


def test_ota_check_returns_websocket_section(client: TestClient) -> None:
    resp = client.post(
        "/api/ota/check",
        json=_SYSTEM_INFO,
        headers={"Device-Id": "aa:bb:cc:dd:ee:ff"},
    )
    assert resp.status_code == 200
    body = resp.json()
    ws = body["websocket"]
    assert ws["url"].endswith("/api/bot/aa:bb:cc:dd:ee:ff/audio")
    assert ws["url"].startswith("ws://")
    assert ws["version"] == 2
    assert "token" in ws


def test_ota_check_omits_activation_and_mqtt(client: TestClient) -> None:
    # No `activation` => firmware skips cloud activation. No `mqtt` => firmware
    # does not prefer MQTT over WebSocket (application.cc:480).
    resp = client.post(
        "/api/ota/check",
        json=_SYSTEM_INFO,
        headers={"Device-Id": "aa:bb:cc:dd:ee:ff"},
    )
    body = resp.json()
    assert "activation" not in body
    assert "mqtt" not in body


def test_ota_check_ws_url_from_device_id_header(client: TestClient) -> None:
    resp = client.post(
        "/api/ota/check",
        json=_SYSTEM_INFO,
        headers={"Device-Id": "11:22:33:44:55:66"},
    )
    ws = resp.json()["websocket"]
    assert ws["url"].endswith("/api/bot/11:22:33:44:55:66/audio")


def test_ota_check_registers_unknown_device(client: TestClient) -> None:
    # An unknown device's OTA check is its first contact; it should be created
    # so its settings are immediately retrievable (integrity with /register).
    device_id = "de:ad:be:ef:00:01"
    pre = client.get(f"/api/settings/{device_id}")
    assert pre.status_code == 404

    resp = client.post("/api/ota/check", json=_SYSTEM_INFO, headers={"Device-Id": device_id})
    assert resp.status_code == 200

    post = client.get(f"/api/settings/{device_id}")
    assert post.status_code == 200


def test_ota_check_echoes_firmware_version_without_url(client: TestClient) -> None:
    # firmware section carries the device's current version and no `url`, so the
    # firmware never flags an upgrade (ota.cc needs both version and url).
    resp = client.post(
        "/api/ota/check",
        json=_SYSTEM_INFO,
        headers={"Device-Id": "aa:bb:cc:dd:ee:ff"},
    )
    firmware = resp.json()["firmware"]
    assert firmware["version"] == "1.4.2"
    assert "url" not in firmware


def test_ota_check_without_device_id_still_provisions(client: TestClient) -> None:
    # Missing Device-Id header must not 500; fall back without crashing.
    resp = client.post("/api/ota/check", json=_SYSTEM_INFO)
    assert resp.status_code == 200
    assert "websocket" in resp.json()
