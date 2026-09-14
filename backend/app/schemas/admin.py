"""Admin-only schemas - workspace stats."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
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


class AdminOrganizationMember(BaseSchema):
    """One member of a tenant, as the deployment admin inspecting it sees them."""

    user_id: UUID
    email: str
    name: str | None = None
    role: str


class AdminOrganizationDetail(AdminOrganizationRead):
    """One organization in full, for the deployment admin's per-tenant page (#1245).

    Metadata only, and deliberately so: the members and their roles, the size, the
    owner and the budget - never the tenant's agents, conversations or secrets,
    which the tenant boundary in `docs/architecture.md` keeps to the tenant. The
    read is behind the `is_app_admin` gate and is itself recorded in the audit
    trail.
    """

    members: list[AdminOrganizationMember]
    monthly_budget_usd: Decimal | None = None
