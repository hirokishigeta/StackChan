"""AgentGateway tests: OpenAI-compatible mapping, errors, registry, routes.

External APIs are never hit: the OpenAI-compatible gateway is driven through an
injected ``httpx.MockTransport`` (CLAUDE.md: mock external APIs in tests).
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from app.application.ports.agent_gateway import AgentError
from app.config.settings import AppSettings
from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentType, ProactiveEvent
from app.infrastructure.agent.dummy_agent_gateway import DummyAgentGateway
from app.infrastructure.agent.hermes_agent_gateway import HermesAgentGateway
from app.infrastructure.agent.openai_compatible_gateway import OpenAICompatibleGateway
from app.infrastructure.agent.openclaw_gateway import OpenClawGateway
from app.infrastructure.agent.registry import build_agent_gateway
from fastapi.testclient import TestClient


def _completion_body(content: str) -> dict[str, object]:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _gateway_with_handler(
    handler: Callable[[httpx.Request], httpx.Response],
) -> OpenAICompatibleGateway:
    transport = httpx.MockTransport(handler)

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url="http://test/v1", transport=transport)

    return OpenAICompatibleGateway(
        base_url="http://test/v1",
        api_key="test-key",
        model="test-model",
        client_factory=factory,
    )


# --- OpenAI-compatible response mapping ----------------------------------


@pytest.mark.anyio
async def test_maps_structured_json_reply() -> None:
    structured = json.dumps(
        {
            "text": "やあ！",
            "emotion": "happy",
            "actions": [{"type": "set_expression", "value": "happy"}],
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        return httpx.Response(200, json=_completion_body(structured))

    gateway = _gateway_with_handler(handler)
    reply = await gateway.chat(message="hi", profile=AgentProfile(model_name="test-model"))

    assert reply.text == "やあ！"
    assert reply.emotion == "happy"
    assert reply.actions[0].type == "set_expression"
    assert reply.actions[0].value == "happy"
    assert reply.end_conversation is False  # absent -> default False


@pytest.mark.anyio
async def test_maps_end_conversation_flag() -> None:
    structured = json.dumps(
        {"text": "またね！", "emotion": "happy", "actions": [], "end_conversation": True}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion_body(structured))

    gateway = _gateway_with_handler(handler)
    reply = await gateway.chat(message="bye", profile=AgentProfile())

    assert reply.end_conversation is True


@pytest.mark.anyio
async def test_plain_text_reply_falls_back_to_text_and_expression() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion_body("ただのテキスト"))

    gateway = _gateway_with_handler(handler)
    reply = await gateway.chat(message="hi", profile=AgentProfile())

    assert reply.text == "ただのテキスト"
    assert reply.emotion == "neutral"
    assert reply.actions[0].type == "set_expression"
    assert reply.actions[0].value == "neutral"


@pytest.mark.anyio
async def test_profile_model_overrides_default() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_completion_body("ok"))

    gateway = _gateway_with_handler(handler)
    await gateway.chat(message="hi", profile=AgentProfile(model_name="custom-model"))

    assert seen["model"] == "custom-model"


@pytest.mark.anyio
async def test_proactive_guarantees_proactive_speak_action() -> None:
    # Model replies without a proactive_speak action; gateway must add one.
    structured = json.dumps({"text": "なにか手伝おうか？", "emotion": "curious", "actions": []})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion_body(structured))

    gateway = _gateway_with_handler(handler)
    event = ProactiveEvent.from_context(
        event_type="attention_detected", context={"face_detected": True}
    )
    reply = await gateway.proactive(event=event, profile=AgentProfile())

    types = [a.type for a in reply.actions]
    assert "proactive_speak" in types
    proactive = next(a for a in reply.actions if a.type == "proactive_speak")
    assert proactive.value == "attention_detected"


# --- Error / timeout handling --------------------------------------------


@pytest.mark.anyio
async def test_timeout_raises_agent_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    gateway = _gateway_with_handler(handler)
    with pytest.raises(AgentError):
        await gateway.chat(message="hi", profile=AgentProfile())


@pytest.mark.anyio
async def test_http_500_raises_agent_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    gateway = _gateway_with_handler(handler)
    with pytest.raises(AgentError):
        await gateway.chat(message="hi", profile=AgentProfile())


@pytest.mark.anyio
async def test_connect_error_raises_agent_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    gateway = _gateway_with_handler(handler)
    with pytest.raises(AgentError):
        await gateway.chat(message="hi", profile=AgentProfile())


@pytest.mark.anyio
async def test_unexpected_body_raises_agent_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    gateway = _gateway_with_handler(handler)
    with pytest.raises(AgentError):
        await gateway.chat(message="hi", profile=AgentProfile())


# --- Registry / provider resolution --------------------------------------


def _settings(agent_type: str) -> AppSettings:
    return AppSettings(default_agent_type=agent_type)


def test_registry_resolves_openai_compatible() -> None:
    gateway = build_agent_gateway(_settings(AgentType.OPENAI_COMPATIBLE.value))
    assert isinstance(gateway, OpenAICompatibleGateway)


def test_registry_resolves_hermes() -> None:
    gateway = build_agent_gateway(_settings(AgentType.HERMES_AGENT.value))
    assert isinstance(gateway, HermesAgentGateway)


def test_registry_resolves_openclaw() -> None:
    gateway = build_agent_gateway(_settings(AgentType.OPEN_CLAW.value))
    assert isinstance(gateway, OpenClawGateway)


def test_registry_unknown_provider_falls_back_to_default() -> None:
    gateway = build_agent_gateway(_settings("NoSuchProvider"))
    assert isinstance(gateway, OpenAICompatibleGateway)


# --- Routes via the use case (dummy + fallback) --------------------------


def test_proactive_route_returns_actions(dummy_agent_client: TestClient) -> None:
    dummy_agent_client.post(
        "/api/bot/register",
        json={"device_id": "cores3-001", "firmware_version": "0.1.0"},
    )
    resp = dummy_agent_client.post(
        "/api/agent/proactive",
        json={
            "device_id": "cores3-001",
            "event_type": "attention_detected",
            "context": {"face_detected": True, "attention_duration_ms": 1800},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["emotion"] == "curious"
    assert any(a["type"] == "proactive_speak" for a in body["actions"])


class _FailingGateway(DummyAgentGateway):
    """Gateway that always raises AgentError (simulates backend outage)."""

    async def chat(self, *, message, profile, context=None):  # type: ignore[no-untyped-def]
        raise AgentError("backend down")

    async def proactive(self, *, event, profile):  # type: ignore[no-untyped-def]
        raise AgentError("backend down")


def test_chat_route_falls_back_on_agent_error(
    agent_client_factory: Callable[[object], TestClient],
) -> None:
    client = agent_client_factory(_FailingGateway())
    client.post(
        "/api/bot/register",
        json={"device_id": "cores3-001", "firmware_version": "0.1.0"},
    )
    resp = client.post(
        "/api/agent/chat",
        json={"device_id": "cores3-001", "message": "hi", "context": {}},
    )
    # Must not 5xx: firmware conversation loop has to survive (§13).
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"]
    assert body["actions"][0]["type"] == "set_expression"


@pytest.mark.anyio
async def test_hermes_delegates_persona_and_model_to_hermes() -> None:
    """HermesAgent owns persona/model: our per-device system_prompt and
    model_name must NOT be sent; the configured Hermes model is used."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(
            200,
            json=_completion_body(
                json.dumps(
                    {
                        "text": "ふむ",
                        "emotion": "neutral",
                        "actions": [],
                        "end_conversation": False,
                    }
                )
            ),
        )

    transport = httpx.MockTransport(handler)

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url="http://hermes/v1", transport=transport)

    gw = HermesAgentGateway(
        base_url="http://hermes/v1",
        api_key="hk",
        model="hermes-agent",
        client_factory=factory,
    )
    profile = AgentProfile(model_name="gpt-5-chat-latest", system_prompt="SECRET PERSONA")
    reply = await gw.chat(message="hi", profile=profile)

    assert reply.text == "ふむ"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "hermes-agent"  # Hermes model, not the profile's
    system_contents = [m["content"] for m in payload["messages"] if m["role"] == "system"]
    assert all("SECRET PERSONA" not in c for c in system_contents)  # persona delegated
