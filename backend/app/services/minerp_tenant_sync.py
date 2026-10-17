"""Provision team orgs mapped to Minerp IAM tenant_ids (platform multi-tenant)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.iam_tenant import iam_may_access_minerp_tenant, parse_iam_tenant_ids
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.organization import OrgRole
from app.clients.minerp_auth_tenant import fetch_minerp_tenant_display_name
from app.integrations.minerp_shop.provision import ensure_minerp_shop_mcp_for_org
from app.repositories import member_repo, organization_repo
from app.services import skill_library
from app.services.skills import SkillService
from app.core.exceptions import AlreadyExistsError
from app.db.models.organization import Organization

logger = logging.getLogger(__name__)


async def sync_tenant_orgs_from_iam_payload(
    db: AsyncSession,
    *,
    user_id: UUID,
    payload: dict[str, Any],
) -> None:
    """Ensure one team org per JWT tenant_id and membership for the IAM user."""
    if not settings.MINERP_TENANT_ORG_SYNC_ENABLED:
        return
    tenant_ids = parse_iam_tenant_ids(payload)
    if not tenant_ids:
        return

    for tenant_id in tenant_ids:
        org = await organization_repo.get_by_minerp_tenant_id(db, tenant_id)
        if org is None:
            org = await _provision_minerp_tenant_org(db, user_id=user_id, tenant_id=tenant_id)
        else:
            await _maybe_refresh_placeholder_org_name(db, org=org, tenant_id=tenant_id)
        await ensure_minerp_shop_mcp_for_org(
            db,
            organization_id=org.id,
            created_by_user_id=user_id,
        )
        membership = await member_repo.get(db, organization_id=org.id, user_id=user_id)
        if membership is None:
            await member_repo.create(
                db,
                organization_id=org.id,
                user_id=user_id,
                role=OrgRole.MEMBER.value,
            )
            logger.info(
                "minerp_tenant_org_member_added",
                extra={"user_id": str(user_id), "tenant_id": str(tenant_id), "org_id": str(org.id)},
            )


def _default_minerp_tenant_org_name(tenant_id: UUID) -> str:
    return f"Minerp tenant {tenant_id.hex[:8]}"


def _is_placeholder_minerp_org_name(name: str, tenant_id: UUID) -> bool:
    return name.strip() == _default_minerp_tenant_org_name(tenant_id)


async def _resolve_org_display_name(tenant_id: UUID) -> str:
    display = await fetch_minerp_tenant_display_name(tenant_id)
    if display:
        return display
    return _default_minerp_tenant_org_name(tenant_id)


async def _maybe_refresh_placeholder_org_name(
    db: AsyncSession,
    *,
    org: Organization,
    tenant_id: UUID,
) -> None:
    if not _is_placeholder_minerp_org_name(org.name, tenant_id):
        return
    display = await fetch_minerp_tenant_display_name(tenant_id)
    if not display or display == org.name:
        return
    await organization_repo.update(db, org, name=display)
    logger.info(
        "minerp_tenant_org_name_refreshed",
        extra={"org_id": str(org.id), "tenant_id": str(tenant_id), "name": display},
    )


async def _provision_minerp_tenant_org(
    db: AsyncSession,
    *,
    user_id: UUID,
    tenant_id: UUID,
) -> Organization:
    name = await _resolve_org_display_name(tenant_id)
    slug_base = f"minerp-{tenant_id.hex[:12]}"
    slug = slug_base
    if await organization_repo.slug_exists(db, slug):
        slug = await organization_repo.generate_unique_slug(db, slug_base)

    org = await organization_repo.create(
        db,
        name=name,
        slug=slug,
        created_by_user_id=user_id,
        is_personal=False,
        monthly_budget_usd=settings.DEFAULT_ORG_MONTHLY_BUDGET_USD,
        minerp_tenant_id=tenant_id,
    )
    await member_repo.create(
        db,
        organization_id=org.id,
        user_id=user_id,
        role=OrgRole.OWNER.value,
    )
    await _seed_bundled_skills(db, organization_id=org.id, owner_id=user_id)
    logger.info(
        "minerp_tenant_org_provisioned",
        extra={"user_id": str(user_id), "tenant_id": str(tenant_id), "org_id": str(org.id)},
    )
    return org


async def _seed_bundled_skills(db: AsyncSession, *, organization_id: UUID, owner_id: UUID) -> None:
    service = SkillService(db)
    ctx = AuthContext(
        user_id=owner_id,
        organization_id=organization_id,
        role=OrgRoleName.OWNER,
    )
    for bundled in skill_library.library():
        try:
            await service.install_from_library(ctx, bundled.key)
        except AlreadyExistsError:
            pass


async def pick_default_organization_for_iam_user(
    db: AsyncSession,
    *,
    user_id: UUID,
    payload: dict[str, Any],
) -> UUID | None:
    """Prefer the first team org whose minerp_tenant_id is allowed on the JWT."""
    allowed = set(parse_iam_tenant_ids(payload))
    if payload.get("has_global_scope") is True:
        pairs = await organization_repo.list_for_user(db, user_id)
        for org, _role in pairs:
            if org.minerp_tenant_id is not None and not org.is_personal:
                return org.id
        return None
    if not allowed:
        return None
    pairs = await organization_repo.list_for_user(db, user_id)
    for org, _role in pairs:
        if org.minerp_tenant_id in allowed:
            return org.id
    return None
