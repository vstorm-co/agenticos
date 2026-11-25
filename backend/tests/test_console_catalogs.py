"""Catalog ceilings intersect; management and personal preferences are distinct."""

from itertools import product
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.organization import Organization, OrganizationMember
from app.repositories import deployment_settings_repo, member_repo, organization_repo
from app.schemas.console_catalogs import CatalogPolicy, catalog_intersection
from app.services.console_catalogs import ConsoleCatalogService


def test_catalog_choices_reject_ambiguous_or_unbounded_input() -> None:
    assert CatalogPolicy().mode == "all"
    assert CatalogPolicy(mode="allow-list", keys=[]).keys == []
    for data in (
        {"mode": "invented"},
        {"mode": "all", "keys": ["github"]},
        {"mode": "available", "keys": ["github"]},
        {"mode": "allow-list", "keys": ["github", "github"]},
        {"mode": "allow-list", "keys": [""]},
        {"mode": "allow-list", "keys": ["bad\x00key"]},
        {"mode": "allow-list", "keys": ["a" * 256]},
        {"mode": "allow-list", "keys": [str(n) for n in range(513)]},
        {"mode": "all", "role": "owner"},
    ):
        with pytest.raises(ValidationError):
            CatalogPolicy.model_validate(data)


@pytest.mark.parametrize("modes", list(product(("all", "allow-list", "available"), repeat=3)))
def test_each_catalog_ceiling_can_only_narrow(modes: tuple[str, str, str]) -> None:
    choices = {
        "all": CatalogPolicy(),
        "allow-list": CatalogPolicy(mode="allow-list", keys=["github", "retired"]),
        "available": CatalogPolicy(mode="available"),
    }
    actual = catalog_intersection([choices[mode] for mode in modes], available={"github", "slack"})
    if modes == ("all", "all", "all"):
        assert actual is None
    elif "allow-list" in modes and "available" in modes:
        assert actual == {"github"}
    elif "allow-list" in modes:
        assert actual == {"github", "retired"}
    else:
        assert actual == {"github", "slack"}
    assert catalog_intersection([CatalogPolicy(mode="allow-list")], available={"github"}) == set()


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["owner", "builder", "member", "viewer"])
@pytest.mark.parametrize("kind", ["mcp_gallery", "skill_gallery"])
async def test_manager_bypass_never_releases_deployment_or_personal_ceiling(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    kind: str,
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=role)
    organization = Organization(
        id=ctx.organization_id,
        name="Gallery",
        slug="gallery",
        console_role_defaults={role: {kind: {"mode": "allow-list", "keys": ["org"]}}},
    )
    deployment = DeploymentSettings(
        console_availability={kind: {"mode": "allow-list", "keys": ["deployment"]}}
    )
    member = OrganizationMember(
        organization_id=ctx.organization_id,
        user_id=ctx.subject_id,
        role=role,
        console_preferences={kind: {"mode": "allow-list", "keys": ["personal"]}},
    )
    monkeypatch.setattr(organization_repo, "get_by_id", AsyncMock(return_value=organization))
    monkeypatch.setattr(deployment_settings_repo, "get", AsyncMock(return_value=deployment))
    monkeypatch.setattr(member_repo, "get_active", AsyncMock(return_value=member))
    service = ConsoleCatalogService(AsyncMock(spec=AsyncSession))
    # The kind's literal contract is tested through the two public choices.
    policies = await service.policies(
        ctx, "mcp_gallery" if kind == "mcp_gallery" else "skill_gallery"
    )
    manager = role in {"owner", "builder"}
    assert [policy.keys for policy in policies] == (
        [["deployment"], ["personal"]] if manager else [["deployment"], ["org"], ["personal"]]
    )


@pytest.mark.anyio
async def test_missing_settings_and_non_personal_contexts_do_not_load_someone_elses_preferences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = Organization(id=uuid4(), name="Gallery", slug="gallery")
    read_org = AsyncMock(return_value=organization)
    read_member = AsyncMock(return_value=None)
    monkeypatch.setattr(organization_repo, "get_by_id", read_org)
    monkeypatch.setattr(deployment_settings_repo, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(member_repo, "get_active", read_member)
    service = ConsoleCatalogService(AsyncMock(spec=AsyncSession))
    for ctx in (
        AuthContext(user_id=None, organization_id=organization.id, role="member"),
        AuthContext(
            user_id=uuid4(),
            organization_id=organization.id,
            role="member",
            subject_is_publisher_fallback=True,
        ),
    ):
        assert all(policy.mode == "all" for policy in await service.policies(ctx, "mcp_gallery"))
    read_member.assert_not_awaited()
    ctx = AuthContext(user_id=uuid4(), organization_id=organization.id, role="member")
    assert all(policy.mode == "all" for policy in await service.policies(ctx, "skill_gallery"))
    read_org.return_value = None
    with pytest.raises(NotFoundError):
        await service.policies(ctx, "mcp_gallery")
