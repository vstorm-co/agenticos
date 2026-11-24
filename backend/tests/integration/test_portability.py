"""Bundle imports exercise real tenant boundaries, versions and atomic receipts."""

from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, SkillBindingSpec
from app.core.exceptions import NotFoundError
from app.core.permissions import Perm
from app.schemas.resource_bundle import BundleImportChoice, BundleImportCreate
from app.schemas.skill import SkillUpdate
from app.schemas.skill_version import SkillForkCreate, SkillVersionCreate
from app.services.agent_registry import AgentRegistryService
from app.services.portability import PortabilityService
from app.services.skill_versions import SkillVersionService
from app.services.skills import SkillService
from tests.integration.test_authoring import _owner

pytestmark = pytest.mark.anyio


async def test_cross_organization_copy_keeps_exact_main_and_fork_files_and_replays(
    db: AsyncSession,
) -> None:
    source = await _owner(db)
    target = await _owner(db)
    skills = SkillService(db)
    skill = await skills.create(
        source, name="research-policy", description="Original policy", content="  Source main v1\n"
    )
    assert skill.latest_version_id is not None
    await skills.add_resource(
        source,
        skill.id,
        name="references/checklist.md",
        description="  Reference policy\n",
        content="  Original checklist\n",
    )
    pin = await skills.versions.export_snapshot(source, skill.id)
    fork = await skills.versions.create_fork(
        source, skill.id, SkillForkCreate(name="regional", from_version_id=pin.id)
    )
    await skills.versions.edit(
        source,
        skill.id,
        SkillVersionCreate(
            fork_id=fork.id,
            base_version_id=pin.id,
            description="Regional policy",
            content="  Fork-specific body\n",
        ),
    )
    await skills.update(source, skill.id, SkillUpdate(content="Later floating main"))
    agent = await AgentRegistryService(db).create(
        source,
        AgentSpec(
            name="Research assistant",
            skill_ids=[skill.id],
            skill_bindings=[SkillBindingSpec(skill_id=skill.id, version=pin.number)],
        ),
        choose_model=False,
    )
    preview = await PortabilityService(db).export_agent(source, agent.id)
    choices = {item.key: BundleImportChoice(action="create") for item in preview.bundle.resources}
    request = BundleImportCreate(operation_id=uuid4(), bundle=preview.bundle, choices=choices)
    service = PortabilityService(db)
    receipt = await service.import_bundle(target, request)
    assert await service.import_bundle(target, request) == receipt
    imported = await AgentRegistryService(db).get(target, receipt.roots[preview.bundle.roots[0]])
    spec = AgentSpec.model_validate(imported.draft_spec)
    assert spec.skill_ids[0] != skill.id
    copied_pin = await SkillVersionService(db).export_snapshot(
        target, spec.skill_ids[0], number=spec.skill_bindings[0].version
    )
    assert copied_pin.content == pin.content
    assert (
        copied_pin.resources["references/checklist.md"]["description"]
        == pin.resources["references/checklist.md"]["description"]
    )
    assert await SkillVersionService(db).files_of(copied_pin) == {
        "references/checklist.md": "  Original checklist\n"
    }
    current = await skills.get(target, spec.skill_ids[0])
    assert current.content == "Later floating main"
    assert imported.visibility == "private"
    assert imported.current_version_id is None
    with pytest.raises(NotFoundError):
        await skills.get(target, skill.id)


async def test_pinned_fork_import_preserves_its_effective_snapshot(db: AsyncSession) -> None:
    source = await _owner(db)
    target = await _owner(db)
    skills = SkillService(db)
    skill = await skills.create(source, name="policy", description="Policy", content="Main body")
    assert skill.latest_version_id is not None
    await skills.put_resources(source, skill.id, [("references/raw.txt", b"raw")])
    fork = await skills.versions.create_fork(
        source, skill.id, SkillForkCreate(name="regional", from_version_id=skill.latest_version_id)
    )
    await skills.versions.edit(
        source,
        skill.id,
        SkillVersionCreate(
            fork_id=fork.id,
            base_version_id=skill.latest_version_id,
            description="Regional policy",
            content="  Regional body\n",
        ),
    )
    original_fork = await skills.versions.export_snapshot(source, skill.id, fork_id=fork.id)
    agent = await AgentRegistryService(db).create(
        source,
        AgentSpec(
            name="Regional agent",
            skill_ids=[skill.id],
            skill_bindings=[SkillBindingSpec(skill_id=skill.id, fork_id=fork.id)],
        ),
        choose_model=False,
    )
    service = PortabilityService(db)
    preview = await service.export_agent(source, agent.id)
    request = BundleImportCreate(
        operation_id=uuid4(),
        bundle=preview.bundle,
        choices={
            item.key: BundleImportChoice(action="create") for item in preview.bundle.resources
        },
    )
    receipt = await service.import_bundle(target, request)
    imported = await AgentRegistryService(db).get(target, receipt.roots[preview.bundle.roots[0]])
    spec = AgentSpec.model_validate(imported.draft_spec)
    version = await skills.versions.export_snapshot(
        target, spec.skill_ids[0], fork_id=spec.skill_bindings[0].fork_id
    )
    assert version.content == original_fork.content
    assert await skills.versions.files_of(version) == {"references/raw.txt": "raw"}
    assert (await skills.get(target, spec.skill_ids[0])).content == "Main body"


async def test_export_identity_lookup_does_not_load_all_main_file_bodies(db: AsyncSession) -> None:
    owner = await _owner(db)
    other = await _owner(db)
    service = SkillService(db)
    skill = await service.create(owner, name="policy", description="Policy", content="Body")
    await service.put_resources(owner, skill.id, [("reference.md", b"Private body")])
    db.expire(skill, ["resources"])
    versions = SkillVersionService(db)
    metadata = await versions.skill_for(owner, skill.id, Perm.SKILLS_VIEW, include_resources=False)
    assert "resources" in inspect(metadata).unloaded
    with pytest.raises(InvalidRequestError, match="lazy='raise'"):
        _ = metadata.resources
    with pytest.raises(NotFoundError):
        await versions.export_snapshot(other, skill.id)
