"""Presentation shared by a Form trigger and its public page."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FormAppearance(BaseModel):
    """Bounded presentation choices; no arbitrary CSS or HTML reaches visitors."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accent: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    width: Literal["standard", "wide"] = "standard"
    layout: Literal["card", "plain"] = "card"
