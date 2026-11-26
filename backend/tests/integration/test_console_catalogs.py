"""Catalog filters count only visible choices, before paging, on real PostgreSQL."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.mcp_registry_server import McpRegistryServer
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.skill import Skill
from app.db.models.user import User
from app.repositories import member_repo, organization_repo
from app.services import mcp_listing, skill_library
from app.services.skills import SkillService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _caller(db: AsyncSession) -> tuple[Organization, AuthContext, User]:
    person = User(id=uuid4(), email="gallery-member@example.com", is_active=True)
    peer = User(id=uuid4(), email="gallery-peer@example.com", is_active=True)
    db.add_all([person, peer])
    await db.flush()
    organization = Organization(
        id=uuid4(), name="Gallery", slug="gallery", created_by_user_id=peer.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=person.id, role="member"))
    await db.flush()
    return (
        organization,
        AuthContext(user_id=person.id, organization_id=organization.id, role="member"),
        peer,
    )


async def test_skill_gallery_never_marks_another_persons_private_copy_installed(
    db: AsyncSession,
) -> None:
    organization, ctx, peer = await _caller(db)
    entries = [entry for industry in skill_library.gallery() for entry in industry.skills]
    public, private = entries[:2]
    visible = Skill(
        id=uuid4(),
        organization_id=organization.id,
        owner_user_id=peer.id,
        name=public.name,
        description=public.description,
        content=public.content,
        visibility="org",
    )
    hidden = Skill(
        id=uuid4(),
        organization_id=organization.id,
        owner_user_id=peer.id,
        name=private.name,
        description=private.description,
        content=private.content,
        visibility="private",
    )
    db.add_all([visible, hidden])
    await db.flush()
    service = SkillService(db)
    gallery = await service.gallery(ctx)
    by_key = {entry.key: entry for industry in gallery.industries for entry in industry.skills}
    assert by_key[public.key].installed_id == visible.id
    assert not by_key[private.key].installed and by_key[private.key].installed_id is None
    assert str(hidden.id) not in gallery.model_dump_json()
    await organization_repo.set_console_role_defaults(
        db, organization, changes={"member": {"skill_gallery": {"mode": "available"}}}
    )
    gallery = await service.gallery(ctx)
    assert [entry.key for industry in gallery.industries for entry in industry.skills] == [
        public.key
    ]
    with pytest.raises(NotFoundError):
        await service.gallery_preview(ctx, private.key)
    denied = await service.install_gallery(ctx, [private.key])
    assert denied.unknown == [private.key] and not denied.installed and not denied.skipped
    await member_repo.set_console_presentation(
        db,
        organization_id=organization.id,
        user_id=ctx.subject_id,
        changes={"skill_gallery": {"mode": "allow-list", "keys": [private.key]}},
    )
    assert (await service.gallery(ctx)).industries == []
    await member_repo.set_console_presentation(
        db, organization_id=organization.id, user_id=ctx.subject_id, changes={"skill_gallery": None}
    )
    assert (await service.gallery_preview(ctx, public.key)).name == public.name


async def test_registry_allow_list_applies_before_count_and_page(db: AsyncSession) -> None:
    organization, ctx, _peer = await _caller(db)
    approved = "org.test/approved"
    for index in range(4):
        key = approved if index == 3 else f"org.test/not-approved-{index}"
        db.add(
            McpRegistryServer(
                id=key,
                name=f"Server {index}",
                description="Example",
                url=f"https://server-{index}.example.test/mcp",
                host=f"server-{index}.example.test",
                category="development",
            )
        )
    await db.flush()
    await organization_repo.set_console_role_defaults(
        db,
        organization,
        changes={"member": {"mcp_gallery": {"mode": "allow-list", "keys": [approved]}}},
    )
    result = await mcp_listing.page(db, ctx=ctx, limit=1)
    assert [entry.key for entry in result.items] == [approved]
    assert result.total == 1 and result.registry_total == 1
    assert (await mcp_listing.page(db, ctx=ctx, skip=1, limit=1)).items == ()
    refused = await mcp_listing.page(db, ctx=ctx, query="not-approved")
    assert refused.items == () and refused.total == 0 and refused.registry_total == 1
    await member_repo.set_console_presentation(
        db,
        organization_id=organization.id,
        user_id=ctx.subject_id,
        changes={"mcp_gallery": {"mode": "all", "keys": []}},
    )
    assert (await mcp_listing.page(db, ctx=ctx)).total == 1
