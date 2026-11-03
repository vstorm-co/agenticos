"""Skill versions and forks, against a real database.

Every change an agent would notice is one new, never-updated version; a fork is a
line of its own that starts from main; and what is in the database is what the
skill's history and its agents read - checked here rather than through mocks,
because numbering, the tenant keys and the cascades are the database's to enforce.
"""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AlreadyExistsError,
    BadRequestError,
    ConcurrentChangeError,
    ConflictError,
    InUseError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.agent_run import AgentRun
from app.db.models.organization import OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.skill import Skill
from app.db.models.skill_proposal import SkillProposal
from app.db.models.skill_version import SkillFile, SkillFork, SkillVersion, SkillVersionSource
from app.repositories import skill_repo, skill_version_repo
from app.schemas.resource_usage import ProposalDecision
from app.schemas.skill import SkillUpdate
from app.schemas.skill_version import (
    SkillForkCreate,
    SkillForkUpdate,
    SkillVersionCreate,
    SkillVersionRestore,
)
from app.services import skill_library
from app.services.agent_registry import AgentRegistryService
from app.services.skill_proposal import SkillProposalService
from app.services.skill_versions import SkillVersionService
from app.services.skills import SkillService
from tests.integration.test_authoring import _member, _owner, _published

pytestmark = pytest.mark.anyio


async def _skill(db: AsyncSession, ctx: AuthContext, name: str = "refunds") -> Skill:
    return await SkillService(db).create(
        ctx,
        name=name,
        description="How refunds work.",
        content="Ask for the order id.",
        visibility=Visibility.ORG,
    )


async def _versions(db: AsyncSession, skill: Skill, fork: SkillFork | None = None) -> list[Any]:
    line = SkillVersion.fork_id.is_(None) if fork is None else SkillVersion.fork_id == fork.id
    result = await db.execute(
        select(SkillVersion)
        .where(SkillVersion.skill_id == skill.id, line)
        .order_by(SkillVersion.number)
    )
    return list(result.scalars().all())


def _edit(
    skill: Skill, base: uuid.UUID | None, content: str, fork: SkillFork | None = None
) -> SkillVersionCreate:
    assert base is not None
    return SkillVersionCreate(
        fork_id=None if fork is None else fork.id,
        base_version_id=base,
        description=skill.description,
        content=content,
    )


class TestEveryChangeIsAVersion:
    async def test_a_new_skill_is_its_own_first_version(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)

        [first] = await _versions(db, skill)
        assert (first.number, first.source, first.content) == (
            1,
            "created",
            "Ask for the order id.",
        )
        assert skill.latest_version_id == first.id and skill.version == 1
        assert first.created_by_user_id == ctx.user_id

    async def test_an_edit_is_the_next_version_and_the_row_mirrors_it(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)

        await SkillService(db).update(ctx, skill.id, SkillUpdate(content="Ask for the receipt."))

        first, second = await _versions(db, skill)
        assert (second.number, second.source, second.content) == (2, "edit", "Ask for the receipt.")
        assert first.content == "Ask for the order id."
        assert (skill.version, skill.latest_version_id) == (2, second.id)

    async def test_a_new_category_alone_is_no_version(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)

        await SkillService(db).update(ctx, skill.id, SkillUpdate(category="support"))

        assert len(await _versions(db, skill)) == 1

    async def test_a_file_change_is_a_version_and_a_body_is_stored_once(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        service = SkillService(db)

        await service.put_resources(ctx, skill.id, [("a.md", b"same"), ("b.md", b"same")])

        _, second = await _versions(db, skill)
        assert second.source == "resources"
        assert set(second.resources) == {"a.md", "b.md"}
        assert second.resources["a.md"]["sha256"] == second.resources["b.md"]["sha256"]
        stored = await db.scalar(
            select(func.count()).select_from(SkillFile).where(SkillFile.skill_id == skill.id)
        )
        assert stored == 1

    async def test_a_library_install_and_its_refresh_are_library_versions(self, db, monkeypatch):
        ctx = await _owner(db)
        old = skill_library.LibrarySkill(
            key="refunds",
            name="refunds",
            description="How refunds work.",
            category=None,
            content="v1 text",
            resources=(skill_library.LibraryResource(name="r.md", content="one"),),
        )
        new = skill_library.LibrarySkill(
            key="refunds",
            name="refunds",
            description="How refunds work.",
            category=None,
            content="v2 text",
            resources=(),
        )
        monkeypatch.setattr(skill_library, "get", lambda _key: old)
        service = SkillService(db)
        await service.install_from_library(ctx, "refunds")
        monkeypatch.setattr(skill_library, "get", lambda _key: new)
        await service.refresh_from_library(ctx, "refunds")

        skill = await db.scalar(select(Skill).where(Skill.organization_id == ctx.organization_id))
        assert skill is not None
        first, second = await _versions(db, skill)
        assert (first.source, set(first.resources)) == ("library", {"r.md"})
        assert first.library_fingerprint == old.fingerprint
        assert (second.source, second.content, second.resources) == ("library", "v2 text", {})
        assert second.library_fingerprint == new.fingerprint

    async def test_an_applied_change_records_where_it_came_from(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        proposal = SkillProposal(
            organization_id=ctx.organization_id,
            skill_id=skill.id,
            name=skill.name,
            description=skill.description,
            content="Ask for the receipt.",
            resources={"check.md": "Look twice."},
            base_version=1,
            base_version_id=skill.latest_version_id,
        )
        db.add(proposal)
        await db.flush()

        await SkillProposalService(db).apply(
            ctx, proposal.id, ProposalDecision(revision=1), checked=True
        )

        _, applied = await _versions(db, skill)
        assert (applied.source, applied.proposal_id) == ("workspace", proposal.id)
        assert (applied.content, set(applied.resources)) == ("Ask for the receipt.", {"check.md"})


class TestEditingAndRestoring:
    async def test_an_edit_on_an_old_version_is_refused(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        first = skill.latest_version_id
        versions = SkillVersionService(db)
        await versions.edit(ctx, skill.id, _edit(skill, first, "Second."))

        with pytest.raises(ConcurrentChangeError):
            await versions.edit(ctx, skill.id, _edit(skill, first, "Lost update."))

        assert [version.content for version in await _versions(db, skill)] == [
            "Ask for the order id.",
            "Second.",
        ]

    async def test_restore_brings_the_text_and_the_files_back_as_the_newest_version(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        service = SkillService(db)
        await service.put_resources(ctx, skill.id, [("a.md", b"first")])
        await db.refresh(skill)
        with_file = skill.latest_version_id
        await service.update(ctx, skill.id, SkillUpdate(content="Changed."))
        await service.put_resources(ctx, skill.id, [("a.md", b"second"), ("b.md", b"new")])
        await db.refresh(skill)
        assert with_file is not None

        restored = await SkillVersionService(db).restore(
            ctx,
            skill.id,
            with_file,
            SkillVersionRestore(base_version_id=skill.latest_version_id),
        )

        assert restored.source is SkillVersionSource.RESTORE
        assert restored.restored_from is not None and restored.restored_from.id == with_file
        assert restored.number == 5
        await db.refresh(skill, ["resources"])
        assert skill.content == "Ask for the order id."
        assert {(resource.name, resource.content) for resource in skill.resources} == {
            ("a.md", "first")
        }

    async def test_history_lists_a_line_newest_first_with_what_each_came_after(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        await SkillService(db).update(ctx, skill.id, SkillUpdate(content="Second."))

        listed = await SkillVersionService(db).list_versions(ctx, skill.id, fork_id=None)

        assert listed.total == 2
        newest, oldest = listed.items
        assert (newest.number, oldest.number) == (2, 1)
        assert newest.previous is not None and newest.previous.id == oldest.id
        assert oldest.previous is None
        assert newest.created_by is not None and newest.created_by.id == ctx.user_id

    async def test_somebody_who_left_keeps_their_versions_and_loses_their_name(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        builder = await _member(db, ctx, OrgRoleName.BUILDER)
        await SkillService(db).update(builder, skill.id, SkillUpdate(content="Second."))
        await db.execute(
            delete(OrganizationMember).where(
                OrganizationMember.organization_id == ctx.organization_id,
                OrganizationMember.user_id == builder.user_id,
            )
        )

        newest, oldest = (
            await SkillVersionService(db).list_versions(ctx, skill.id, fork_id=None)
        ).items

        assert newest.created_by is not None
        assert (newest.created_by.id, newest.created_by.name) == (builder.user_id, None)
        assert oldest.created_by is not None and oldest.created_by.name is not None

    async def test_a_version_keeps_its_files_after_main_changed_them(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        service = SkillService(db)
        await service.put_resources(ctx, skill.id, [("a.md", b"old")])
        await db.refresh(skill)
        old = skill.latest_version_id
        await service.put_resources(ctx, skill.id, [("a.md", b"new")])
        assert old is not None

        versions = SkillVersionService(db)
        read = await versions.read_version(ctx, skill.id, old)
        file = await versions.read_resource(ctx, skill.id, old, "a.md")

        assert [resource.name for resource in read.resources] == ["a.md"]
        newest = await versions.read_version(ctx, skill.id, skill.latest_version_id)
        assert read.resources[0].size_bytes == newest.resources[0].size_bytes
        assert read.resources[0].digest != newest.resources[0].digest
        assert file.content == "old"
        with pytest.raises(NotFoundError):
            await versions.read_resource(ctx, skill.id, old, "missing.md")


class TestTheEdges:
    async def test_a_skill_gone_before_its_version_is_recorded_is_not_found(self, db):
        ctx = await _owner(db)
        gone = Skill(id=uuid.uuid4(), organization_id=ctx.organization_id, name="gone")

        with pytest.raises(NotFoundError):
            await SkillVersionService(db).record_main(ctx, gone, source=SkillVersionSource.EDIT)

    async def test_restoring_a_version_without_files_takes_the_files_away(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        first = skill.latest_version_id
        await SkillService(db).put_resources(ctx, skill.id, [("a.md", b"one")])
        await db.refresh(skill)
        assert first is not None

        await SkillVersionService(db).restore(
            ctx, skill.id, first, SkillVersionRestore(base_version_id=skill.latest_version_id)
        )

        await db.refresh(skill, ["resources"])
        assert skill.resources == []

    async def test_an_unknown_fork_has_no_history(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)

        with pytest.raises(NotFoundError):
            await SkillVersionService(db).list_versions(ctx, skill.id, fork_id=uuid.uuid4())

    async def test_counting_the_forks_of_no_skills_asks_nothing(self, db):
        from app.repositories import skill_version_repo

        ctx = await _owner(db)
        assert (
            await skill_version_repo.count_active_forks(
                db, organization_id=ctx.organization_id, skill_ids=[]
            )
            == {}
        )
        assert (
            await skill_version_repo.forks_served_since(
                db, organization_id=ctx.organization_id, fork_ids=[], since=datetime.now(UTC)
            )
            == set()
        )


class TestForks:
    async def _fork(self, db: AsyncSession, ctx: AuthContext, skill: Skill, name: str = "returns"):
        assert skill.latest_version_id is not None
        return await SkillVersionService(db).create_fork(
            ctx, skill.id, SkillForkCreate(name=name, from_version_id=skill.latest_version_id)
        )

    async def test_behind_main_counts_changes_to_what_main_says_not_versions(self, db):
        """Restoring the newest text again is a version and no change; a main line back
        at what the fork started from is behind by none."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        versions = SkillVersionService(db)
        read = await self._fork(db, ctx, skill)
        started = read.base.id
        await SkillService(db).update(ctx, skill.id, SkillUpdate(content="One more rule."))
        changed = skill.latest_version_id
        assert changed is not None
        for _ in range(2):
            assert skill.latest_version_id is not None
            await versions.restore(
                ctx, skill.id, changed, SkillVersionRestore(base_version_id=skill.latest_version_id)
            )

        [after_restores] = (await versions.list_forks(ctx, skill.id)).items
        assert (skill.version, after_restores.behind_main) == (4, 1)

        assert skill.latest_version_id is not None
        await versions.restore(
            ctx, skill.id, started, SkillVersionRestore(base_version_id=skill.latest_version_id)
        )

        [back] = (await versions.list_forks(ctx, skill.id)).items
        assert (skill.version, back.behind_main) == (5, 0)

    async def test_a_fork_serves_its_base_until_it_has_a_version_of_its_own(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        versions = SkillVersionService(db)
        read = await self._fork(db, ctx, skill)
        assert (read.latest, read.changes, read.behind_main, read.base.number) == (None, 0, 0, 1)
        unchanged = await versions.list_versions(ctx, skill.id, fork_id=read.id)
        assert (unchanged.items, unchanged.total) == ([], 0)

        fork = await db.get(SkillFork, read.id)
        assert fork is not None
        assert versions.line_latest(skill, fork) == skill.latest_version_id

        edited = await versions.edit(
            ctx, skill.id, _edit(skill, skill.latest_version_id, "Returns only.", fork)
        )
        await SkillService(db).update(ctx, skill.id, SkillUpdate(content="Main moved."))

        assert (edited.number, edited.fork_id) == (1, fork.id)
        assert edited.previous is not None and edited.previous.id == read.base.id
        [after] = (await versions.list_forks(ctx, skill.id)).items
        assert (after.changes, after.behind_main) == (1, 1)
        assert after.latest is not None and after.latest.id == edited.id
        assert skill.content == "Main moved."

    async def test_saving_a_fork_unchanged_makes_no_version(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        versions = SkillVersionService(db)
        read = await self._fork(db, ctx, skill)
        fork = await db.get(SkillFork, read.id)

        same = await versions.edit(
            ctx, skill.id, _edit(skill, read.base.id, "Ask for the order id.", fork)
        )

        assert same.id == read.base.id
        assert await _versions(db, skill, fork) == []

    async def test_a_fork_of_a_fork_is_refused(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        versions = SkillVersionService(db)
        read = await self._fork(db, ctx, skill)
        fork = await db.get(SkillFork, read.id)
        own = await versions.edit(ctx, skill.id, _edit(skill, read.base.id, "Fork text.", fork))

        with pytest.raises(BadRequestError) as refused:
            await versions.create_fork(
                ctx, skill.id, SkillForkCreate(name="deeper", from_version_id=own.id)
            )

        assert refused.value.details["fields"][0]["field"] == "from_version_id"

    async def test_a_second_fork_of_the_same_name_is_refused(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        await self._fork(db, ctx, skill)
        other = await self._fork(db, ctx, skill, name="other")

        with pytest.raises(AlreadyExistsError):
            await self._fork(db, ctx, skill)
        with pytest.raises(AlreadyExistsError):
            await SkillVersionService(db).rename_fork(
                ctx, skill.id, other.id, SkillForkUpdate(name="returns")
            )

        renamed = await SkillVersionService(db).rename_fork(
            ctx, skill.id, other.id, SkillForkUpdate(name="refunds-eu")
        )
        same = await SkillVersionService(db).rename_fork(
            ctx, skill.id, other.id, SkillForkUpdate(name="refunds-eu")
        )
        assert renamed.name == same.name == "refunds-eu"

    async def test_an_archived_fork_takes_no_new_version(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        versions = SkillVersionService(db)
        read = await self._fork(db, ctx, skill)
        fork = await db.get(SkillFork, read.id)
        archived = await versions.archive_fork(ctx, skill.id, read.id)
        again = await versions.archive_fork(ctx, skill.id, read.id)

        assert archived.archived_at is not None and again.archived_at == archived.archived_at
        with pytest.raises(ConflictError):
            await versions.edit(ctx, skill.id, _edit(skill, read.base.id, "Too late.", fork))
        assert (await versions.list_forks(ctx, skill.id)).items == []
        assert [
            item.id for item in (await versions.list_forks(ctx, skill.id, archived=True)).items
        ] == [read.id]

    @pytest.mark.parametrize("change", ["rename", "edit", "archive"])
    async def test_a_fork_change_takes_the_skill_before_the_fork(
        self, db: AsyncSession, engine: AsyncEngine, change: str
    ):
        """Applying a proposal to a fork locks the skill, then the fork.

        Held here half-way, with the skill locked: a change that locked the fork
        first would hold it while waiting for the skill, and the apply's turn for
        the fork would deadlock.
        """
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        read = await self._fork(db, ctx, skill)
        await db.commit()
        changes = {
            "rename": lambda versions: versions.rename_fork(
                ctx, skill.id, read.id, SkillForkUpdate(name="eu")
            ),
            "edit": lambda versions: versions.edit(
                ctx,
                skill.id,
                SkillVersionCreate(
                    fork_id=read.id,
                    base_version_id=read.base.id,
                    description=skill.description,
                    content="Returns only.",
                ),
            ),
            "archive": lambda versions: versions.archive_fork(ctx, skill.id, read.id),
        }
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def change_fork() -> None:
            async with factory() as session:
                await changes[change](SkillVersionService(session))
                await session.commit()

        task: asyncio.Task[None] | None = None
        async with factory() as applying:
            try:
                await skill_repo.lock(applying, skill.id)
                task = asyncio.create_task(change_fork())
                await asyncio.sleep(0.4)
                assert not task.done()

                await skill_version_repo.get_fork(
                    applying,
                    read.id,
                    organization_id=ctx.organization_id,
                    skill_id=skill.id,
                    lock=True,
                )
                await applying.commit()
                await task
                task = None
            finally:
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    async def test_a_version_that_took_main_in_names_it_and_the_fork_keeps_its_start(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        versions = SkillVersionService(db)
        read = await self._fork(db, ctx, skill)
        await SkillService(db).update(ctx, skill.id, SkillUpdate(content="Main moved."))
        fork = await db.get(SkillFork, read.id)
        assert fork is not None and skill.latest_version_id is not None

        await versions.record_fork(
            ctx,
            fork,
            description=skill.description,
            content="Main moved, and returns only.",
            resources={},
            source=SkillVersionSource.CATCH_UP,
            merged_from_id=skill.latest_version_id,
        )
        fork.base_version_id = skill.latest_version_id
        await db.flush()

        [merged] = (await versions.list_versions(ctx, skill.id, fork_id=fork.id)).items
        [after] = (await versions.list_forks(ctx, skill.id)).items
        assert merged.merged_from is not None and merged.merged_from.number == 2
        assert merged.previous is not None and merged.previous.id == read.base.id
        assert (after.base.number, after.started_from.number, after.behind_main) == (2, 1, 0)

    async def test_restoring_a_fork_version_stays_on_the_fork(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        versions = SkillVersionService(db)
        read = await self._fork(db, ctx, skill)
        fork = await db.get(SkillFork, read.id)
        first = await versions.edit(ctx, skill.id, _edit(skill, read.base.id, "One.", fork))
        second = await versions.edit(ctx, skill.id, _edit(skill, first.id, "Two.", fork))

        restored = await versions.restore(
            ctx, skill.id, first.id, SkillVersionRestore(base_version_id=second.id)
        )

        assert (restored.fork_id, restored.number, restored.content) == (fork.id, 3, "One.")
        assert skill.content == "Ask for the order id."
        listed = await versions.list_versions(ctx, skill.id, fork_id=read.id)
        assert [item.number for item in listed.items] == [3, 2, 1]

    async def test_a_fork_no_run_has_read_for_30_days_is_offered_for_archiving(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        versions = SkillVersionService(db)
        quiet_read = await self._fork(db, ctx, skill, name="quiet")
        busy_read = await self._fork(db, ctx, skill, name="busy")
        quiet, busy = await db.get(SkillFork, quiet_read.id), await db.get(SkillFork, busy_read.id)
        assert quiet is not None and busy is not None
        busy_version = await versions.edit(
            ctx, skill.id, _edit(skill, busy_read.base.id, "Busy.", busy)
        )
        month_ago = datetime.now(UTC) - timedelta(days=31)
        quiet.created_at = busy.created_at = month_ago
        agent = await _published(db, ctx, name="Clerk", spec={"name": "Clerk"})
        db.add(
            AgentRun(
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                status="completed",
                surface="web",
                skill_version_ids=[busy_version.id],
            )
        )
        await db.flush()

        listed = {item.name: item for item in (await versions.list_forks(ctx, skill.id)).items}

        assert listed["quiet"].archive_candidate is True
        assert listed["busy"].archive_candidate is False


class TestWhoMayDoWhat:
    async def test_another_organization_reaches_nothing(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        stranger = await _owner(db)
        versions = SkillVersionService(db)
        assert skill.latest_version_id is not None

        with pytest.raises(NotFoundError):
            await versions.list_versions(stranger, skill.id, fork_id=None)
        with pytest.raises(NotFoundError):
            await versions.read_version(stranger, skill.id, skill.latest_version_id)
        with pytest.raises(NotFoundError):
            await versions.edit(stranger, skill.id, _edit(skill, skill.latest_version_id, "x"))

    async def test_a_version_of_another_skill_is_not_found_through_this_one(self, db):
        ctx = await _owner(db)
        skill, other = await _skill(db, ctx), await _skill(db, ctx, name="invoices")
        assert other.latest_version_id is not None

        with pytest.raises(NotFoundError):
            await SkillVersionService(db).read_version(ctx, skill.id, other.latest_version_id)

    async def test_a_reader_without_edit_access_reads_the_history_and_changes_nothing(self, db):
        """A viewer of an organization-wide skill sees its versions; without a grant
        to edit it, every write answers as if the skill were not there."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        viewer = await _member(db, ctx, OrgRoleName.VIEWER)
        versions = SkillVersionService(db)
        assert skill.latest_version_id is not None

        listed = await versions.list_versions(viewer, skill.id, fork_id=None)
        assert listed.total == 1 and listed.items[0].created_by is not None

        with pytest.raises(NotFoundError):
            await versions.edit(viewer, skill.id, _edit(skill, skill.latest_version_id, "x"))
        with pytest.raises(NotFoundError):
            await versions.create_fork(
                viewer,
                skill.id,
                SkillForkCreate(name="mine", from_version_id=skill.latest_version_id),
            )
        with pytest.raises(NotFoundError):
            await versions.restore(
                viewer,
                skill.id,
                skill.latest_version_id,
                SkillVersionRestore(base_version_id=skill.latest_version_id),
            )

    async def test_the_schema_keeps_a_version_in_its_skills_organization(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        stranger = await _owner(db)
        db.add(
            SkillVersion(
                organization_id=stranger.organization_id,
                skill_id=skill.id,
                number=9,
                description="d",
                content="c",
                source="edit",
            )
        )

        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_two_versions_cannot_share_a_number_on_one_line(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        db.add(
            SkillVersion(
                organization_id=ctx.organization_id,
                skill_id=skill.id,
                number=1,
                description="d",
                content="c",
                source="edit",
            )
        )

        with pytest.raises(IntegrityError):
            await db.flush()


class TestDeleting:
    async def test_a_skill_nobody_uses_goes_with_its_versions_and_forks(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        assert skill.latest_version_id is not None
        await SkillVersionService(db).create_fork(
            ctx, skill.id, SkillForkCreate(name="returns", from_version_id=skill.latest_version_id)
        )

        await SkillService(db).delete(ctx, skill.id)

        assert await db.scalar(select(func.count()).select_from(SkillVersion)) == 0
        assert await db.scalar(select(func.count()).select_from(SkillFork)) == 0

    async def test_a_skill_in_an_agents_draft_is_not_deleted(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        await _published(
            db, ctx, name="Clerk", spec={"name": "Clerk", "skill_ids": [str(skill.id)]}
        )

        with pytest.raises(InUseError) as refused:
            await SkillService(db).delete(ctx, skill.id)

        assert [agent["name"] for agent in refused.value.details["agents"]] == ["Clerk"]
        assert refused.value.details["hidden"] == 0
        assert "is used by 'Clerk'." in refused.value.message

    async def test_an_agent_the_caller_cannot_see_is_counted_and_never_named(self, db):
        owner = await _owner(db)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        skill = await _skill(db, member)
        secret = await _published(
            db, owner, name="Secret", spec={"name": "Secret", "skill_ids": [str(skill.id)]}
        )
        secret.visibility = "private"
        await db.flush()

        with pytest.raises(InUseError) as refused:
            await SkillService(db).delete(member, skill.id)

        assert refused.value.details == {"agents": [], "hidden": 1}
        assert "is used by 1 agent you cannot see." in refused.value.message
        assert "Secret" not in refused.value.message

    async def test_a_skill_a_served_specialist_binds_is_not_deleted(self, db):
        """The draft moved on; production still serves a version whose specialist reads it."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        served = {
            "name": "Clerk",
            "capabilities": [
                {
                    "id": "subagents",
                    "config": {
                        "inline": [
                            {
                                "name": "returns",
                                "description": "Handles returns.",
                                "instructions": "Handle returns.",
                                "skill_ids": [str(skill.id)],
                            }
                        ]
                    },
                }
            ],
        }
        agent: Agent = await _published(db, ctx, name="Clerk", spec=served)
        agent.draft_spec = {"name": "Clerk"}
        assert agent.current_version_id is not None
        db.add(
            AgentEnvironment(
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                name="production",
                version_id=agent.current_version_id,
                is_default=True,
            )
        )
        await db.flush()

        with pytest.raises(InUseError):
            await SkillService(db).delete(ctx, skill.id)

    async def test_an_agent_is_one_user_however_many_places_bind_it(self, db):
        """Served in two environments and bound in its draft, it is still one agent."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _published(
            db, ctx, name="Clerk", spec={"name": "Clerk", "skill_ids": [str(skill.id)]}
        )
        assert agent.current_version_id is not None
        for name in ("production", "staging"):
            db.add(
                AgentEnvironment(
                    organization_id=ctx.organization_id,
                    agent_id=agent.id,
                    name=name,
                    version_id=agent.current_version_id,
                    is_default=name == "production",
                )
            )
        await db.flush()

        with pytest.raises(InUseError) as refused:
            await SkillService(db).delete(ctx, skill.id)

        assert len(refused.value.details["agents"]) == 1

    async def test_a_draft_that_no_longer_reads_counts_as_using_it(self, db):
        """Not knowing is not permission: the draft's owner fixes it, and the skill
        is not deleted from under them meanwhile."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _published(db, ctx, name="Clerk", spec={"name": "Clerk"})
        agent.draft_spec = {"skill_ids": [str(skill.id)], "no_such_field": True}
        await db.flush()

        with pytest.raises(InUseError):
            await SkillService(db).delete(ctx, skill.id)

    async def test_a_served_version_that_no_longer_reads_blocks_only_its_own_skills(self, db):
        """Only a spec that names the skill is parsed, so one stored before a format
        change does not block deleting every other skill of the organization."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _published(db, ctx, name="Clerk", spec={"no_such_field": True})
        assert agent.current_version_id is not None
        db.add(
            AgentEnvironment(
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                name="production",
                version_id=agent.current_version_id,
                is_default=True,
            )
        )
        await db.flush()

        await SkillService(db).delete(ctx, skill.id)

        assert await db.get(Skill, skill.id) is None

    async def test_an_archived_agent_uses_nothing(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _published(
            db, ctx, name="Clerk", spec={"name": "Clerk", "skill_ids": [str(skill.id)]}
        )
        agent.status = "archived"
        await db.flush()

        await SkillService(db).delete(ctx, skill.id)

        assert await db.get(Skill, skill.id) is None


class TestTheSkillPage:
    async def test_the_page_says_what_the_caller_may_do_and_how_many_forks_there_are(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        viewer = await _member(db, ctx, OrgRoleName.VIEWER)
        assert skill.latest_version_id is not None
        await SkillVersionService(db).create_fork(
            ctx, skill.id, SkillForkCreate(name="returns", from_version_id=skill.latest_version_id)
        )
        service = SkillService(db)

        mine = await service.read(ctx, skill)
        theirs = await service.read(viewer, skill)

        assert (mine.can_edit, mine.forks, mine.latest_version_id) == (
            True,
            1,
            skill.latest_version_id,
        )
        assert theirs.can_edit is False

    async def test_an_edit_in_progress_does_not_hold_up_an_agent_binding_the_skill(
        self, db: AsyncSession, engine: AsyncEngine
    ):
        """An edit or a decision locks the skill and then the agents it moves; an agent's
        save holds the agent and then the skill. The two locks must not wait for each
        other, or the pair deadlocks."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _published(db, ctx, name="Clerk", spec={"name": "Clerk"})
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        bound = AgentSpec.model_validate({"name": "Clerk", "skill_ids": [str(skill.id)]})

        async with factory() as editing, factory() as binding:
            try:
                await skill_repo.lock(editing, skill.id)

                await asyncio.wait_for(
                    AgentRegistryService(binding).save_draft(ctx, agent.id, bound), timeout=3
                )
                await binding.commit()
            finally:
                await editing.rollback()

    async def test_a_binding_saved_while_a_delete_waits_stops_the_delete(
        self, db: AsyncSession, engine: AsyncEngine
    ):
        """Held here half-way: the draft binds the skill and has not committed yet. The
        delete waits for it rather than deleting a skill a live draft now names."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _published(db, ctx, name="Clerk", spec={"name": "Clerk"})
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        bound = AgentSpec.model_validate({"name": "Clerk", "skill_ids": [str(skill.id)]})

        async def delete_skill() -> None:
            async with factory() as session:
                await SkillService(session).delete(ctx, skill.id)
                await session.commit()

        task: asyncio.Task[None] | None = None
        async with factory() as binding:
            try:
                await AgentRegistryService(binding).save_draft(ctx, agent.id, bound)
                task = asyncio.create_task(delete_skill())
                await asyncio.sleep(0.4)
                assert not task.done()

                await binding.commit()
                with pytest.raises(InUseError):
                    await task
                task = None
            finally:
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
