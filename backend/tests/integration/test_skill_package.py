"""Actual PostgreSQL bytes, immutable versions, rollback and tenant boundaries."""

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.capabilities.sandbox._capped import CappedStateBackend
from app.agents.spec import SkillBindingSpec
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import OrgRoleName
from app.core.skill_files import decode_skill_file
from app.db.models.skill import Skill
from app.db.models.skill_version import SkillFile, SkillVersion
from app.repositories import skill_version_repo
from app.schemas.skill import SkillUpdate
from app.schemas.skill_version import SkillVersionRestore
from app.services.skill_package import SkillPackageService
from app.services.skill_versions import SkillVersionService
from app.services.skill_workspace import materialise
from app.services.skills import SkillService
from tests.integration.test_authoring import _member, _owner
from tests.workspaces import document_workspace

pytestmark = [pytest.mark.anyio, pytest.mark.security]
BODY = b"---\nname: proposal-builder\ndescription: Generate proposals.\nlicense: MIT\nallowed-tools: [execute]\n---\nUse assets/template.xlsx.\n"
RAW = b"PK\x03\x04binary\x00\xfftemplate"
FILES = [
    ("proposal-builder/SKILL.md", BODY),
    ("proposal-builder/assets/template.xlsx", RAW),
    ("proposal-builder/scripts/build.py", b"raise RuntimeError('must not execute')\n"),
]


async def test_package_bytes_metadata_pins_and_restore_share_real_versions(
    engine: AsyncEngine,
) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        ctx = await _owner(db)
        packages = SkillPackageService(db)
        preview = await packages.preview(ctx, FILES, archive=False)
        result = await packages.apply(
            ctx, FILES, archive=False, expected_fingerprint=preview.fingerprint
        )
        skills = SkillService(db)
        stored = await skills.get(ctx, result.skill_id)
        assert stored.version == 1
        assert stored.manifest_metadata == {"license": "MIT", "allowed-tools": ["execute"]}
        version = await skill_version_repo.get_version(
            db, result.version_id, organization_id=ctx.organization_id, skill_id=stored.id
        )
        assert version is not None
        entry = version.resources["assets/template.xlsx"]
        assert entry["sha256"] == hashlib.sha256(RAW).hexdigest()
        assert entry["size_bytes"] == len(RAW)
        assert entry["encoding"] == "base64"
        versions = SkillVersionService(db)
        original = await versions.read_resource(ctx, stored.id, version.id, "assets/template.xlsx")
        assert decode_skill_file(original.content, original.encoding) == RAW
        await skills.update(
            ctx, stored.id, SkillUpdate(manifest_metadata={"license": "Apache-2.0"})
        )
        await skills.put_resources(ctx, stored.id, [("assets/template.xlsx", b"new\0binary")])
        latest = await skills.get(ctx, stored.id)
        assert latest.version == 3
        [pinned] = await skills.resolve_for_agent(
            ctx, [stored.id], bindings=[SkillBindingSpec(skill_id=stored.id, version=1)]
        )
        assert pinned.manifest_metadata == {"license": "MIT", "allowed-tools": ["execute"]}
        workspace = document_workspace(CappedStateBackend(max_bytes=1024 * 1024))
        await materialise(workspace, [pinned])
        assert (
            await workspace.read_bytes("/workspace/skills/proposal-builder/assets/template.xlsx")
            == RAW
        )
        assert latest.latest_version_id is not None
        restored = await versions.restore(
            ctx,
            stored.id,
            version.id,
            SkillVersionRestore(base_version_id=latest.latest_version_id),
        )
        assert restored.number == 4
        assert restored.manifest_metadata == version.manifest_metadata
        restored_file = await versions.read_resource(
            ctx, stored.id, restored.id, "assets/template.xlsx"
        )
        assert decode_skill_file(restored_file.content, restored_file.encoding) == RAW
        assert await db.scalar(select(func.count()).select_from(SkillFile)) == 3
        await db.commit()


async def test_stale_preview_and_rollback_leave_no_partial_skill_files(engine: AsyncEngine) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        ctx = await _owner(db)
        packages = SkillPackageService(db)
        preview = await packages.preview(ctx, FILES, archive=False)
        with pytest.raises(BadRequestError, match="changed"):
            await packages.apply(ctx, FILES, archive=False, expected_fingerprint="0" * 64)
        assert await db.scalar(select(func.count()).select_from(Skill)) == 0
        with pytest.raises(RuntimeError, match="roll back"):
            async with db.begin_nested():
                await packages.apply(
                    ctx, FILES, archive=False, expected_fingerprint=preview.fingerprint
                )
                raise RuntimeError("roll back the whole package")
        assert await db.scalar(select(func.count()).select_from(Skill)) == 0
        assert await db.scalar(select(func.count()).select_from(SkillFile)) == 0
        assert await db.scalar(select(func.count()).select_from(SkillVersion)) == 0


async def test_imported_binary_and_versions_remain_private_and_tenant_scoped(
    engine: AsyncEngine,
) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        owner = await _owner(db)
        packages = SkillPackageService(db)
        preview = await packages.preview(owner, FILES, archive=False)
        result = await packages.apply(
            owner, FILES, archive=False, expected_fingerprint=preview.fingerprint
        )
        other = await _owner(db)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        for ctx in (other, member):
            with pytest.raises(NotFoundError):
                await SkillService(db).get(ctx, result.skill_id)
            with pytest.raises(NotFoundError):
                await SkillVersionService(db).read_resource(
                    ctx, result.skill_id, result.version_id, "assets/template.xlsx"
                )
        with pytest.raises(NotFoundError):
            await SkillVersionService(db).read_resource(
                owner, result.skill_id, uuid4(), "assets/template.xlsx"
            )


async def test_portable_cross_org_copy_preserves_binary_and_frontmatter(db: AsyncSession) -> None:
    from app.agents.spec import AgentSpec
    from app.schemas.resource_bundle import BundleImportChoice, BundleImportCreate
    from app.services.agent_registry import AgentRegistryService
    from app.services.portability import PortabilityService

    owner, target = await _owner(db), await _owner(db)
    packages = SkillPackageService(db)
    preview = await packages.preview(owner, FILES, archive=False)
    imported = await packages.apply(
        owner, FILES, archive=False, expected_fingerprint=preview.fingerprint
    )
    registry = AgentRegistryService(db)
    agent = await registry.create(
        owner,
        AgentSpec(
            name="Binary template agent",
            skill_ids=[imported.skill_id],
            skill_bindings=[SkillBindingSpec(skill_id=imported.skill_id, version=1)],
        ),
        choose_model=False,
    )
    portability = PortabilityService(db)
    exported = await portability.export_agent(owner, agent.id)
    receipt = await portability.import_bundle(
        target,
        BundleImportCreate(
            operation_id=uuid4(),
            bundle=exported.bundle,
            choices={
                item.key: BundleImportChoice(action="create") for item in exported.bundle.resources
            },
        ),
    )
    copied_agent = await registry.get(target, receipt.roots[exported.bundle.roots[0]])
    copied_spec = AgentSpec.model_validate(copied_agent.draft_spec)
    [copied] = await SkillService(db).resolve_for_agent(
        target, copied_spec.skill_ids, bindings=copied_spec.skill_bindings
    )
    assert copied.id != imported.skill_id
    assert copied.manifest_metadata == preview.manifest_metadata
    asset = next(item for item in copied.resources if item.name == "assets/template.xlsx")
    assert decode_skill_file(asset.content, asset.encoding) == RAW
    assert copied.visibility == "private"


async def test_fork_edits_keep_binary_assets_and_versioned_metadata(db: AsyncSession) -> None:
    from app.schemas.skill_version import SkillForkCreate, SkillVersionCreate

    owner = await _owner(db)
    packages = SkillPackageService(db)
    preview = await packages.preview(owner, FILES, archive=False)
    result = await packages.apply(
        owner, FILES, archive=False, expected_fingerprint=preview.fingerprint
    )
    service = SkillVersionService(db)
    fork = await service.create_fork(
        owner, result.skill_id, SkillForkCreate(name="regional", from_version_id=result.version_id)
    )
    edited = await service.edit(
        owner,
        result.skill_id,
        SkillVersionCreate(
            fork_id=fork.id,
            base_version_id=result.version_id,
            description=preview.description,
            content="Use regional template.",
            manifest_metadata={"license": "Apache-2.0"},
        ),
    )
    snapshot = await service.export_snapshot(owner, result.skill_id, fork_id=fork.id)
    assert snapshot.manifest_metadata == {"license": "Apache-2.0"}
    asset = await service.read_resource(owner, result.skill_id, edited.id, "assets/template.xlsx")
    assert decode_skill_file(asset.content, asset.encoding) == RAW
    main = await service.export_snapshot(owner, result.skill_id)
    assert main.manifest_metadata == preview.manifest_metadata


async def test_queued_check_reload_retains_binary_encoding_and_frontmatter(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.repositories import skill_check_repo
    from app.schemas.skill_check import SkillCheckStart
    from app.services.skill_check import SkillCheckService, _candidate_of
    from tests.integration.test_skill_checks import NEW, FakeEvals, _lab

    lab = await _lab(db)
    skills = SkillService(db)
    await skills.update(lab.ctx, lab.skill.id, SkillUpdate(manifest_metadata={"license": "MIT"}))
    await skills.put_resources(lab.ctx, lab.skill.id, [("assets/template.xlsx", RAW)])
    FakeEvals().install(monkeypatch)
    check = await SkillCheckService(db).start(lab.ctx, lab.skill.id, SkillCheckStart(candidate=NEW))
    check_id, skill_id = check.id, lab.skill.id
    db.expire_all()
    row = await skill_check_repo.get(db, check_id, organization_id=lab.ctx.organization_id)
    assert row is not None
    resumed = _candidate_of(row)
    assert resumed.manifest_metadata == {"license": "MIT"}
    assert resumed.resources is not None
    asset = next(item for item in resumed.resources if item.name == "assets/template.xlsx")
    assert decode_skill_file(asset.content, asset.encoding) == RAW
    shown = await SkillCheckService(db).read(lab.ctx, skill_id, check_id)
    assert shown.candidate.manifest_metadata == {"license": "MIT"}
