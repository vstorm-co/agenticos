"""Admin-only schemas - workspace stats."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.schemas.base import BaseSchema


class AdminStats(BaseSchema):
    """Workspace-wide aggregate metrics shown on /admin overview.

    No billing fields. AgenticOS is self-hosted and has no billing, and the
    `mrr_cents` and `credits_charged_30d` the template shipped were computed
    as the literal 0 - a revenue figure on a dashboard that had never counted
    anything.
    """

    total_users: int
    active_users_24h: int
    total_organizations: int
    total_agents: int
    total_conversations: int
    total_messages: int


class AdminOrganizationRead(BaseSchema):
    """One organization as the platform admin sees it - every tenant, with size.

    The owner is the earliest of them, and every field of it is nullable: an
    organization whose last owner left has none, which is a state the deployment
    admin is the one person able to fix and so the one person who must see it.
    """

    id: UUID
    name: str
    slug: str
    is_personal: bool
    member_count: int
    agent_count: int
    owner_user_id: UUID | None = None
    owner_email: str | None = None
    owner_name: str | None = None
    created_at: datetime


class AdminOrganizationList(BaseSchema):
    items: list[AdminOrganizationRead]
    total: int
