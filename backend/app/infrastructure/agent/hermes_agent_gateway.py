"""HermesAgent AgentGateway adapter (NousResearch hermes-agent).

hermes-agent exposes an **OpenAI-compatible** API server (default
``http://127.0.0.1:8642/v1``, bearer ``API_SERVER_KEY``) with
``POST /v1/chat/completions``. We therefore drive it through the same
OpenAI-compatible transport as :class:`OpenAICompatibleGateway`, pointed at the
Hermes connection params from settings.

Delegation (per product decision): when HermesAgent is selected, the agent
*settings* are owned by Hermes — its own persona/system prompt, model, memory
(FTS5 recall) and skills. So we strip our per-device ``system_prompt`` and
``model_name`` from the profile before the call; Hermes uses its configured
model and persona. Connection params (base_url / api_key / model) come from
:class:`AppSettings` (never hard-coded; CLAUDE.md).

TODO(issue#6): leverage Hermes-specific endpoints beyond chat — ``/v1/responses``
with ``store``/``previous_response_id`` for Hermes-managed conversation memory,
``/api/sessions`` for continuity, and ``/api/jobs`` for scheduling — once
per-conversation state threading is wired through the WS session layer.
"""

from __future__ import annotations

import dataclasses

from app.application.ports.agent_gateway import AgentGateway, ProgressCallback
from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentReply, ProactiveEvent

from .openai_compatible_gateway import ClientFactory, OpenAICompatibleGateway


class HermesAgentGateway(AgentGateway):
    """AgentGateway backed by the OpenAI-compatible hermes-agent API server."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 30.0,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._inner = OpenAICompatibleGateway(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_s=timeout_s,
            client_factory=client_factory,
        )

    @staticmethod
    def _delegated(profile: AgentProfile) -> AgentProfile:
        """Hand persona/model to Hermes: drop our system_prompt and model_name so
        Hermes uses its own (empty model_name falls back to the configured
        ``hermes_model`` in the inner gateway)."""
        return dataclasses.replace(profile, system_prompt="", model_name="")

    async def chat(
        self,
        *,
        message: str,
        profile: AgentProfile,
        context: dict[str, object] | None = None,
        progress_cb: ProgressCallback | None = None,
    ) -> AgentReply:
        delegated = self._delegated(profile)
        if progress_cb is None:
            # No progress sink: keep the simpler non-streaming path.
            return await self._inner.chat(message=message, profile=delegated, context=context)
        # Stream so Hermes tool/thinking steps reach the device mid-turn.
        return await self._inner.chat_streaming(
            message=message, profile=delegated, context=context, progress_cb=progress_cb
        )

    async def proactive(
        self,
        *,
        event: ProactiveEvent,
        profile: AgentProfile,
    ) -> AgentReply:
        return await self._inner.proactive(event=event, profile=self._delegated(profile))
