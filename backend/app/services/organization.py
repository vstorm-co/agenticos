import contextlib
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm, role_has
from app.db.models.organization import Organization, OrganizationMember, OrgRole
from app.repositories import member_repo, organization_repo
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationList,
    OrganizationRead,
    OrganizationUpdate,
)
from app.services import skill_library
from app.services.file_storage import get_file_storage
from app.services.skills import SkillService

logger = logging.getLogger(__name__)


def _org_read(org: Organization, member_count: int, role: str) -> OrganizationRead:
    """One organization as a member of it sees it.

    `member_count` and `role` are not on the row - the first is a count over
    the membership table, the second is the caller's own membership - so every
    response has to carry them in alongside it.
    """
    return OrganizationRead(
        id=org.id,
        name=org.name,
        slug=org.slug,
        is_personal=org.is_personal,
        avatar_url=org.avatar_url,
        member_count=member_count,
        role=role,
        monthly_budget_usd=org.monthly_budget_usd,
        created_at=org.created_at,
        updated_at=org.updated_at,
    )


class OrganizationService:
    _ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, org_id: UUID) -> Organization:
        org = await organization_repo.get_by_id(self.db, org_id)
        if not org:
            raise NotFoundError(message="Organization not found", details={"org_id": str(org_id)})
        return org

    async def get_for_user(
        self, org_id: UUID, user_id: UUID
    ) -> tuple[Organization, OrganizationMember]:
        """Get org and verify current user is a member. Returns (org, membership)."""
        membership = await member_repo.get(self.db, organization_id=org_id, user_id=user_id)
        if not membership:
            raise NotFoundError(message="Organization not found", details={"org_id": str(org_id)})
        org = await organization_repo.get_by_id(self.db, org_id)
        if not org:
            raise NotFoundError(message="Organization not found", details={"org_id": str(org_id)})
        return org, membership

    async def read_for_user(self, org_id: UUID, user_id: UUID) -> OrganizationRead:
        """One organization, shaped for the member asking for it.

        Every route answering with a single organization ends here, including
        the ones that just changed it: a PATCH answers with the row as it now
        stands, and its member count and the caller's role are part of that.
        Two of them used to reach that by listing *every* organization the
        caller belongs to and scanning for the one they already held - a query
        per organization, to re-find one row.
        """
        org, membership = await self.get_for_user(org_id, user_id)
        count = await organization_repo.count_members(self.db, org_id)
        return _org_read(org, member_count=count, role=membership.role)

    async def list_readable_for_user(self, user_id: UUID) -> OrganizationList:
        """Every organization the caller belongs to, each with role and size."""
        rows = await self.list_for_user(user_id)
        items = [_org_read(row["org"], row["member_count"], row["role"]) for row in rows]
        return OrganizationList(items=items, total=len(items))

    async def list_for_user(self, user_id: UUID) -> list[dict]:
        orgs = await organization_repo.list_for_user(self.db, user_id)
        result = []
        for org in orgs:
            membership = await member_repo.get(self.db, organization_id=org.id, user_id=user_id)
            count = await organization_repo.count_members(self.db, org.id)
            result.append(
                {
                    "org": org,
                    "role": membership.role if membership else OrgRole.MEMBER.value,
                    "member_count": count,
                }
            )
        return result

    async def create(self, data: OrganizationCreate, owner_id: UUID) -> Organization:
        """Create a new team organization (non-personal)."""
        slug = data.slug
        if slug:
            if await organization_repo.slug_exists(self.db, slug):
                raise AlreadyExistsError(
                    message=(
                        f"The slug '{slug}' is taken. It is this organization's address in URLs "
                        "and has to be unique across the platform - pick a different one, or "
                        "leave it blank and one will be derived from the name."
                    ),
                    details={"slug": slug},
                )
        else:
            slug = await organization_repo.generate_unique_slug(self.db, data.name)

        org = await organization_repo.create(
            self.db,
            name=data.name,
            slug=slug,
            created_by_user_id=owner_id,
            is_personal=False,
            monthly_budget_usd=settings.DEFAULT_ORG_MONTHLY_BUDGET_USD,
        )
        await member_repo.create(
            self.db,
            organization_id=org.id,
            user_id=owner_id,
            role=OrgRole.OWNER.value,
        )
        await self._seed_bundled_skills(org.id, owner_id)
        return org

    async def _seed_bundled_skills(self, organization_id: UUID, owner_id: UUID) -> None:
        """Copy every bundled skill into a brand-new organization.

        Implicit rather than an Install click (#281): a spec binds a skill by
        row id, so a bundled skill has to be a row before the Builder can offer
        it - and gating that row behind a per-person Install button meant two
        lists on the skills page and a step with no decision in it. Seeded as
        the owner with organization visibility, the same shape `seed-skills`
        and the listing's own top-up (`SkillService._ensure_bundled`) write -
        the catalog is always present, and disabling a skill is how an
        organization retires one.
        """
        service = SkillService(self.db)
        ctx = AuthContext(
            user_id=owner_id,
            organization_id=organization_id,
            role=OrgRoleName.OWNER,
        )
        for bundled in skill_library.library():
            try:
                await service.install_from_library(ctx, bundled.key)
            except AlreadyExistsError:
                # Two bundled folders declaring one name - nothing validates the
                # library's own uniqueness. Skipping the twin keeps a packaging
                # mistake from refusing every registration on the deployment;
                # the seed-skills command tolerates the same collision.
                logger.warning("Bundled skill %r shares a name with another; skipped", bundled.key)

    async def create_personal_org(self, user_id: UUID, email: str) -> Organization:
        """Create the Personal Organization for a newly registered user.

        It starts with the deployment's default monthly budget
        (`DEFAULT_ORG_MONTHLY_BUDGET_USD`, $100 unless configured otherwise), so
        a fresh account is not one runaway agent away from a surprise bill. A
        deployment that would rather start uncapped sets that to nothing.
        """
        slug = await organization_repo.generate_unique_slug(self.db, email.split("@")[0])
        org = await organization_repo.create(
            self.db,
            name="Personal",
            slug=slug,
            created_by_user_id=user_id,
            is_personal=True,
            monthly_budget_usd=settings.DEFAULT_ORG_MONTHLY_BUDGET_USD,
        )
        await member_repo.create(
            self.db,
            organization_id=org.id,
            user_id=user_id,
            role=OrgRole.OWNER.value,
        )
        await self._seed_bundled_skills(org.id, user_id)
        return org

    async def update(
        self,
        org_id: UUID,
        data: OrganizationUpdate,
        requester_id: UUID,
    ) -> Organization:
        """Update org metadata and settings.

        Two permissions decide this PATCH, each covering the fields it names:
        `org:settings` for the metadata (name, avatar), `budgets:manage` for
        the monthly spending cap. The built-in Owner and Admin hold both, so
        nothing changes for them - but the catalog advertises `budgets:manage`
        as its own entitlement, and a permission the matrix shows and no
        endpoint consults is a row that means nothing.
        """
        org, membership = await self.get_for_user(org_id, requester_id)
        wants_budget = "monthly_budget_usd" in data.model_fields_set
        wants_metadata = bool(data.model_fields_set - {"monthly_budget_usd"})
        if wants_metadata and not role_has(membership.role, Perm.ORG_SETTINGS):
            raise AuthorizationError(message="Only Owner or Admin can update the organization")
        if wants_budget and not role_has(membership.role, Perm.BUDGETS_MANAGE):
            raise AuthorizationError(
                message="Changing the spending limit requires 'budgets:manage'"
            )

        if wants_budget:
            # Keyed on the field being named, not on its value: an explicit
            # `null` lifts the ceiling, and every other PATCH must leave it
            # exactly where it was.
            org = await organization_repo.set_monthly_budget(
                self.db, org, limit_usd=data.monthly_budget_usd
            )

        return await organization_repo.update(
            self.db,
            org,
            name=data.name,
            avatar_url=data.avatar_url,
        )

    async def delete(self, org_id: UUID, requester_id: UUID) -> None:
        """Delete org. Requires OWNER role. Personal orgs cannot be deleted."""
        org, membership = await self.get_for_user(org_id, requester_id)

        if org.is_personal:
            raise BadRequestError(message="Personal organization cannot be deleted")
        if not role_has(membership.role, Perm.ORG_DELETE):
            raise AuthorizationError(message="Only the Owner can delete the organization")

        await organization_repo.delete(self.db, org)

    async def upload_avatar(
        self,
        org_id: UUID,
        requester_id: UUID,
        file_data: bytes,
        filename: str,
        content_type: str | None,
    ) -> Organization:
        """Replace the organization avatar. Requires ADMIN or OWNER role.

        Raises:
            BadRequestError: If file type or size is invalid.
            AuthorizationError: If requester is not Owner or Admin.
        """
        if content_type not in self._ALLOWED_AVATAR_TYPES:
            raise BadRequestError(message="Only JPEG, PNG, WebP, and GIF images are allowed")
        if len(file_data) > 2 * 1024 * 1024:
            raise BadRequestError(message="Avatar image too large. Maximum 2MB.")

        org, membership = await self.get_for_user(org_id, requester_id)
        if not role_has(membership.role, Perm.ORG_SETTINGS):
            raise AuthorizationError(message="Only Owner or Admin can update the org")

        storage = get_file_storage()
        if org.avatar_url:
            with contextlib.suppress(Exception):
                await storage.delete(org.avatar_url)
        storage_path = await storage.save(f"avatars/orgs/{org_id}", filename, file_data)
        return await organization_repo.update(self.db, org, avatar_url=storage_path)

    def get_avatar_path(self, avatar_url: str) -> str | None:
        full_path = get_file_storage().get_full_path(avatar_url)
        return str(full_path) if full_path is not None else None
