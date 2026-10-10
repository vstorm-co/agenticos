"""Schemas for groups - named sets of an organization's members."""

from datetime import datetime
from decimal import Decimal
from typing import Literal, get_args
from uuid import UUID

from pydantic import Field

from app.db.models.organization import MembershipSourceLiteral
from app.db.models.resource_grant import GrantLevelLiteral
from app.schemas.base import BaseSchema
from app.schemas.organization import MonthlyBudgetUsd

GroupIcon = Literal[
    "users",
    "briefcase",
    "banknote",
    "megaphone",
    "headphones",
    "code",
    "scale",
    "heart-handshake",
    "truck",
    "flask-conical",
    "graduation-cap",
    "building",
]
"""The marks a group may carry - lucide names the console draws (#2072)."""


def as_group_icon(value: str | None) -> GroupIcon | None:
    """The stored column as the vocabulary the API publishes, or a loud failure."""
    if value is None:
        return None
    for icon in get_args(GroupIcon):
        if icon == value:
            return icon
    raise ValueError(f"Not a group icon: {value!r}")


class GroupCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    icon: GroupIcon | None = None
    monthly_budget_usd: MonthlyBudgetUsd | None = Field(
        default=None,
        description=(
            "Dollars the group's people may spend in a calendar month, across every "
            "agent they run. Null is no cap of its own; the organization's still applies."
        ),
    )


class GroupUpdate(BaseSchema):
    """Rename a group or change its description; an omitted field is left as it is."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    icon: GroupIcon | None = None
    monthly_budget_usd: MonthlyBudgetUsd | None = Field(
        default=None, description="Sent as null to remove the cap; left out to keep it."
    )


class GroupRead(BaseSchema):
    id: UUID
    organization_id: UUID
    name: str
    description: str | None = None
    icon: GroupIcon | None = None
    monthly_budget_usd: Decimal | None = None
    member_count: int = 0
    created_at: datetime


class GroupList(BaseSchema):
    items: list[GroupRead]
    total: int


class GroupMemberAdd(BaseSchema):
    user_id: UUID


class GroupMemberRead(BaseSchema):
    user_id: UUID
    email: str
    full_name: str | None = None
    source: MembershipSourceLiteral
    """`directory` when a directory group mapping put this person here; the next
    sign-in may take them out again. Adding them by hand makes it `manual`."""
    is_lead: bool = False
    """Whether this person leads the group: they add and remove its members."""
    created_at: datetime


class GroupLeadUpdate(BaseSchema):
    """Make a member the group's lead, or not."""

    is_lead: bool


class GroupMemberList(BaseSchema):
    items: list[GroupMemberRead]
    total: int


GroupResourceKind = Literal["agent", "collection", "skill", "context", "artifact", "mcp_connection"]


class GroupResource(BaseSchema):
    """One thing shared with a group, named, at the level it was shared at."""

    kind: GroupResourceKind
    id: UUID
    name: str
    level: GrantLevelLiteral


class GroupResourceList(BaseSchema):
    """What a group has been given, among what the caller may see (#2072)."""

    items: list[GroupResource]
    total: int


class GroupSpendRead(BaseSchema):
    """One department's month: what its members' runs cost against its cap (#2072)."""

    group_id: UUID
    name: str
    icon: GroupIcon | None = None
    member_count: int
    monthly_budget_usd: Decimal | None = None
    spent_usd: Decimal
    run_count: int


class GroupSpendList(BaseSchema):
    """Every department's month, costliest first.

    A person in two departments counts in both, so the rows do not add up to
    the organization's bill - each answers to its own cap.
    """

    since: datetime
    items: list[GroupSpendRead]


class GroupShareItem(BaseSchema):
    """One resource to share with a group, by kind and id."""

    kind: GroupResourceKind
    id: UUID


class GroupShareRequest(BaseSchema):
    """Share several resources with one group at once, from the group's page (#2072)."""

    items: list[GroupShareItem] = Field(min_length=1, max_length=50)
    level: GrantLevelLiteral = Field(
        default="use", description="What the group may do with each: `read`, `use` or `edit`."
    )
