"""OpenAI-compatible AgentGateway (design-spec §11.3 / §11.7).

Talks to any OpenAI-compatible Chat Completions endpoint (OpenAI, Ollama,
LM Studio, vLLM, ...). base_url / api_key / model come from settings (never
hard-coded; CLAUDE.md). The HTTP client is injected so tests mock it without
touching the network.

Response mapping (design-spec §11.3): the model is asked to reply with a JSON
object ``{"text", "emotion", "actions"}``. If it complies we map it directly;
otherwise we fall back to treating the whole message content as ``text`` and
synthesise a ``set_expression`` action from the emotion. On transport failure
(timeout / connection / non-2xx / malformed body) we raise
:class:`AgentError` so the conversation loop can degrade gracefully (§13).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from app.application.ports.agent_gateway import AgentError, AgentGateway, ProgressCallback
from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentAction, AgentReply, ProactiveEvent

# Instructs the model to emit a structured reply we can map to §11.3.
_RESPONSE_FORMAT_INSTRUCTION = (
    "Always reply with a single JSON object and nothing else, shaped as: "
    '{"text": string, "emotion": string, '
    '"actions": [{"type": string, "value": string|null}], '
    '"end_conversation": boolean}. '
    "emotion is one of: neutral, happy, sad, angry, curious, surprised, sleepy. "
    "Set end_conversation to true ONLY when the conversation has clearly and "
    "naturally finished — e.g. the user says goodbye/thanks-that's-all, or there "
    "is nothing left to do. Otherwise set it to false so we keep listening. "
    "When ending, give a brief, warm farewell and gently invite the user to call "
    "you again by name if they need anything (例:「何かあったら呼んでね」). "
    "IMPORTANT: the 'text' field is spoken aloud by a text-to-speech voice, so it "
    "must read naturally when heard. Do NOT put URLs, web links, markdown, code "
    "blocks, file paths, or raw tool output in 'text'. If a tool or source "
    "returned such things, summarize the result in plain spoken Japanese instead "
    "of reciting them. Keep 'text' to what a person would actually say out loud."
)

# Type of the injectable client factory: () -> AsyncClient.
ClientFactory = Callable[[], httpx.AsyncClient]


class OpenAICompatibleGateway(AgentGateway):
    """AgentGateway backed by an OpenAI-compatible Chat Completions API."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 30.0,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_s = timeout_s
        # Injectable for tests; defaults to a real httpx client.
        self._client_factory: ClientFactory = client_factory or self._default_client_factory

    def _default_client_factory(self) -> httpx.AsyncClient:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=self._timeout_s,
        )

    async def chat(
        self,
        *,
        message: str,
        profile: AgentProfile,
        context: dict[str, object] | None = None,
        progress_cb: ProgressCallback | None = None,
    ) -> AgentReply:
        # progress_cb is ignored: this gateway is non-streaming.
        user_content = _augment_with_context(message, context)
        messages = self._build_messages(profile, user_content)
        return await self._complete(messages, profile)

    async def chat_streaming(
        self,
        *,
        message: str,
        profile: AgentProfile,
        context: dict[str, object] | None,
        progress_cb: ProgressCallback,
    ) -> AgentReply:
        """Streaming variant: SSE-stream the completion, surfacing Hermes-style
        ``hermes.tool.progress`` events as short status labels via ``progress_cb``.

        Builds the same request as :meth:`chat` plus ``stream: true``. Normal
        content chunks are accumulated and mapped to an :class:`AgentReply` with
        the same parsing as the non-streaming path; tool-progress events are
        translated to a human-readable label by :func:`_tool_label` and pushed
        through ``progress_cb`` (de-duped so the same label is not spammed).
        """
        user_content = _augment_with_context(message, context)
        messages = self._build_messages(profile, user_content)
        model = profile.model_name or self._model
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": profile.temperature,
            "max_tokens": profile.max_tokens,
            "stream": True,
        }
        content_parts: list[str] = []
        pending_event: str | None = None
        last_label: str | None = None
        try:
            async with self._client_factory() as client:
                async with client.stream("POST", "/chat/completions", json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            pending_event = None
                            continue
                        if line.startswith("event:"):
                            pending_event = line[len("event:") :].strip()
                            continue
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if pending_event == "hermes.tool.progress":
                            label = _tool_label(obj if isinstance(obj, dict) else {})
                            if label != last_label:
                                last_label = label
                                await progress_cb(label)
                            pending_event = None
                            continue
                        try:
                            piece = obj["choices"][0]["delta"].get("content", "")
                        except (KeyError, IndexError, TypeError):
                            piece = ""
                        if piece:
                            content_parts.append(piece)
        except httpx.TimeoutException as exc:
            raise AgentError(f"agent request timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise AgentError(
                f"agent returned HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AgentError(f"agent request failed: {exc}") from exc

        return _content_to_reply("".join(content_parts))

    async def proactive(
        self,
        *,
        event: ProactiveEvent,
        profile: AgentProfile,
    ) -> AgentReply:
        prompt = (
            f"Event: {event.event_type}. Context: {json.dumps(event.context_dict())}. "
            "Start a short, natural proactive conversation with the user and include a "
            "proactive_speak action with reason set to the event type."
        )
        messages = self._build_messages(profile, prompt)
        reply = await self._complete(messages, profile)
        return _ensure_proactive_action(reply, event)

    # --- internals --------------------------------------------------------

    def _build_messages(self, profile: AgentProfile, user_content: str) -> list[dict[str, str]]:
        system_parts = [p for p in (profile.system_prompt, _RESPONSE_FORMAT_INSTRUCTION) if p]
        messages: list[dict[str, str]] = []
        if system_parts:
            messages.append({"role": "system", "content": "\n\n".join(system_parts)})
        messages.append({"role": "user", "content": user_content})
        return messages

    async def _complete(self, messages: list[dict[str, str]], profile: AgentProfile) -> AgentReply:
        model = profile.model_name or self._model
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": profile.temperature,
            "max_tokens": profile.max_tokens,
        }
        try:
            async with self._client_factory() as client:
                response = await client.post("/chat/completions", json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as exc:
            raise AgentError(f"agent request timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise AgentError(
                f"agent returned HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AgentError(f"agent request failed: {exc}") from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise AgentError(f"agent returned a non-JSON body: {exc}") from exc

        return _map_completion(body)


def _augment_with_context(message: str, context: dict[str, object] | None) -> str:
    """Append a compact context hint so the model can use device state."""
    if not context:
        return message
    return f"{message}\n\n[context] {json.dumps(context, ensure_ascii=False, sort_keys=True)}"


def _map_completion(body: dict[str, Any]) -> AgentReply:
    """Map an OpenAI-compatible completion body to an AgentReply (§11.3)."""
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AgentError(f"unexpected completion shape: {exc}") from exc

    if not isinstance(content, str):
        raise AgentError("completion message content was not a string")

    return _content_to_reply(content)


def _content_to_reply(content: str) -> AgentReply:
    """Map a completion's text content to an AgentReply (§11.3).

    Shared by the non-streaming (:func:`_map_completion`) and streaming
    (:meth:`OpenAICompatibleGateway.chat_streaming`) paths: structured JSON is
    parsed when present, otherwise the text is used verbatim with a synthesised
    expression.
    """
    structured = _try_parse_structured(content)
    if structured is not None:
        return structured

    # Plain-text fallback: use the text verbatim and synthesise an expression.
    text = content.strip()
    emotion = "neutral"
    return AgentReply(
        text=text,
        emotion=emotion,
        actions=(AgentAction(type="set_expression", value=emotion),),
    )


def _tool_label(obj: dict[str, Any]) -> str:
    """Map a ``hermes.tool.progress`` event to a short Japanese status label.

    ``tool_name`` varies across tools, so we match on substrings of its
    lowercased form. ``"_thinking"`` / empty names map to a generic thinking
    status; unknown tools fall back to naming the tool.
    """
    raw = obj.get("tool_name")
    name = str(raw) if raw is not None else ""
    lowered = name.lower()
    if not lowered or lowered == "_thinking":
        return "🤔 考えています…"
    if any(k in lowered for k in ("search", "web", "browse")):
        return "🔧 Web検索を実行中…"
    if any(k in lowered for k in ("read", "file", "cat", "open")):
        return "🔧 ファイルを読んでいます…"
    if any(k in lowered for k in ("write", "edit")):
        return "🔧 ファイルを編集中…"
    if any(k in lowered for k in ("shell", "bash", "exec", "command", "terminal")):
        return "🔧 コマンドを実行中…"
    if any(k in lowered for k in ("python", "code")):
        return "🔧 コードを実行中…"
    return f"🔧 {name} を実行中…"


def _try_parse_structured(content: str) -> AgentReply | None:
    """Parse the model's JSON reply if present; return None on any mismatch."""
    text = content.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "text" not in data:
        return None

    reply_text = str(data["text"])
    emotion = str(data.get("emotion", "neutral")) or "neutral"
    actions = _map_actions(data.get("actions"), emotion)
    end_conversation = bool(data.get("end_conversation", False))
    return AgentReply(
        text=reply_text, emotion=emotion, actions=actions, end_conversation=end_conversation
    )


def _map_actions(raw: Any, emotion: str) -> tuple[AgentAction, ...]:
    """Map the model's actions array to AgentAction; default to expression."""
    if not isinstance(raw, list):
        return (AgentAction(type="set_expression", value=emotion),)
    actions: list[AgentAction] = []
    for item in raw:
        if not isinstance(item, dict) or "type" not in item:
            continue
        value = item.get("value")
        actions.append(
            AgentAction(type=str(item["type"]), value=None if value is None else str(value))
        )
    if not actions:
        return (AgentAction(type="set_expression", value=emotion),)
    return tuple(actions)


def _ensure_proactive_action(reply: AgentReply, event: ProactiveEvent) -> AgentReply:
    """Guarantee a proactive_speak action on proactive replies (§11.7)."""
    if any(a.type == "proactive_speak" for a in reply.actions):
        return reply
    return AgentReply(
        text=reply.text,
        emotion=reply.emotion,
        actions=(*reply.actions, AgentAction(type="proactive_speak", value=event.event_type)),
    )
