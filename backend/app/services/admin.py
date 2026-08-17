"""Admin overview / observability service.

Reads aggregate counts across users and conversations and exposes them to the
dashboard. All reads - no mutation. Should remain cheap (single COUNT(*) per
metric); if usage grows we'd promote to materialized views.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.db.models.agent import Agent
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization, OrganizationMember, OrgRole
from app.db.models.session import Session as UserSession
from app.db.models.user import User

logger = logging.getLogger(__name__)


class AdminService:
    # `db` is an AsyncSession (Postgres) or a sync Session (SQLite); typed as
    # `Any` so the one shared implementation accepts both.
    def __init__(self, db: Any) -> None:
        self.db = db

    async def workspace_stats(self) -> dict[str, Any]:
        """Aggregate workspace metrics."""
        total_users = (await self.db.execute(select(func.count(User.id)))).scalar_one()

        # Active in last 24h via session.last_used_at - best-effort, returns 0
        # when session_management isn't enabled in this deployment.
        active_24h: int = 0
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        try:
            active_24h = int(
                (
                    await self.db.execute(
                        select(func.count(func.distinct(UserSession.user_id))).where(
                            UserSession.last_used_at >= cutoff
                        )
                    )
                ).scalar_one()
            )
        except Exception:
            logger.exception("admin_stats_active_users_query_failed")

        total_conversations = (
            await self.db.execute(select(func.count(Conversation.id)))
        ).scalar_one()
        total_messages = (await self.db.execute(select(func.count(Message.id)))).scalar_one()
        total_organizations = (
            await self.db.execute(select(func.count(Organization.id)))
        ).scalar_one()
        total_agents = (await self.db.execute(select(func.count(Agent.id)))).scalar_one()

        return {
            "total_users": int(total_users),
            "active_users_24h": int(active_24h),
            "total_organizations": int(total_organizations),
            "total_agents": int(total_agents),
            "total_conversations": int(total_conversations),
            "total_messages": int(total_messages),
        }

    async def list_organizations(self, *, skip: int = 0, limit: int = 50) -> dict[str, Any]:
        """Every organization in the deployment, with member and agent counts.

        The platform admin's view - deliberately cross-tenant, which is why it
        lives behind the `is_app_admin` gate and nowhere else.
        """
        member_counts = (
            select(
                OrganizationMember.organization_id,
                func.count(OrganizationMember.user_id).label("member_count"),
            )
            .group_by(OrganizationMember.organization_id)
            .subquery()
        )
        agent_counts = (
            select(Agent.organization_id, func.count(Agent.id).label("agent_count"))
            .group_by(Agent.organization_id)
            .subquery()
        )
        # Who answers for a tenant, which is the question the admin's list was
        # missing: a row of counts says how big an organization is and nothing
        # about who to ask about it. The earliest owner, because an organization
        # can hold several and the founder is the one a deployment admin means;
        # `DISTINCT ON` picks it in the same pass rather than in a query per row.
        owners = (
            select(
                OrganizationMember.organization_id,
                User.id.label("owner_user_id"),
                User.email.label("owner_email"),
                User.full_name.label("owner_name"),
            )
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.role == OrgRole.OWNER.value)
            .distinct(OrganizationMember.organization_id)
            .order_by(OrganizationMember.organization_id, OrganizationMember.joined_at)
            .subquery()
        )
        rows = await self.db.execute(
            select(
                Organization,
                func.coalesce(member_counts.c.member_count, 0),
                func.coalesce(agent_counts.c.agent_count, 0),
                owners.c.owner_user_id,
                owners.c.owner_email,
                owners.c.owner_name,
            )
            .outerjoin(member_counts, member_counts.c.organization_id == Organization.id)
            .outerjoin(agent_counts, agent_counts.c.organization_id == Organization.id)
            .outerjoin(owners, owners.c.organization_id == Organization.id)
            .order_by(Organization.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        total = (await self.db.execute(select(func.count(Organization.id)))).scalar_one()
        items = [
            {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "is_personal": org.is_personal,
                "member_count": int(member_count),
                "agent_count": int(agent_count),
                # Null when an organization has no owner at all - possible after
                # the last one leaves, and the reason the admin needs to see it.
                "owner_user_id": owner_user_id,
                "owner_email": owner_email,
                "owner_name": owner_name,
                "created_at": org.created_at,
            }
            for org, member_count, agent_count, owner_user_id, owner_email, owner_name in rows.all()
        ]
        return {"items": items, "total": int(total)}
