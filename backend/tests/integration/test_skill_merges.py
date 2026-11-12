"""Merging a fork with main: the three-way merge a catch-up or a move to main works on.

Against a real database, because the merge is read off stored versions and their
files, and accepting writes versions and moves the fork's base under row locks.
"""

import uuid
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    ConflictError,
    NotFoundError,
)
from app.core.exceptions import ValidationError as TooLargeToMerge
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.improvement import ImprovementStage, ImprovementStatus
from app.db.models.resource_grant import Visibility
from app.db.models.skill import Skill
from app.db.models.skill_improvement import SkillImprovementPurpose, SkillImprovementRun
from app.db.models.skill_merge import SkillMerge
from app.db.models.skill_version import SkillFork, SkillVersionSource
from app.repositories import skill_repo, skill_version_repo
from app.schemas.skill import SkillUpdate
from app.schemas.skill_check import SkillCheckApply
from app.schemas.skill_merge import MergeDescriptionEdit, MergeFilePick, MergePartEdit
from app.schemas.skill_version import SkillForkCreate, SkillVersionCreate
from app.services.skill_catch_up import SkillCatchUpService
from app.services.skill_check import SkillCheckService
from app.services.skill_merge import MAX_LINES
from app.services.skill_versions import SkillVersionService, manifest_of
from app.services.skills import SkillService
from tests.integration.test_authoring import _member, _owner
from tests.integration.test_skill_checks import FakeEvals, Outcome, _lab, _run_to_end, _start

pytestmark = pytest.mark.anyio

CATCH_UP = SkillImprovementPurpose.CATCH_UP
TO_MAIN = SkillImprovementPurpose.TO_MAIN


async def _skill(db: AsyncSession, ctx: AuthContext) -> Skill:
    skill = await SkillService(db).create(
        ctx,
        name="refunds",
        description="How refunds work.",
        content="one\ntwo\nthree\nfour",
        visibility=Visibility.ORG,
    )
    await SkillService(db).put_resources(ctx, skill.id, [("a.md", b"first")])
    return skill


async def _fork(db: AsyncSession, ctx: AuthContext, skill: Skill) -> SkillFork:
    assert skill.latest_version_id is not None
    made = await SkillVersionService(db).create_fork(
        ctx, skill.id, SkillForkCreate(name="returns", from_version_id=skill.latest_version_id)
    )
    return await _fork_row(db, ctx, skill, made.id)


async def _fork_row(db: AsyncSession, ctx: AuthContext, skill: Skill, fork_id: Any) -> SkillFork:
    fork = await skill_version_repo.get_fork(
        db, fork_id, organization_id=ctx.organization_id, skill_id=skill.id
    )
    assert fork is not None
    await db.refresh(fork)
    return fork


async def _on_fork(
    db: AsyncSession,
    ctx: AuthContext,
    skill: Skill,
    fork: SkillFork,
    *,
    content: str | None = None,
    description: str | None = None,
    files: dict[str, str] | None = None,
) -> SkillFork:
    """A new fork version: its text edited, or its files replaced by `files`."""
    versions = SkillVersionService(db)
    current = await skill_version_repo.get_version(
        db,
        versions.line_latest(skill, fork) or fork.base_version_id,
        organization_id=ctx.organization_id,
        skill_id=skill.id,
    )
    assert current is not None
    resources = current.resources
    if files is not None:
        resources, bodies = manifest_of((name, None, text) for name, text in files.items())
        await skill_version_repo.put_files(
            db, organization_id=ctx.organization_id, skill_id=skill.id, bodies=bodies
        )
    await versions.record_fork(
        ctx,
        fork,
        description=description or current.description,
        content=content or current.content,
        resources=resources,
        source=SkillVersionSource.EDIT,
    )
    return await _fork_row(db, ctx, skill, fork.id)


async def _main(db: AsyncSession, ctx: AuthContext, skill: Skill, **update: Any) -> None:
    await SkillService(db).update(ctx, skill.id, SkillUpdate(**update))
    await db.refresh(skill)


async def _session(
    db: AsyncSession,
    ctx: AuthContext,
    skill: Skill,
    fork: SkillFork,
    purpose: SkillImprovementPurpose,
    *,
    status: ImprovementStatus = ImprovementStatus.WAITING,
    stage: ImprovementStage = ImprovementStage.FILTERING,
) -> SkillImprovementRun:
    to_main = purpose is TO_MAIN
    assert skill.latest_version_id is not None
    run = SkillImprovementRun(
        organization_id=ctx.organization_id,
        skill_id=skill.id,
        fork_id=None if to_main else fork.id,
        source_fork_id=fork.id if to_main else None,
        purpose=purpose.value,
        base_version_id=skill.latest_version_id if to_main else fork.base_version_id,
        created_by_user_id=ctx.user_id,
        status=status.value,
        stage=stage.value,
        window_days=7,
        estimate_usd=Decimal("0"),
        budget_usd=Decimal("1"),
    )
    db.add(run)
    await db.flush()
    return run


async def _merged(
    db: AsyncSession,
    ctx: AuthContext,
    skill: Skill,
    fork: SkillFork,
    purpose: SkillImprovementPurpose = CATCH_UP,
) -> SkillMerge:
    run = await _session(db, ctx, skill, fork, purpose)
    return await SkillCatchUpService(db).build_merge(ctx, run=run, skill=skill, fork=fork)


class TestWhatCannotBeMerged:
    async def test_a_fork_with_no_version_of_its_own_returns_to_main_instead(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        await _main(db, ctx, skill, content="one\ntwo\nthree\nFOUR")

        with pytest.raises(ConflictError, match="no changes of its own"):
            await SkillCatchUpService(db).merge_sides(ctx, skill=skill, fork=fork, kind=CATCH_UP)

    async def test_an_archived_fork_takes_nothing_in(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _on_fork(db, ctx, skill, await _fork(db, ctx, skill), content="one")
        await SkillVersionService(db).archive_fork(ctx, skill.id, fork.id)
        await db.refresh(fork)

        with pytest.raises(ConflictError, match="archived"):
            await SkillCatchUpService(db).merge_sides(ctx, skill=skill, fork=fork, kind=TO_MAIN)

    async def test_a_side_with_nothing_new_has_nothing_to_merge(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _on_fork(db, ctx, skill, await _fork(db, ctx, skill), content="one\nTWO")
        service = SkillCatchUpService(db)

        with pytest.raises(ConflictError, match="Main has nothing"):
            await service.merge_sides(ctx, skill=skill, fork=fork, kind=CATCH_UP)
        sides = await service.merge_sides(ctx, skill=skill, fork=fork, kind=TO_MAIN)
        assert (sides.conflicts, sides.prompt) == (0, "")

        await _main(db, ctx, skill, content="one\nTWO")
        for kind in (CATCH_UP, TO_MAIN):
            with pytest.raises(ConflictError):
                await service.merge_sides(ctx, skill=skill, fork=fork, kind=kind)

    async def test_texts_too_long_to_merge_are_refused_before_merging(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        long = "".join(f"Check line {number}.\n" for number in range(MAX_LINES))
        await _main(db, ctx, skill, content=long + "Say hello.")
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(db, ctx, skill, fork, content=long + "Say goodbye.")
        await _main(db, ctx, skill, content=long + "Say thanks.")

        with pytest.raises(TooLargeToMerge) as refused:
            await SkillCatchUpService(db).merge_sides(ctx, skill=skill, fork=fork, kind=CATCH_UP)

        assert refused.value.status_code == 422
        assert "too long to merge" in refused.value.message
        assert refused.value.details["max_lines"] == MAX_LINES

    async def test_a_fork_that_changed_nothing_has_nothing_to_move_to_main(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(db, ctx, skill, fork, content="one\ntwo\nthree\nfour")
        await _main(db, ctx, skill, content="one")

        with pytest.raises(ConflictError, match="has nothing main does not have"):
            await SkillCatchUpService(db).merge_sides(ctx, skill=skill, fork=fork, kind=TO_MAIN)


class TestTheMerge:
    async def test_changes_on_lines_apart_merge_by_themselves(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(db, ctx, skill, fork, content="one\nTWO\nthree\nfour")
        await _main(db, ctx, skill, content="one\ntwo\nthree\nFOUR")
        service = SkillCatchUpService(db)

        merge = await _merged(db, ctx, skill, fork)

        assert (merge.kind, merge.conflicts, merge.unresolved) == ("catch_up", 0, 0)
        assert [part["state"] for part in merge.parts] == ["same", "fork", "same", "main"]
        assert service.conflicts_prompt(merge) == ""
        merged = await service.candidate_of(merge)
        assert merged is not None
        assert (merged.description, merged.content) == (
            "How refunds work.",
            "one\nTWO\nthree\nFOUR",
        )
        assert [(item.name, item.content) for item in merged.files] == [("a.md", "first")]
        assert await service.merge_for_run(merge.run_id, organization_id=ctx.organization_id) == (
            merge
        )

    async def test_a_line_both_sides_changed_waits_for_a_combined_text(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(db, ctx, skill, fork, content="one\ntwo, by fork\nthree\nfour")
        await _main(db, ctx, skill, content="one\ntwo, by main\nthree\nfour")
        service = SkillCatchUpService(db)

        merge = await _merged(db, ctx, skill, fork)

        assert (merge.conflicts, merge.unresolved) == (1, 1)
        assert await service.candidate_of(merge) is None
        assert service.conflicts_prompt(merge) == (
            "Conflict 1 of 1 - the instructions\n<base>\ntwo\n\n</base>\n"
            "<fork>\ntwo, by fork\n\n</fork>\n<main>\ntwo, by main\n\n</main>"
        )

        # The model's text ends where the part ended, with its line break.
        await service.fill_conflicts(merge, ["two, by both"])

        conflict = merge.parts[1]
        assert (conflict["result"], conflict["proposed"], conflict["edited"]) == (
            "two, by both\n",
            "two, by both\n",
            False,
        )
        merged = await service.candidate_of(merge)
        assert merged is not None and merged.content == "one\ntwo, by both\nthree\nfour"
        assert merge.unresolved == 0

    async def test_the_model_writes_one_text_per_conflict_or_none(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(db, ctx, skill, fork, content="fork")
        await _main(db, ctx, skill, content="main")
        merge = await _merged(db, ctx, skill, fork)

        with pytest.raises(ValueError, match="1 conflicts, 2 texts"):
            await SkillCatchUpService(db).fill_conflicts(merge, ["a", "b"])
        assert merge.unresolved == 1

    async def test_a_description_both_changed_is_the_first_conflict(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(
            db, ctx, skill, fork, content="fork", description="Refunds, the fork's way."
        )
        await _main(db, ctx, skill, content="main", description="Refunds, main's way.")
        service = SkillCatchUpService(db)

        sides = await service.merge_sides(ctx, skill=skill, fork=fork, kind=CATCH_UP)
        merge = await _merged(db, ctx, skill, fork)

        assert (sides.conflicts, merge.conflicts) == (2, 2)
        assert sides.prompt == service.conflicts_prompt(merge)
        assert sides.prompt.startswith("Conflict 1 of 2 - the description\n<base>\nHow refunds")
        await service.fill_conflicts(merge, ["Refunds, both ways.", "both"])
        merged = await service.candidate_of(merge)
        assert merged is not None
        assert (merged.description, merged.content) == ("Refunds, both ways.", "both")

    async def test_files_merge_by_name_and_one_both_changed_waits_for_a_side(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(
            db, ctx, skill, fork, files={"a.md": "fork's a", "c.md": "fork's own"}
        )
        await SkillService(db).put_resources(ctx, skill.id, [("a.md", b"main's a")])
        await SkillService(db).put_resources(ctx, skill.id, [("b.md", b"main's own")])
        await db.refresh(skill)
        service = SkillCatchUpService(db)

        merge = await _merged(db, ctx, skill, fork)

        assert [(row["name"], row["state"], row["take"]) for row in merge.files] == [
            ("a.md", "conflict", None),
            ("b.md", "main", "main"),
            ("c.md", "fork", "fork"),
        ]
        assert (merge.conflicts, merge.unresolved) == (0, 1)
        assert await service.candidate_of(merge) is None

        await service.pick_file(
            ctx, skill.id, merge.run_id, MergeFilePick(name="a.md", take="fork")
        )

        merged = await service.candidate_of(merge)
        assert merged is not None
        assert [(item.name, item.content) for item in merged.files] == [
            ("a.md", "fork's a"),
            ("b.md", "main's own"),
            ("c.md", "fork's own"),
        ]
        assert sorted(merged.resources) == ["a.md", "b.md", "c.md"]

    async def test_a_file_one_side_deleted_and_the_other_kept_is_dropped(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(db, ctx, skill, fork, files={})
        await _main(db, ctx, skill, content="one")

        merge = await _merged(db, ctx, skill, fork)

        assert [(row["name"], row["state"], row["take"]) for row in merge.files] == [
            ("a.md", "fork", "fork")
        ]
        merged = await SkillCatchUpService(db).candidate_of(merge)
        assert merged is not None and (merged.files, merged.resources) == ((), {})


class TestTheModelsTexts:
    async def test_a_persons_text_stands_beside_the_models(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(db, ctx, skill, fork, content="one\nfork")
        await _main(db, ctx, skill, content="one\nmain")
        merge = await _merged(db, ctx, skill, fork)
        service = SkillCatchUpService(db)
        await service.edit_part(ctx, skill.id, merge.run_id, 1, MergePartEdit(result="mine"))

        await service.fill_conflicts(merge, ["the model's"])

        part = merge.parts[1]
        assert (part["result"], part["proposed"], part["edited"]) == ("mine", "the model's", True)
        assert merge.unresolved == 0

    async def test_a_description_out_of_bounds_stays_for_a_person(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(db, ctx, skill, fork, content="fork", description="The fork's.")
        await _main(db, ctx, skill, content="main", description="Main's.")
        merge = await _merged(db, ctx, skill, fork)

        await SkillCatchUpService(db).fill_conflicts(merge, ["  ", "both"])

        assert (merge.description["result"], merge.description["proposed"]) == (None, None)
        assert (merge.parts[0]["result"], merge.unresolved) == ("both", 1)

    async def test_a_line_both_sides_deleted_and_a_person_wrote_keeps_the_next_apart(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(db, ctx, skill, fork, content="one\nthree\nfour")
        await _main(db, ctx, skill, content="one\nthree\nFOUR")
        merge = await _merged(db, ctx, skill, fork)
        service = SkillCatchUpService(db)
        assert [part["state"] for part in merge.parts] == ["same", "both", "same", "main"]

        await service.edit_part(ctx, skill.id, merge.run_id, 1, MergePartEdit(result="2"))

        merged = await service.candidate_of(merge)
        assert merged is not None and merged.content == "one\n2\nthree\nFOUR"


class TestCatchingUp:
    async def test_accepting_makes_a_fork_version_that_took_main_in(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        started = fork.base_version_id
        fork = await _on_fork(db, ctx, skill, fork, content="one\nTWO\nthree\nfour")
        await _main(db, ctx, skill, content="one\ntwo\nthree\nFOUR")
        service = SkillCatchUpService(db)
        merge = await _merged(db, ctx, skill, fork)

        version = await service.accept_catch_up(ctx, skill=skill, fork=fork, merge=merge)

        fork = await _fork_row(db, ctx, skill, fork.id)
        assert (version.source, version.merged_from_id, version.content) == (
            "catch_up",
            skill.latest_version_id,
            "one\nTWO\nthree\nFOUR",
        )
        assert (fork.latest_version_id, fork.base_version_id, fork.started_from_id) == (
            version.id,
            skill.latest_version_id,
            started,
        )
        with pytest.raises(ConflictError, match="Main has nothing"):
            await service.merge_sides(ctx, skill=skill, fork=fork, kind=CATCH_UP)

    async def _caught_up(
        self, db: AsyncSession
    ) -> tuple[AuthContext, Skill, SkillFork, SkillMerge]:
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(db, ctx, skill, fork, content="one\nTWO\nthree\nfour")
        await _main(db, ctx, skill, content="one\ntwo\nthree\nFOUR")
        return ctx, skill, fork, await _merged(db, ctx, skill, fork)

    async def test_main_moving_after_the_merge_refuses_the_accept(self, db):
        ctx, skill, fork, merge = await self._caught_up(db)
        await _main(db, ctx, skill, content="one\ntwo\nthree\nFOUR, again")

        with pytest.raises(ConcurrentChangeError, match="Main has a newer version"):
            await SkillCatchUpService(db).accept_catch_up(ctx, skill=skill, fork=fork, merge=merge)

    async def test_the_fork_moving_after_the_merge_refuses_the_accept(self, db):
        ctx, skill, fork, merge = await self._caught_up(db)
        fork = await _on_fork(db, ctx, skill, fork, content="one\nTWO, again\nthree\nfour")
        with pytest.raises(ConcurrentChangeError, match="'returns' has a newer version"):
            await SkillCatchUpService(db).accept_catch_up(ctx, skill=skill, fork=fork, merge=merge)

    async def test_an_unsettled_merge_is_not_accepted(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(db, ctx, skill, fork, content="fork")
        await _main(db, ctx, skill, content="main")
        service = SkillCatchUpService(db)
        merge = await _merged(db, ctx, skill, fork)

        with pytest.raises(BadRequestError, match="Settle every conflict"):
            await service.accept_catch_up(ctx, skill=skill, fork=fork, merge=merge)


class TestMovingToMain:
    async def test_a_checked_merge_becomes_main_with_the_fork_it_took_in(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        fork = await _fork_row(db, lab.ctx, lab.skill, lab.fork_id)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.a.id: Outcome(fixed=2)}
        await _run_to_end(service, evals, lab, check.id)

        applied = await service.apply(
            lab.ctx,
            lab.skill.id,
            check.id,
            SkillCheckApply(),
            merged_from_id=fork.latest_version_id,
        )

        version = await skill_version_repo.get_version(
            db, applied.version.id, organization_id=lab.ctx.organization_id, skill_id=lab.skill.id
        )
        assert version is not None
        assert (version.fork_id, version.source, version.merged_from_id) == (
            None,
            "from_fork",
            fork.latest_version_id,
        )
        # The check served main's own files, so main keeps them.
        assert sorted(version.resources) == ["a.md"]

    async def test_main_takes_the_fork_files_the_merge_keeps(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(db, ctx, skill, fork, files={"c.md": "fork's own"})
        await _main(db, ctx, skill, content="one")
        service = SkillCatchUpService(db)
        merge = await _merged(db, ctx, skill, fork, TO_MAIN)
        merged = await service.candidate_of(merge)
        assert merged is not None
        locked = await skill_repo.lock(db, skill.id)
        assert locked is not None

        version = await SkillService(db).take_in(
            ctx,
            locked,
            description=merged.description,
            content=merged.content,
            files=merged.files,
            merged_from_id=merge.fork_version_id,
        )

        assert (version.source, version.merged_from_id, version.content) == (
            "from_fork",
            fork.latest_version_id,
            "one",
        )
        assert sorted(version.resources) == ["c.md"]
        bodies = await SkillVersionService(db).files_of(version)
        assert bodies == {"c.md": "fork's own"}

    async def test_main_moving_after_the_check_refuses_the_move(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        fork = await _fork_row(db, lab.ctx, lab.skill, lab.fork_id)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.a.id: Outcome(fixed=2)}
        await _run_to_end(service, evals, lab, check.id)
        await SkillVersionService(db).edit(
            lab.ctx,
            lab.skill.id,
            SkillVersionCreate(
                base_version_id=lab.skill.latest_version_id,
                description=lab.skill.description,
                content="moved on",
            ),
        )

        with pytest.raises(ConcurrentChangeError, match="changed since this was checked"):
            await service.apply(
                lab.ctx,
                lab.skill.id,
                check.id,
                SkillCheckApply(),
                merged_from_id=fork.latest_version_id,
            )


class TestEditingTheMerge:
    async def _conflicted(self, db: AsyncSession) -> tuple[AuthContext, Skill, SkillMerge]:
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(
            db, ctx, skill, fork, content="one\nfork", description="Refunds, the fork's way."
        )
        await _main(db, ctx, skill, content="one\nmain", description="Refunds, main's way.")
        return ctx, skill, await _merged(db, ctx, skill, fork)

    async def test_a_person_settles_every_conflict_at_changes(self, db):
        ctx, skill, merge = await self._conflicted(db)
        service = SkillCatchUpService(db)

        read = await service.read_merge(ctx, skill.id, merge.run_id)
        assert (read.kind, read.conflicts, read.unresolved) == ("catch_up", 2, 2)
        assert (read.base.number, read.fork.number, read.main.number) == (2, 1, 3)
        assert read.description.state == "conflict" and read.description.result is None
        assert [part.state for part in read.parts] == ["same", "conflict"]
        assert read.files[0].model_dump() == {
            "name": "a.md",
            "state": "same",
            "base": {"description": None, "size_bytes": 5},
            "fork": {"description": None, "size_bytes": 5},
            "main": {"description": None, "size_bytes": 5},
            "take": "main",
        }

        read = await service.edit_description(
            ctx, skill.id, merge.run_id, MergeDescriptionEdit(result="Refunds.")
        )
        assert (read.description.result, read.description.edited, read.unresolved) == (
            "Refunds.",
            True,
            1,
        )
        read = await service.edit_part(ctx, skill.id, merge.run_id, 1, MergePartEdit(result="both"))

        assert (read.parts[1].result, read.parts[1].edited, read.unresolved) == ("both", True, 0)
        merged = await service.candidate_of(merge)
        assert merged is not None
        assert (merged.description, merged.content) == ("Refunds.", "one\nboth")

    async def test_a_rewritten_line_keeps_the_next_one_on_its_own(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        fork = await _on_fork(db, ctx, skill, fork, content="one\ntwo, by fork\nthree\nfour")
        await _main(db, ctx, skill, content="one\ntwo, by main\nthree\nfour")
        merge = await _merged(db, ctx, skill, fork)
        service = SkillCatchUpService(db)

        read = await service.edit_part(ctx, skill.id, merge.run_id, 1, MergePartEdit(result="2"))
        assert read.parts[1].result == "2\n"
        merged = await service.candidate_of(merge)
        assert merged is not None and merged.content == "one\n2\nthree\nfour"

        await service.edit_part(ctx, skill.id, merge.run_id, 1, MergePartEdit(result=""))
        merged = await service.candidate_of(merge)
        assert merged is not None and merged.content == "one\nthree\nfour"

    async def test_a_part_or_file_the_merge_does_not_have_is_refused(self, db):
        ctx, skill, merge = await self._conflicted(db)
        service = SkillCatchUpService(db)

        with pytest.raises(NotFoundError, match="no such part"):
            await service.edit_part(ctx, skill.id, merge.run_id, 2, MergePartEdit(result="x"))
        with pytest.raises(NotFoundError, match="no such part"):
            await service.edit_part(ctx, skill.id, merge.run_id, -1, MergePartEdit(result="x"))
        with pytest.raises(BadRequestError, match="no file by that name"):
            await service.pick_file(
                ctx, skill.id, merge.run_id, MergeFilePick(name="z.md", take="main")
            )

    async def test_the_merge_is_edited_only_while_its_session_waits_at_changes(self, db):
        ctx, skill, merge = await self._conflicted(db)
        run = await db.get(SkillImprovementRun, merge.run_id)
        assert run is not None
        run.status = ImprovementStatus.RUNNING.value
        run.stage = ImprovementStage.EVALUATING.value
        await db.flush()
        service = SkillCatchUpService(db)

        with pytest.raises(BadRequestError, match="waits at Changes"):
            await service.edit_description(
                ctx, skill.id, merge.run_id, MergeDescriptionEdit(result="Refunds.")
            )
        assert (await service.read_merge(ctx, skill.id, merge.run_id)).unresolved == 2

    async def test_a_session_that_merges_nothing_has_no_merge(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        run = await _session(db, ctx, skill, fork, SkillImprovementPurpose.IMPROVE)

        with pytest.raises(NotFoundError, match="merges nothing"):
            await SkillCatchUpService(db).read_merge(ctx, skill.id, run.id)

    @pytest.mark.security
    async def test_who_may_read_and_edit_a_merge(self, db):
        ctx, skill, merge = await self._conflicted(db)
        service = SkillCatchUpService(db)
        edit = MergeDescriptionEdit(result="Refunds.")

        blind = replace(ctx, key_scopes=frozenset(Perm) - {Perm.RUNS_VIEW})
        with pytest.raises(AuthorizationError, match="runs:view"):
            await service.read_merge(blind, skill.id, merge.run_id)
        with pytest.raises(AuthorizationError, match="runs:view"):
            await service.edit_description(blind, skill.id, merge.run_id, edit)

        operator = await _member(db, ctx, OrgRoleName.OPERATOR)
        assert (await service.read_merge(operator, skill.id, merge.run_id)).unresolved == 2
        with pytest.raises(AuthorizationError, match="edit access to the skill"):
            await service.edit_description(operator, skill.id, merge.run_id, edit)

    @pytest.mark.security
    async def test_another_organizations_merge_is_not_found(self, db):
        ctx, skill, merge = await self._conflicted(db)
        other = await _owner(db)
        service = SkillCatchUpService(db)

        with pytest.raises(NotFoundError):
            await service.read_merge(other, skill.id, merge.run_id)
        other_skill = await _skill(db, other)
        with pytest.raises(NotFoundError, match="session not found"):
            await service.read_merge(other, other_skill.id, merge.run_id)
        with pytest.raises(NotFoundError, match="session not found"):
            await service.edit_part(
                other, other_skill.id, merge.run_id, 0, MergePartEdit(result="x")
            )


def test_a_merge_names_its_session_and_kind():
    merge = SkillMerge(run_id=uuid.uuid4(), kind="to_main")
    assert "to_main" in repr(merge) and str(merge.run_id) in repr(merge)
