"""Happy-path API tests against the dummy infrastructure."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _register(client: TestClient, device_id: str = "cores3-001") -> None:
    resp = client.post(
        "/api/bot/register",
        json={"device_id": device_id, "firmware_version": "0.1.0"},
    )
    assert resp.status_code == 200


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_register_bot_returns_settings(client: TestClient) -> None:
    resp = client.post(
        "/api/bot/register",
        json={"device_id": "cores3-001", "firmware_version": "0.1.0"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["bot_id"] == "cores3-001"
    assert "agent" in body["settings"]
    assert "wake_word" in body["settings"]


def test_agent_chat_dummy(dummy_agent_client: TestClient) -> None:
    _register(dummy_agent_client)
    resp = dummy_agent_client.post(
        "/api/agent/chat",
        json={"device_id": "cores3-001", "message": "こんにちは", "context": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"]
    assert body["emotion"] == "happy"
    assert body["actions"][0]["type"] == "set_expression"


def test_speech_recognize_dummy(client: TestClient) -> None:
    resp = client.post("/api/speech/recognize", content=b"\x00\x01\x02")
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "こんにちは"
    assert body["language"] == "ja"
    assert 0.0 <= body["confidence"] <= 1.0


def test_vision_detect_dummy(client: TestClient) -> None:
    resp = client.post("/api/vision/detect", content=b"\xff\xd8\xff")
    assert resp.status_code == 200
    body = resp.json()
    assert body["detections"][0]["type"] == "face"
    assert body["tracking_target"] is not None


def test_vision_attention_route(dummy_agent_client: TestClient) -> None:
    # Attention is disabled by default, so the route stays a safe no-op but must
    # respond 200 with the evaluation envelope (design-spec §6).
    _register(dummy_agent_client)
    resp = dummy_agent_client.post(
        "/api/vision/attention?device_id=cores3-001", content=b"\xff\xd8\xff"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] in {"Idle", "FaceDetected", "AttentionDetected"}
    assert body["attention_detected"] is False
    assert "detections" in body


def test_commands_polling_drains_empty(client: TestClient) -> None:
    _register(client)
    resp = client.get("/api/bot/cores3-001/commands")
    assert resp.status_code == 200
    assert resp.json() == {"commands": []}


def test_wakeword_endpoint(client: TestClient) -> None:
    _register(client)
    # Add two wake words via the settings API.
    put = client.put(
        "/api/settings/cores3-001",
        json={
            "wake_word": {
                "enabled": True,
                "detection_method": "local",
                "max_local_active": 3,
                "wake_words": [
                    {"id": "ww-1", "phrase": "hello bot", "threshold": 0.7, "enabled": True},
                    {
                        "id": "ww-2",
                        "phrase": "ねえスタックチャン",
                        "threshold": 0.65,
                        "enabled": True,
                    },
                ],
            }
        },
    )
    assert put.status_code == 200

    resp = client.get("/api/bot/cores3-001/wakeword")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["detection_method"] == "local"
    assert len(body["wake_words"]) == 2
    assert body["wake_words"][0]["id"] == "ww-1"


def test_settings_default_wake_words_served(client: TestClient) -> None:
    _register(client)
    # A freshly registered device exposes the default wake-word list.
    resp = client.get("/api/bot/cores3-001/wakeword")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["wake_words"]) >= 1
    assert all(w["phrase"].strip() for w in body["wake_words"])


def test_settings_put_rejects_empty_wake_word_phrase(client: TestClient) -> None:
    _register(client)
    resp = client.put(
        "/api/settings/cores3-001",
        json={"wake_word": {"wake_words": [{"id": "ww-1", "phrase": "  "}]}},
    )
    assert resp.status_code == 422


def test_settings_put_rejects_bad_wake_word_threshold(client: TestClient) -> None:
    _register(client)
    resp = client.put(
        "/api/settings/cores3-001",
        json={"wake_word": {"wake_words": [{"id": "ww-1", "phrase": "hello", "threshold": 1.5}]}},
    )
    assert resp.status_code == 422


def test_settings_wake_words_roundtrip(client: TestClient) -> None:
    _register(client)
    payload = {
        "wake_word": {
            "enabled": True,
            "detection_method": "local",
            "wake_words": [
                {"id": "ww-a", "phrase": "おはよう", "threshold": 0.6, "enabled": True},
                {"id": "ww-b", "phrase": "bye bot", "threshold": 0.8, "enabled": False},
            ],
        }
    }
    put = client.put("/api/settings/cores3-001", json=payload)
    assert put.status_code == 200
    got = client.get("/api/settings/cores3-001").json()["wake_word"]["wake_words"]
    assert [w["phrase"] for w in got] == ["おはよう", "bye bot"]
    assert got[1]["enabled"] is False


def test_settings_default_end_words_served(client: TestClient) -> None:
    _register(client)
    # A freshly registered device exposes the default per-device end-word list.
    body = client.get("/api/settings/cores3-001").json()
    end_words = body["end_word"]["end_words"]
    assert len(end_words) >= 1
    assert all(w["phrase"].strip() for w in end_words)


def test_settings_put_rejects_empty_end_word_phrase(client: TestClient) -> None:
    _register(client)
    resp = client.put(
        "/api/settings/cores3-001",
        json={"end_word": {"end_words": [{"id": "ew-1", "phrase": "  "}]}},
    )
    assert resp.status_code == 422


def test_settings_end_words_roundtrip(client: TestClient) -> None:
    _register(client)
    payload = {
        "end_word": {
            "end_words": [
                {"id": "ew-a", "phrase": "もうおしまい", "enabled": True},
                {"id": "ew-b", "phrase": "また今度", "enabled": False},
            ]
        }
    }
    put = client.put("/api/settings/cores3-001", json=payload)
    assert put.status_code == 200
    got = client.get("/api/settings/cores3-001").json()["end_word"]["end_words"]
    assert [w["phrase"] for w in got] == ["もうおしまい", "また今度"]
    assert got[1]["enabled"] is False


def test_settings_get_put_roundtrip(client: TestClient) -> None:
    _register(client)
    put = client.put(
        "/api/settings/cores3-001",
        json={"agent": {"model_name": "my-model", "temperature": 0.3}},
    )
    assert put.status_code == 200
    assert put.json()["agent"]["model_name"] == "my-model"

    get = client.get("/api/settings/cores3-001")
    assert get.status_code == 200
    assert get.json()["agent"]["model_name"] == "my-model"
    assert get.json()["agent"]["temperature"] == 0.3


def test_settings_unknown_device_404(client: TestClient) -> None:
    resp = client.get("/api/settings/unknown")
    assert resp.status_code == 404


def test_dashboard_renders(client: TestClient) -> None:
    _register(client)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "StackChan" in resp.text
    # The registered device id is injected into the known-device list.
    assert "cores3-001" in resp.text
