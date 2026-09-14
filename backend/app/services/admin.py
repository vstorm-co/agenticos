"""Admin overview / observability service.

Reads aggregate counts across users and conversations and exposes them to the
dashboard. All reads - no mutation. Should remain cheap (single COUNT(*) per
metric); if usage grows we'd promote to materialized views.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.core.audit import record_audit
from app.core.exceptions import NotFoundError
from app.db.models.agent import Agent
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.session import Session as UserSession
from app.db.models.user import User
from app.repositories import member as member_repo
from app.repositories import organization as organization_repo

logger = logging.getLogger(__name__)

# The member list on the admin's per-tenant page is bounded; `member_count` still
# carries the true total, so a tenant larger than this shows the count and the
# first names rather than an unbounded fetch on a page nobody pages.
_ADMIN_MEMBER_LIMIT = 500


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

    async def list_organizations(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        search: str | None = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        kind: str = "all",
    ) -> dict[str, Any]:
        """Every organization in the deployment, with member and agent counts.

        The platform admin's view - deliberately cross-tenant, which is why it
        lives behind the `is_app_admin` gate and nowhere else.
        """
        rows, total = await organization_repo.admin_list_with_counts(
            self.db,
            skip=skip,
            limit=limit,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            kind=kind,
        )
        items = [
            {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "is_personal": org.is_personal,
                "member_count": member_count,
                "agent_count": agent_count,
                # Null when an organization has no owner at all - possible after
                # the last one leaves, and the reason the admin needs to see it.
                "owner_user_id": owner_user_id,
                "owner_email": owner_email,
                "owner_name": owner_name,
                "created_at": org.created_at,
            }
            for org, member_count, agent_count, owner_user_id, owner_email, owner_name in rows
        ]
        return {"items": items, "total": total}

    async def get_organization_detail(self, org_id: UUID, *, actor_user_id: UUID) -> dict[str, Any]:
        """One organization in full for the deployment admin, and record that they looked.

        The per-tenant page behind `/admin/organizations` (#1245). Read-only and
        metadata only: the members and their roles, the size, the owner and the
        budget - never the tenant's agents, conversations or secrets, which the
        tenant boundary keeps to the tenant. Behind the `is_app_admin` gate, and
        the cross-tenant read is itself an audit entry, because a bypass is exactly
        what the trail exists to hold to account.

        Raises:
            NotFoundError: If no organization has this id.
        """
        row = await organization_repo.admin_get_with_counts(self.db, org_id)
        if row is None:
            raise NotFoundError(
                message="Organization not found", details={"organization_id": org_id}
            )
        org, member_count, agent_count, owner_user_id, owner_email, owner_name = row
        members = [
            {"user_id": member.user_id, "email": email, "name": full_name, "role": member.role}
            for member, email, full_name, _avatar_url, _avatar_color in await member_repo.list_for_org(
                self.db, org_id, limit=_ADMIN_MEMBER_LIMIT
            )
        ]
        await record_audit(
            self.db,
            actor_user_id=actor_user_id,
            action="admin.organization.read",
            organization_id=org_id,
            target_type="organization",
            target_id=str(org_id),
        )
        return {
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
            "is_personal": org.is_personal,
            "member_count": member_count,
            "agent_count": agent_count,
            "owner_user_id": owner_user_id,
            "owner_email": owner_email,
            "owner_name": owner_name,
            "created_at": org.created_at,
            "monthly_budget_usd": org.monthly_budget_usd,
            "members": members,
        }
