"""Exact exported skill pins resolve their line and owner, never newest by accident."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.services.organization_secret import OrganizationSecretService
from app.services.skill_versions import SkillVersionService

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("mode", ["current", "number", "fork-edited", "fork-base"])
async def test_snapshot_uses_an_authorized_exact_version(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    skill_id, current, pinned, base, fork_id = [uuid4() for _ in range(5)]
    service = SkillVersionService(mock_db_session)
    skill = SimpleNamespace(id=skill_id, latest_version_id=current)
    authorize = AsyncMock(return_value=skill)
    monkeypatch.setattr(service, "skill_for", authorize)
    read = AsyncMock(return_value=SimpleNamespace(id=pinned))
    monkeypatch.setattr(service, "_version", read)
    monkeypatch.setattr(
        service,
        "_fork",
        AsyncMock(
            return_value=SimpleNamespace(
                latest_version_id=pinned if mode == "fork-edited" else None, base_version_id=base
            )
        ),
    )
    numbered = AsyncMock(return_value={3: SimpleNamespace(id=pinned)})
    monkeypatch.setattr("app.services.skill_versions.skill_version_repo.get_by_numbers", numbered)
    await service.export_snapshot(
        ctx,
        skill_id,
        number=3 if mode == "number" else None,
        fork_id=fork_id if mode.startswith("fork") else None,
    )
    authorize.assert_awaited_once_with(ctx, skill_id, Perm.SKILLS_VIEW, include_resources=False)
    if mode == "number":
        numbered.assert_awaited_once_with(
            mock_db_session,
            organization_id=ctx.organization_id,
            skill_id=skill_id,
            fork_id=None,
            numbers=[3],
        )
        read.assert_not_awaited()
    else:
        expected = current if mode == "current" else pinned if mode == "fork-edited" else base
        read.assert_awaited_once_with(ctx, skill, expected)


@pytest.mark.parametrize("mode", ["both", "no-current", "number-missing"])
async def test_missing_and_contradictory_version_pins_are_refused(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    service = SkillVersionService(mock_db_session)
    skill_id = uuid4()
    monkeypatch.setattr(
        service,
        "skill_for",
        AsyncMock(return_value=SimpleNamespace(id=skill_id, latest_version_id=None)),
    )
    monkeypatch.setattr(
        "app.services.skill_versions.skill_version_repo.get_by_numbers", AsyncMock(return_value={})
    )
    with pytest.raises((BadRequestError, NotFoundError)):
        await service.export_snapshot(
            AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"),
            skill_id,
            number=3 if mode != "no-current" else None,
            fork_id=uuid4() if mode == "both" else None,
        )


@pytest.mark.security
async def test_fork_identity_and_secret_metadata_delegate_to_existing_access_checks(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    versions = SkillVersionService(mock_db_session)
    skill, fork = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
    monkeypatch.setattr(versions, "skill_for", AsyncMock(return_value=skill))
    get = AsyncMock(return_value=fork)
    monkeypatch.setattr(versions, "_fork", get)
    assert await versions.get_fork(ctx, skill.id, fork.id) is fork
    get.assert_awaited_once_with(ctx, skill, fork.id)
    version = SimpleNamespace(id=uuid4())
    read_version = AsyncMock(return_value=version)
    monkeypatch.setattr(versions, "_version", read_version)
    assert await versions.export_version_by_id(ctx, skill.id, version.id) is version
    read_version.assert_awaited_once_with(ctx, skill, version.id)
    secrets = OrganizationSecretService(mock_db_session)
    secret = SimpleNamespace(id=uuid4())
    checked = AsyncMock(return_value=secret)
    monkeypatch.setattr(secrets, "_get", checked)
    assert await secrets.get_metadata(ctx, secret.id) is secret
    checked.assert_awaited_once_with(ctx, secret.id)
