"""Schemas for a person's pinned sidebar items."""

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

MAX_NAV_PINS = 100
_ITEM_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,63}$")


def _check_item_id(value: str) -> str:
    if not _ITEM_ID.fullmatch(value):
        raise ValueError(
            "pinned item ids are letters and digits, starting with a letter, at most 64 long"
        )
    return value


def _check_unique(ids: list[str]) -> list[str]:
    if len(set(ids)) != len(ids):
        raise ValueError("a navigation item can be pinned only once")
    return ids


NavItemId = Annotated[str, AfterValidator(_check_item_id)]


class NavPinsUpdate(BaseModel):
    """The full ordered pin list; replaces whatever was saved."""

    model_config = ConfigDict(extra="forbid")

    item_ids: Annotated[
        list[NavItemId], Field(max_length=MAX_NAV_PINS), AfterValidator(_check_unique)
    ]


class NavPinsRead(BaseModel):
    """The caller's pins; an empty list when nothing is pinned."""

    item_ids: list[str]
