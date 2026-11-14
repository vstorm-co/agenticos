"""A shared skill cannot rewrite the shipped assistant for a more privileged caller (#2882)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.resource_grant import GrantLevel
from app.db.models.skill import Skill
from app.services.access import SKILL, accessible_ids, resolve_access
from app.services.skills import SkillService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def skill_for(ctx: AuthContext, name: str) -> Skill:
    return Skill(
        id=uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name=name,
        content="Instructions",
        description="Purpose",
        visibility="org",
    )


@pytest.mark.parametrize(
    "role,allowed", [("builder", False), ("member", False), ("admin", True), ("owner", True)]
)
async def test_platform_skill_write_requires_shipped_agent_edit_authority(
    role: str, allowed: bool
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=role)
    row = skill_for(ctx, "platform-agents")
    db = AsyncMock(spec=AsyncSession)
    with patch(
        "app.services.access.resource_grant_repo.get_level", AsyncMock(return_value=GrantLevel.EDIT)
    ):
        assert await resolve_access(db, ctx, row, Perm.SKILLS_EDIT, resource_type=SKILL) is allowed
        assert await resolve_access(db, ctx, row, Perm.SKILLS_VIEW, resource_type=SKILL)


async def test_batch_editability_matches_detail_even_with_an_explicit_edit_grant() -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="builder")
    protected, ordinary = skill_for(ctx, "platform-agents"), skill_for(ctx, "team-checklist")
    db = AsyncMock(spec=AsyncSession)
    with patch(
        "app.services.access.visible_resource_ids",
        AsyncMock(return_value=[protected.id, ordinary.id]),
    ):
        assert await accessible_ids(
            db, ctx, [protected, ordinary], Perm.SKILLS_EDIT, resource_type=SKILL
        ) == {ordinary.id}


@pytest.mark.parametrize("operation", ["get", "delete", "update"])
async def test_all_skill_mutations_use_the_central_refusal(operation: str) -> None:
    from app.schemas.skill import SkillUpdate

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="builder")
    row = skill_for(ctx, "platform-agents")
    db = AsyncMock(spec=AsyncSession)
    with patch("app.services.skills.skill_repo.get", AsyncMock(return_value=row)):
        service = SkillService(db)
        with pytest.raises(NotFoundError):
            if operation == "get":
                await service.get(ctx, row.id, perm=Perm.SKILLS_EDIT)
            elif operation == "delete":
                await service.delete(ctx, row.id)
            else:
                await service.update(ctx, row.id, SkillUpdate(description="Replaced"))


async def test_builder_cannot_claim_a_reserved_platform_name_before_seeding() -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="builder")
    db = AsyncMock(spec=AsyncSession)
    with (
        patch("app.services.skills.skill_repo.get_by_name", AsyncMock(return_value=None)),
        patch("app.services.skills.skill_repo.create", AsyncMock()) as create,
    ):
        with pytest.raises(AuthorizationError):
            await SkillService(db).create(
                ctx, name="platform-agents", description="Claimed", content="Changed"
            )
        create.assert_not_awaited()


async def test_http_mutation_cannot_bypass_platform_skill_protection(mock_redis) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.api import deps
    from app.main import app

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="builder")
    row = skill_for(ctx, "platform-agents")
    db = AsyncMock(spec=AsyncSession)
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_skill_service] = lambda: SkillService(db)
    try:
        with patch("app.services.skills.skill_repo.get", AsyncMock(return_value=row)):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.patch(
                    f"/api/v1/skills/{row.id}", json={"description": "Replaced"}
                )
                assert response.status_code == 404
                assert "Changed" not in response.text
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
