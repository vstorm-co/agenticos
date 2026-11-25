"""Bounded catalog presentation choices, independent of runtime tool permissions."""

from collections.abc import Collection, Sequence
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.schemas.base import BaseSchema

CatalogKey = Annotated[str, StringConstraints(min_length=1, max_length=255)]


class CatalogPolicy(BaseSchema):
    """Available means organization connections for MCP, visible installed skills otherwise."""

    model_config = ConfigDict(extra="forbid")
    mode: Literal["all", "allow-list", "available"] = "all"
    keys: list[CatalogKey] = Field(default_factory=list, max_length=512)

    @field_validator("keys")
    @classmethod
    def unique_keys(cls, value: list[str]) -> list[str]:
        if any("\x00" in key for key in value):
            raise ValueError("Catalog keys cannot contain a null character")
        if len(value) != len(set(value)):
            raise ValueError("Catalog keys must be unique")
        return value

    @model_validator(mode="after")
    def allow_list_keys(self) -> Self:
        if self.mode != "allow-list" and self.keys:
            raise ValueError("Catalog keys require allow-list mode")
        return self


def catalog_intersection(
    policies: Sequence[CatalogPolicy], *, available: Collection[str]
) -> frozenset[str] | None:
    """None leaves the catalog whole; an empty set deliberately offers no entries."""
    allowed: frozenset[str] | None = None
    for policy in policies:
        if policy.mode == "all":
            continue
        selection = frozenset(policy.keys if policy.mode == "allow-list" else available)
        allowed = selection if allowed is None else allowed & selection
    return allowed
