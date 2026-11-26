"""A native sign-in's public state; no schema can return its credentials."""

from typing import Literal

from pydantic import Field

from app.schemas.base import BaseSchema


class ClaudeSubscriptionRead(BaseSchema):
    available: bool
    connected: bool = False
    state: Literal[
        "disconnected", "starting", "awaiting_code", "verifying", "connected", "error"
    ] = "disconnected"
    error_code: str | None = Field(default=None, max_length=64, pattern=r"^CLAUDE_[A-Z_]+$")
