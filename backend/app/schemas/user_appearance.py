"""Closed appearance tokens shared by the console and the person's agent.

No selector, URL, font source or raw CSS is accepted. Presets resolve to trusted
theme variables in the frontend; an unknown field is an error rather than a
silently ignored attempt to change another person's account.
"""

from typing import Literal

from pydantic import ConfigDict

from app.schemas.base import BaseSchema


class UserAppearance(BaseSchema):
    """The account's appearance. Omitted PATCH fields keep their saved value."""

    model_config = ConfigDict(extra="forbid")

    theme: Literal["light", "dark", "system"] = "system"
    look: Literal["standard", "glass", "graphite", "midnight", "paper"] = "standard"
    accent: Literal["default", "blue", "violet", "green", "amber", "rose"] = "default"
    radius: Literal["default", "square", "rounded"] = "default"
    text_size: Literal["default", "large"] = "default"
    motion: Literal["system", "reduce", "full"] = "system"
    voice_glow: Literal["vivid", "subtle", "off"] = "subtle"
    workflow_nodes: Literal["colour", "simple"] = "colour"
