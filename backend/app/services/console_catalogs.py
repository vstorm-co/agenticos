"""Resolve catalog ceilings without changing account access or runtime bindings."""

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm, Scope
from app.repositories import deployment_settings_repo, member_repo, organization_repo
from app.schemas.console_catalogs import CatalogPolicy
from app.schemas.console_presentation import (
    StoredConsolePreferences,
    StoredRoleConsole,
    stored_role_defaults,
)

CatalogKind = Literal["mcp_gallery", "skill_gallery"]


def _policy(
    preferences: StoredConsolePreferences | StoredRoleConsole, kind: CatalogKind
) -> CatalogPolicy:
    return (
        preferences.mcp_gallery if kind == "mcp_gallery" else preferences.skill_gallery
    ) or CatalogPolicy()


class ConsoleCatalogService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def policies(self, ctx: AuthContext, kind: CatalogKind) -> tuple[CatalogPolicy, ...]:
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        if organization is None:
            raise NotFoundError(message="Organization not found", details={})
        deployment = await deployment_settings_repo.get(self.db)
        available = StoredConsolePreferences.model_validate(
            deployment.console_availability or {} if deployment else {}
        )
        role = stored_role_defaults(organization.console_role_defaults).get(
            ctx.role, StoredRoleConsole()
        )
        member = (
            await member_repo.get_active(
                self.db, organization_id=ctx.organization_id, user_id=ctx.user_id
            )
            if ctx.user_id is not None and not ctx.subject_is_publisher_fallback
            else None
        )
        personal = StoredConsolePreferences.model_validate(
            member.console_preferences or {} if member else {}
        )
        manages = (
            ctx.has(Perm.MCP_MANAGE)
            if kind == "mcp_gallery"
            else ctx.scope_for(Perm.SKILLS_EDIT) >= Scope.SHARED
        )
        inherited = () if manages else (_policy(role, kind),)
        return (
            _policy(available, kind),
            *inherited,
            _policy(personal, kind),
        )
