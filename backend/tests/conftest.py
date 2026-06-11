"""Test fixtures. The container is rebuilt on a temp SQLite DB per test."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.config.settings import AppSettings
from app.di_container import container as container_module
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: object) -> Iterator[TestClient]:
    """A TestClient backed by an isolated temp SQLite database."""
    db_path = f"{tmp_path}/test.db"  # type: ignore[str-bytes-safe]
    test_settings = AppSettings(database_url=f"sqlite:///{db_path}")
    test_container = container_module.Container(test_settings)

    container_module.get_container.cache_clear()
    original = container_module.get_container
    container_module.get_container = lambda: test_container  # type: ignore[assignment]
    try:
        with TestClient(create_app()) as test_client:
            yield test_client
    finally:
        container_module.get_container = original  # type: ignore[assignment]
        container_module.get_container.cache_clear()
