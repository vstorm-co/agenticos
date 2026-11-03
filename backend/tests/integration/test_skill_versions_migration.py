"""`0250_skill_versions`: what each skill said becomes v1, and pending changes follow it.

The schema half is cycled with the whole chain by `test_migrations.py`. What only a
seeded database shows is the data: the backfill's versions and the proposals it
re-points, and the downgrade taking the binding back out of the stored specs.
"""

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.models.skill import Skill, SkillResource
from app.db.models.skill_proposal import SkillProposal
from app.db.models.skill_usage import RunSkillUse
from app.db.models.skill_version import SkillFile, SkillVersion
from tests.integration.test_authoring import _owner, _published
from tests.integration.test_skill_usage import _agent, _org, _used, _version
from tests.integration.test_skill_usage import _run as _agent_run
from tests.integration.test_skill_usage import _skill as _usage_skill

pytestmark = pytest.mark.anyio


def _migration() -> ModuleType:
    path = Path(__file__).parents[2] / "alembic/versions/0250_skill_versions.py"
    spec = importlib.util.spec_from_file_location("skill_versions_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _run(session: Session, step: str, *args: str) -> None:
    with Operations.context(MigrationContext.configure(session.connection())):
        getattr(_migration(), step)(*args)


async def test_each_skill_becomes_its_own_v1_and_pending_changes_follow_it(db: AsyncSession):
    ctx = await _owner(db)
    skill = Skill(
        organization_id=ctx.organization_id,
        name="refunds",
        description="How refunds work.",
        content="Ask for the receipt.",
        version=7,
        library_fingerprint="f" * 64,
    )
    db.add(skill)
    await db.flush()
    db.add_all(
        [
            SkillResource(skill_id=skill.id, name="a.md", description="A", content="same"),
            SkillResource(skill_id=skill.id, name="b.md", description=None, content="same"),
        ]
    )
    current, stale, decided = (
        SkillProposal(
            organization_id=ctx.organization_id, skill_id=skill.id, name="refunds", base_version=7
        ),
        SkillProposal(
            organization_id=ctx.organization_id, skill_id=skill.id, name="refunds", base_version=5
        ),
        SkillProposal(
            organization_id=ctx.organization_id,
            skill_id=skill.id,
            name="refunds",
            base_version=7,
            status="applied",
        ),
    )
    db.add_all([current, stale, decided])
    await db.flush()

    await db.run_sync(_run, "_backfill")

    [v1] = (await db.execute(select(SkillVersion))).scalars().all()
    assert (v1.skill_id, v1.fork_id, v1.number, v1.source) == (skill.id, None, 1, "backfill")
    assert (v1.description, v1.content) == ("How refunds work.", "Ask for the receipt.")
    assert v1.library_fingerprint == "f" * 64
    assert v1.resources["a.md"]["description"] == "A"
    assert v1.resources["a.md"]["sha256"] == v1.resources["b.md"]["sha256"]
    assert v1.resources["b.md"]["size_bytes"] == 4
    assert len((await db.execute(select(SkillFile))).scalars().all()) == 1

    await db.refresh(skill)
    assert (skill.version, skill.latest_version_id) == (1, v1.id)
    for proposal in (current, stale, decided):
        await db.refresh(proposal)
    assert (current.base_version, current.base_version_id) == (1, v1.id)
    assert (stale.base_version, stale.base_version_id) == (5, None)
    assert (decided.base_version, decided.base_version_id) == (7, None)


async def test_the_downgrade_takes_the_binding_out_of_every_stored_spec(db: AsyncSession):
    """Its own and an inline specialist's, so the older code can read the spec at all."""
    ctx = await _owner(db)
    skill_id = str(uuid.uuid4())
    binding = [{"skill_id": skill_id, "version": 3}]
    spec = {
        "name": "Clerk",
        "skill_ids": [skill_id],
        "skill_bindings": binding,
        "capabilities": [
            {
                "id": "subagents",
                "config": {
                    "inline": [
                        {"name": "returns", "skill_ids": [skill_id], "skill_bindings": binding}
                    ]
                },
            }
        ],
    }
    agent = await _published(db, ctx, name="Clerk", spec=spec)
    untouched = await _published(db, ctx, name="Plain", spec={"name": "Plain"})

    await db.run_sync(_run, "_strip_bindings", "agents", "draft_spec")
    await db.run_sync(_run, "_strip_bindings", "agent_versions", "spec")

    await db.refresh(agent)
    assert "skill_bindings" not in agent.draft_spec
    assert "skill_bindings" not in agent.draft_spec["capabilities"][0]["config"]["inline"][0]
    assert agent.draft_spec["skill_ids"] == [skill_id]
    await db.refresh(untouched)
    assert untouched.draft_spec == {"name": "Plain"}


async def test_a_downgrade_forgets_the_version_each_use_was_served(db: AsyncSession):
    """The uses outlive the versions, so none may keep naming one that is gone."""
    org, user = await _org(db)
    skill = await _usage_skill(db, org)
    version = await _version(db, skill, 1)
    run = await _agent_run(db, org, await _agent(db, org, user, "Desk"))
    await _used(db, run, skill, version=version)

    await db.run_sync(_run, "_forget_served_versions")

    stored = await db.execute(select(RunSkillUse.skill_version_id))
    assert stored.scalars().all() == [None]


async def test_a_skill_whose_organization_is_gone_gets_no_version_and_stops_nothing(
    db: AsyncSession,
):
    """Only a row written past its keys can be such a skill; the upgrade goes on without it."""
    ctx = await _owner(db)
    orphan = uuid.uuid4()
    await db.execute(text("SET LOCAL session_replication_role = replica"))
    await db.execute(
        text(
            "INSERT INTO skills (id, organization_id, name, description, content, version, "
            "visibility) VALUES (:id, :org, 'orphan', 'd', 'c', 1, 'org')"
        ),
        {"id": orphan, "org": uuid.uuid4()},
    )
    await db.execute(
        text(
            "INSERT INTO skill_resources (id, skill_id, name, content) "
            "VALUES (:id, :skill, 'a.md', 'text')"
        ),
        {"id": uuid.uuid4(), "skill": orphan},
    )
    await db.execute(text("SET LOCAL session_replication_role = DEFAULT"))
    kept = Skill(organization_id=ctx.organization_id, name="refunds", description="d", content="c")
    db.add(kept)
    await db.flush()

    await db.run_sync(_run, "_backfill")

    versions = (await db.execute(select(SkillVersion.skill_id))).scalars().all()
    assert versions == [kept.id]
    assert (await db.execute(select(SkillFile.skill_id))).scalars().all() == []
