"""Test fixtures. The container is rebuilt on a temp SQLite DB per test.

The default ``client`` uses the registry-resolved gateway (OpenAICompatible),
which never hits the network in these tests because no test calls it without a
mock. Tests that exercise the API end-to-end use ``dummy_agent_client`` to swap
in a deterministic in-memory gateway, keeping external APIs mocked (CLAUDE.md).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
from app.application.ports.agent_gateway import AgentGateway
from app.config.settings import AppSettings
from app.di_container import container as container_module
from app.di_container import dependencies as dependencies_module
from app.infrastructure.agent.dummy_agent_gateway import DummyAgentGateway
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def anyio_backend() -> str:
    """Run ``@pytest.mark.anyio`` tests on asyncio only (no trio dep)."""
    return "asyncio"


@contextmanager
def _client_with_container(container: container_module.Container) -> Iterator[TestClient]:
    # ``dependencies`` binds ``get_container`` at import time, so patch both the
    # module attribute and that bound reference for full test isolation.
    container_module.get_container.cache_clear()
    original = container_module.get_container

    def _stub() -> container_module.Container:
        return container

    container_module.get_container = _stub  # type: ignore[assignment]
    dependencies_module.get_container = _stub  # type: ignore[assignment]
    try:
        with TestClient(create_app()) as test_client:
            yield test_client
    finally:
        container_module.get_container = original  # type: ignore[assignment]
        dependencies_module.get_container = original  # type: ignore[assignment]
        container_module.get_container.cache_clear()


def _make_container(
    tmp_path: object, gateway: AgentGateway | None = None
) -> container_module.Container:
    db_path = f"{tmp_path}/test.db"  # type: ignore[str-bytes-safe]
    test_settings = AppSettings(database_url=f"sqlite:///{db_path}")
    container = container_module.Container(test_settings)
    if gateway is not None:
        container._agent_gateway = gateway  # noqa: SLF001  (test-only injection)
    return container


@pytest.fixture
def client(tmp_path: object) -> Iterator[TestClient]:
    """A TestClient backed by an isolated temp SQLite database."""
    with _client_with_container(_make_container(tmp_path)) as test_client:
        yield test_client


@pytest.fixture
def dummy_agent_client(tmp_path: object) -> Iterator[TestClient]:
    """A TestClient whose AgentGateway is the deterministic dummy."""
    container = _make_container(tmp_path, gateway=DummyAgentGateway())
    with _client_with_container(container) as test_client:
        yield test_client


@pytest.fixture
def agent_client_factory(
    tmp_path: object,
) -> Iterator[Callable[[AgentGateway], TestClient]]:
    """Build a TestClient with a caller-supplied AgentGateway."""
    managers: list[object] = []

    def _build(gateway: AgentGateway) -> TestClient:
        container = _make_container(tmp_path, gateway=gateway)
        cm = _client_with_container(container)
        client = cm.__enter__()
        managers.append(cm)
        return client

    try:
        yield _build
    finally:
        for cm in reversed(managers):
            cm.__exit__(None, None, None)  # type: ignore[attr-defined]
