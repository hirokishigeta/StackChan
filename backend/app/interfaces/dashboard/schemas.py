"""Dashboard view models."""

from __future__ import annotations

from pydantic import BaseModel


class BotSummary(BaseModel):
    """One row in the dashboard Bot list."""

    device_id: str
    name: str
    firmware_version: str
    connection_status: str
