"""Provider -> concrete AgentGateway resolution via a registry.

Adding a provider means adding a builder and one registry entry — no growing
``if``/``elif`` chain (CLAUDE.md / design-spec §13 maintainability). The
registry maps an :class:`AgentType` to a builder that takes the app settings
and returns a concrete :class:`AgentGateway`.
"""

from __future__ import annotations

from collections.abc import Callable

from app.application.ports.agent_gateway import AgentGateway
from app.config.settings import AppSettings
from app.domain.agent.value_objects import AgentType

from .hermes_agent_gateway import HermesAgentGateway
from .openai_compatible_gateway import OpenAICompatibleGateway
from .openclaw_gateway import OpenClawGateway

GatewayBuilder = Callable[[AppSettings], AgentGateway]


def _build_openai_compatible(settings: AppSettings) -> AgentGateway:
    return OpenAICompatibleGateway(
        base_url=settings.agent_base_url,
        api_key=settings.agent_api_key,
        model=settings.default_agent_model,
        timeout_s=settings.agent_request_timeout_s,
    )


def _build_hermes(settings: AppSettings) -> AgentGateway:
    return HermesAgentGateway(
        base_url=settings.hermes_base_url,
        api_key=settings.hermes_api_key,
        model=settings.hermes_model,
        timeout_s=settings.agent_request_timeout_s,
    )


def _build_openclaw(settings: AppSettings) -> AgentGateway:
    return OpenClawGateway()


# The single source of truth for provider selection.
_BUILDERS: dict[AgentType, GatewayBuilder] = {
    AgentType.OPENAI_COMPATIBLE: _build_openai_compatible,
    AgentType.HERMES_AGENT: _build_hermes,
    AgentType.OPEN_CLAW: _build_openclaw,
}

# Provider used when the configured value is missing/unknown.
_DEFAULT_TYPE = AgentType.OPENAI_COMPATIBLE


def build_agent_gateway(settings: AppSettings) -> AgentGateway:
    """Resolve and construct the configured AgentGateway.

    Falls back to the default provider if ``default_agent_type`` is unset or
    not a known :class:`AgentType` (so a typo never crashes startup).
    """
    try:
        agent_type = AgentType(settings.default_agent_type)
    except ValueError:
        agent_type = _DEFAULT_TYPE
    builder = _BUILDERS.get(agent_type, _BUILDERS[_DEFAULT_TYPE])
    return builder(settings)
