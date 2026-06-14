"""HermesAgentGateway streaming tests (tool-progress surfacing).

When a ``progress_cb`` is supplied, HermesAgentGateway streams the
OpenAI-compatible SSE from hermes-agent and surfaces ``hermes.tool.progress``
events as short status labels while accumulating the normal content chunks into
an :class:`AgentReply`. Without ``progress_cb`` it keeps the non-streaming path.

The hermes-agent server is never hit: the inner client is driven through an
injected ``httpx.MockTransport`` (CLAUDE.md: mock external APIs in tests).
"""

from __future__ import annotations

import httpx
import pytest
from app.domain.agent.entities import AgentProfile
from app.infrastructure.agent.hermes_agent_gateway import HermesAgentGateway


def _chunk(content: str) -> str:
    return 'data: {"choices":[{"delta":{"content":' + _json_str(content) + "}}]}\n\n"


def _json_str(s: str) -> str:
    import json

    return json.dumps(s, ensure_ascii=False)


# SSE body interleaving a tool-progress event with normal content chunks that
# together spell the structured reply JSON, ended by [DONE].
_SSE_BODY = (
    "event: hermes.tool.progress\n"
    'data: {"tool_name":"web_search","status":"running"}\n'
    "\n"
    + _chunk('{"text":"はい",')
    + _chunk('"emotion":"happy",')
    + _chunk('"actions":[],"end_conversation":false}')
    + "data: [DONE]\n\n"
)


def _streaming_gateway() -> HermesAgentGateway:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, content=_SSE_BODY.encode("utf-8"))

    transport = httpx.MockTransport(handler)

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url="http://hermes/v1", transport=transport)

    return HermesAgentGateway(
        base_url="http://hermes/v1",
        api_key="hk",
        model="hermes-agent",
        client_factory=factory,
    )


@pytest.mark.anyio
async def test_streaming_surfaces_tool_progress_and_parses_reply() -> None:
    labels: list[str] = []

    async def cb(label: str) -> None:
        labels.append(label)

    gw = _streaming_gateway()
    reply = await gw.chat(message="hi", profile=AgentProfile(), progress_cb=cb)

    assert "🔧 Web検索を実行中…" in labels
    assert reply.text == "はい"
    assert reply.emotion == "happy"
    assert reply.end_conversation is False


@pytest.mark.anyio
async def test_no_progress_cb_uses_non_streaming_path() -> None:
    import json

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen["payload"] = payload
        # Non-streaming completion shape (no SSE, no "stream" flag expected).
        assert "stream" not in payload
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "text": "やあ",
                                    "emotion": "neutral",
                                    "actions": [],
                                    "end_conversation": False,
                                }
                            ),
                        }
                    }
                ]
            },
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
    reply = await gw.chat(message="hi", profile=AgentProfile())

    assert reply.text == "やあ"
    assert reply.emotion == "neutral"
