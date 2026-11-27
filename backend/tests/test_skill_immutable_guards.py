"""Missing immutable inputs and malformed imports cannot publish partial skill state."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.skill_merge import SkillMerge
from app.db.models.skill_version import SkillFork, SkillVersionSource
from app.services.skill_catch_up import SkillCatchUpService
from app.services.skill_package import SkillPackageService, read_package_files
from app.services.skill_versions import SkillVersionService
from app.services.skills import SkillService
from tests.test_skill_package import BODY
from tests.test_skills import _ctx, _skill

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_fork_without_immutable_base_cannot_inherit_metadata() -> None:
    ctx = _ctx()
    fork = SkillFork(
        id=uuid4(),
        organization_id=ctx.organization_id,
        skill_id=uuid4(),
        base_version_id=uuid4(),
        latest_version_id=None,
    )
    with (
        patch(
            "app.services.skill_versions.skill_version_repo.get_version",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.skill_versions.skill_version_repo.latest_number", AsyncMock()
        ) as number,
        pytest.raises(NotFoundError, match="Skill version not found"),
    ):
        await SkillVersionService(AsyncMock()).record_fork(
            ctx,
            fork,
            description="description",
            content="body",
            resources={},
            source=SkillVersionSource.CREATED,
        )
    number.assert_not_awaited()


@pytest.mark.parametrize("foreign", [False, True])
async def test_merge_requires_all_versions_from_its_own_skill(foreign: bool) -> None:
    ids = [uuid4() for _ in range(3)]
    merge = SkillMerge(
        organization_id=uuid4(),
        skill_id=uuid4(),
        base_version_id=ids[0],
        main_version_id=ids[1],
        fork_version_id=ids[2],
        unresolved=0,
        description={"result": "merged"},
        parts=[],
        files=[],
    )
    versions = {} if not foreign else {key: MagicMock(skill_id=uuid4()) for key in ids}
    with (
        patch(
            "app.services.skill_catch_up.skill_version_repo.get_files", AsyncMock(return_value=[])
        ),
        patch(
            "app.services.skill_catch_up.skill_version_repo.get_versions",
            AsyncMock(return_value=versions),
        ),
        pytest.raises(BadRequestError, match="no longer has its skill versions"),
    ):
        await SkillCatchUpService(AsyncMock()).candidate_of(merge)


@pytest.mark.parametrize("problem", ["count", "bytes", "duplicate"])
async def test_resource_upload_limits_are_checked_before_any_mutation(
    problem: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _ctx()
    skill = _skill(ctx=ctx)
    files = [("a", b"a"), ("b", b"b")]
    if problem == "count":
        monkeypatch.setattr("app.services.skills.MAX_SKILL_PACKAGE_FILES", 1)
    elif problem == "bytes":
        monkeypatch.setattr("app.services.skills.MAX_SKILL_PACKAGE_BYTES", 1)
    else:
        files = [("a", b"first"), ("a", b"second")]
    with (
        patch("app.services.skills.skill_repo.get", AsyncMock(return_value=skill)),
        patch("app.services.skills.skill_repo.get_resource_by_name", AsyncMock()) as lookup,
        pytest.raises(BadRequestError),
    ):
        await SkillService(AsyncMock()).put_resources(ctx, skill.id, files)
    lookup.assert_not_awaited()


@pytest.mark.parametrize("complete", [False, True])
async def test_body_only_import_requires_a_complete_first_version(complete: bool) -> None:
    ctx = _ctx()
    package = read_package_files([("SKILL.md", BODY)])
    skill = _skill(ctx=ctx)
    skill.latest_version_id = uuid4() if complete else None
    with (
        patch.object(SkillService, "create", AsyncMock(return_value=skill)) as create,
        patch.object(SkillService, "put_resources", AsyncMock()) as resources,
    ):
        service = SkillPackageService(AsyncMock())
        if complete:
            result = await service.apply(
                ctx, [("SKILL.md", BODY)], archive=False, expected_fingerprint=package.fingerprint
            )
            assert result.version_id == skill.latest_version_id
        else:
            with pytest.raises(RuntimeError, match="complete first version"):
                await service.apply(
                    ctx,
                    [("SKILL.md", BODY)],
                    archive=False,
                    expected_fingerprint=package.fingerprint,
                )
    assert create.await_args is not None
    assert create.await_args.kwargs["source"] == SkillVersionSource.CREATED
    resources.assert_not_awaited()


async def test_text_only_main_replacement_preserves_existing_assets() -> None:
    ctx = _ctx()
    asset = MagicMock(name="assets/template.xlsx", content="AP8=", encoding="base64")
    skill = _skill(ctx=ctx, resources=[asset])
    service = SkillService(AsyncMock())
    version = MagicMock(number=2)
    with (
        patch("app.services.skills.skill_repo.update", AsyncMock()) as update,
        patch("app.services.skills.skill_repo.delete_resource", AsyncMock()) as delete,
        patch("app.services.skills.skill_repo.create_resource", AsyncMock()) as create,
        patch.object(type(service.versions), "record_main", AsyncMock(return_value=version)),
        patch("app.services.eval_suite.EvalSuiteService.dependency_changed", AsyncMock()),
        patch("app.services.skills.record_audit", AsyncMock()),
    ):
        assert (
            await service._replace_main(
                ctx,
                skill,
                description="new description",
                content="new body",
                files=None,
                source=SkillVersionSource.CREATED,
                action="skill.updated",
            )
            is version
        )
    delete.assert_not_awaited()
    create.assert_not_awaited()
    assert skill.resources == [asset]
    assert update.await_args is not None
    assert update.await_args.kwargs["update_data"] == {
        "description": "new description",
        "content": "new body",
    }
