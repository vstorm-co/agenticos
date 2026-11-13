"""Organization role preferences for the sidebar, without changing authorization."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm, assignable_roles
from app.db.models.organization import Organization
from app.repositories import organization_repo
from app.schemas.permissions import (
    NAVIGATION_ITEM_IDS,
    RoleNavigationRead,
    RoleNavigationUpdate,
)


class RoleNavigationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _editable_roles(ctx: AuthContext) -> list[OrgRoleName]:
        if not ctx.has(Perm.ROLES_MANAGE):
            return []
        allowed = assignable_roles(OrgRoleName.OWNER if ctx.is_app_admin else ctx.role)
        return [role for role in OrgRoleName if role in allowed]

    @classmethod
    def _read_for(cls, ctx: AuthContext, organization: Organization) -> RoleNavigationRead:
        stored = organization.role_navigation or {}
        return RoleNavigationRead(
            hidden_items={
                role: [] if role == OrgRoleName.OWNER else list(stored.get(role, []))
                for role in OrgRoleName
            },
            configurable_items=list(NAVIGATION_ITEM_IDS),
            editable_roles=cls._editable_roles(ctx),
        )

    async def read(self, ctx: AuthContext) -> RoleNavigationRead:
        """Read the policy only for the organization authenticated by this request."""
        organization = await self._organization(ctx)
        return self._read_for(ctx, organization)

    async def for_caller(self, ctx: AuthContext) -> list[str]:
        """The caller's presentation preferences; owners and app admins retain recovery."""
        if ctx.is_app_admin or ctx.role == OrgRoleName.OWNER:
            return []
        organization = await self._organization(ctx)
        return list((organization.role_navigation or {}).get(ctx.role, []))

    async def update(
        self, ctx: AuthContext, role: OrgRoleName, data: RoleNavigationUpdate
    ) -> RoleNavigationRead:
        """Change only a strictly lower role, audited in the same transaction.

        Neither role permissions nor resource grants are rewritten. A scoped API
        key must itself carry roles:manage even when its issuer is an owner.
        """
        if role not in self._editable_roles(ctx):
            raise AuthorizationError(
                message="Only a role manager with greater authority may change this sidebar",
                details={"role": role, "required": [Perm.ROLES_MANAGE.value]},
            )
        organization = await organization_repo.set_role_navigation(
            self.db,
            organization_id=ctx.organization_id,
            role=role.value,
            hidden_items=data.hidden_items,
        )
        if organization is None:
            raise NotFoundError(
                message="Organization not found or access denied",
                details={"org_id": ctx.organization_id},
            )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="roles.navigation.updated",
            target_type="organization",
            target_id=str(ctx.organization_id),
            details={"role": role.value, "hidden_items": data.hidden_items},
        )
        return self._read_for(ctx, organization)

    async def _organization(self, ctx: AuthContext) -> Organization:
        if ctx.is_anonymous:
            raise AuthorizationError(message="A signed-in organization member is required")
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        if organization is None:
            raise NotFoundError(
                message="Organization not found or access denied",
                details={"org_id": ctx.organization_id},
            )
        return organization
