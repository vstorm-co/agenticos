"""A session that merges two lines of a skill: a fork catching up with main, or a fork
moving to main, against a real database.

The merge itself is `SkillCatchUpService`'s and runs for real. The multi-agent check is
the fake the improvement session's tests use, and the conflicts' model call is priced
here and answered by settling its request, so each move is the session's own.
"""

import threading
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    ConflictError,
    NotFoundError,
    PaymentRequiredError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.authoring import AuthoringRequest, AuthoringStatus
from app.db.models.improvement import ImprovementStatus
from app.db.models.resource_grant import Visibility
from app.db.models.skill import Skill
from app.db.models.skill_check import AgentState, CheckStatus, SkillCheck
from app.db.models.skill_improvement import SkillImprovementPurpose, SkillImprovementRun
from app.db.models.skill_version import SkillFork, SkillVersion
from app.repositories import skill_improvement_repo, skill_version_repo
from app.schemas.authoring import AuthoringEstimate
from app.schemas.skill import SkillUpdate
from app.schemas.skill_check import AgentRef, SkillCheckAgentRead
from app.schemas.skill_improvement import (
    SkillContinuationConsent,
    SkillContinue,
    SkillImprovementApply,
    SkillImprovementFork,
    SkillImprovementRead,
    SkillImprovementReturn,
    SkillMergeStart,
)
from app.schemas.skill_version import SkillForkRead, SkillVersionCreate
from app.services import skill_catch_up as skill_catch_up_module
from app.services.authoring import AuthoringService
from app.services.skill_catch_up import SkillCatchUpService
from app.services.skill_improvement import SkillImprovementService
from app.services.skill_versions import SkillVersionService
from app.services.skills import SkillService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_authoring import _improver, _owner
from tests.integration.test_skill_bindings import _fork, _serving, _spec, _with_specialist
from tests.integration.test_skill_improvement import _checked

pytestmark = pytest.mark.anyio

CATCH_UP = SkillImprovementPurpose.CATCH_UP
TO_MAIN = SkillImprovementPurpose.TO_MAIN
_BODY = "Refunds take 14 days.\nAlways ask for the order number.\nBe polite."
_PRICE = Decimal("0.04")


@pytest.fixture
def call_price(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """What the conflicts' model call costs, and whether the improver can pay it."""
    state: dict[str, Any] = {"price": _PRICE, "affordable": True, "chars": []}

    async def estimate_call(self, ctx, *, chars, improver_agent_id=None):
        state["chars"].append(chars)
        return AuthoringEstimate(
            runs=0,
            rated_down=0,
            calls=1,
            estimate_usd=state["price"],
            affordable=state["affordable"],
            reason=None,
        )

    monkeypatch.setattr(AuthoringService, "estimate_call", estimate_call)
    return state


async def _diverged(
    db: AsyncSession, ctx: AuthContext, *, conflict: bool = False
) -> tuple[Skill, SkillForkRead]:
    """A skill whose fork changed its first line and whose main changed since the fork:
    its last line, or the same first line differently."""
    skill = await SkillService(db).create(
        ctx,
        name=f"refunds-{uuid.uuid4().hex[:6]}",
        description="How refunds work.",
        content=_BODY,
        visibility=Visibility.ORG,
    )
    await SkillService(db).put_resources(ctx, skill.id, [("a.md", b"first")])
    await db.refresh(skill)
    fork = await _fork(db, ctx, skill, _BODY.replace("14 days", "30 days"))
    main = _BODY.replace("14 days", "21 days") if conflict else _BODY.replace("polite", "brief")
    await SkillService(db).update(ctx, skill.id, SkillUpdate(content=main))
    await db.refresh(skill)
    return skill, fork


async def _row(db: AsyncSession, read: SkillImprovementRead) -> SkillImprovementRun:
    run = await db.get(SkillImprovementRun, read.id)
    assert run is not None
    await db.refresh(run)
    return run


async def _advance(db: AsyncSession, run: SkillImprovementRun) -> SkillImprovementRun:
    await SkillImprovementService(db).advance(run.id, run.organization_id)
    await db.refresh(run)
    return run


async def _started(
    db: AsyncSession, ctx: AuthContext, skill: Skill, fork: SkillForkRead, purpose=CATCH_UP
) -> SkillImprovementRun:
    read = await SkillImprovementService(db).start_merge(
        ctx, skill.id, fork.id, purpose, SkillMergeStart(budget_usd=Decimal("1"))
    )
    return await _row(db, read)


async def _at_changes(
    db: AsyncSession, ctx: AuthContext, purpose=CATCH_UP
) -> tuple[SkillImprovementRun, Skill, SkillForkRead]:
    skill, fork = await _diverged(db, ctx)
    run = await _started(db, ctx, skill, fork, purpose)
    await _advance(db, run)
    await _advance(db, run)
    assert (run.status, run.stage) == ("waiting", "filtering")
    return run, skill, fork


async def _check_now(
    db: AsyncSession, ctx: AuthContext, run: SkillImprovementRun, *, main_alone: bool = True
) -> SkillImprovementRead:
    service = SkillImprovementService(db)
    quote = await service.estimate_continuation(
        ctx, run.skill_id, run.id, SkillContinue(main_alone=main_alone)
    )
    return await service.continue_run(
        ctx,
        run.skill_id,
        run.id,
        SkillContinuationConsent(
            confirmed=True,
            estimate_usd=quote.total_usd,
            candidate_hash=quote.candidate_hash,
            budget_usd=run.budget_usd,
            main_alone=main_alone,
        ),
    )


async def _settle(
    db: AsyncSession,
    run: SkillImprovementRun,
    merged: str | None,
    alone: str | None = None,
) -> SkillImprovementRun:
    """Finish the attempt's checks with these verdicts, then let the session judge them."""
    iteration = await skill_improvement_repo.get_iteration(
        db, organization_id=run.organization_id, run_id=run.id, number=run.iteration
    )
    assert iteration is not None and iteration.skill_check_id is not None
    for check_id, verdict in (
        (iteration.skill_check_id, merged),
        (iteration.main_alone_check_id, alone),
    ):
        if check_id is None:
            continue
        check = await db.get(SkillCheck, check_id)
        assert check is not None
        check.status, check.verdict = CheckStatus.DONE.value, verdict
    await db.flush()
    return await _advance(db, run)


async def _finish_request(db: AsyncSession, run: SkillImprovementRun, status: str) -> None:
    iteration = await skill_improvement_repo.get_iteration(
        db, organization_id=run.organization_id, run_id=run.id, number=run.iteration
    )
    assert iteration is not None and iteration.authoring_request_id is not None
    request = await db.get(AuthoringRequest, iteration.authoring_request_id)
    assert request is not None
    request.status = status
    request.finished_at = datetime.now(UTC)
    await db.flush()


def _unknown(fake: Any, *, name: str, hidden: bool) -> None:
    """The check's one agent that could not be checked, named or one the reader cannot see."""
    if hidden:
        fake.hidden_unknown = 1
        return
    fake.agents = [
        SkillCheckAgentRead(
            agent=AgentRef(id=uuid.uuid4(), name=name),
            state=AgentState.UNKNOWN,
            stages=[],
            expected_usd=Decimal(0),
            at_most_usd=Decimal(0),
        )
    ]


class TestStarting:
    async def test_a_catch_up_runs_on_the_fork_and_a_move_to_main_on_main(
        self, db, call_price, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _diverged(db, ctx)
        service = SkillImprovementService(db)

        estimate = await service.estimate_merge(ctx, skill.id, fork.id, CATCH_UP)
        caught = await service.start_merge(
            ctx, skill.id, fork.id, CATCH_UP, SkillMergeStart(budget_usd=Decimal("0"))
        )
        await service.cancel(ctx, skill.id, caught.id)
        moved = await service.start_merge(
            ctx, skill.id, fork.id, TO_MAIN, SkillMergeStart(budget_usd=Decimal("0"))
        )

        assert (estimate.conflicts, estimate.total_usd, estimate.line.fork_id) == (
            0,
            Decimal(0),
            fork.id,
        )
        assert (caught.purpose, caught.fork_id, caught.source_fork_id) == (
            "catch_up",
            fork.id,
            None,
        )
        assert caught.merge_id is not None and caught.max_iterations == 1
        assert (moved.purpose, moved.fork_id, moved.source_fork_id) == ("to_main", None, fork.id)
        assert call_price["chars"] == []

    async def test_starting_merges_once_and_off_the_event_loop(self, db, call_price, monkeypatch):
        """A long text takes the merge seconds of CPU, which the API's event loop serves
        every tenant's requests in between; starting reuses the merge the estimate made."""
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _diverged(db, ctx)
        threads: list[int] = []
        merging = skill_catch_up_module.merge_text

        def merge(base: str, fork_text: str, main: str) -> Any:
            threads.append(threading.get_ident())
            return merging(base, fork_text, main)

        monkeypatch.setattr(skill_catch_up_module, "merge_text", merge)

        await SkillImprovementService(db).start_merge(
            ctx, skill.id, fork.id, CATCH_UP, SkillMergeStart(budget_usd=Decimal("0"))
        )

        assert len(threads) == 1
        assert threads[0] != threading.get_ident()

    @pytest.mark.security
    async def test_conflicts_are_priced_as_one_call_the_budget_has_to_cover(
        self, db, call_price, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _diverged(db, ctx, conflict=True)
        service = SkillImprovementService(db)

        estimate = await service.estimate_merge(ctx, skill.id, fork.id, CATCH_UP)
        with pytest.raises(PaymentRequiredError):
            await service.start_merge(
                ctx, skill.id, fork.id, CATCH_UP, SkillMergeStart(budget_usd=Decimal("0.01"))
            )
        call_price["affordable"] = False
        with pytest.raises(PaymentRequiredError):
            await service.start_merge(
                ctx, skill.id, fork.id, CATCH_UP, SkillMergeStart(budget_usd=Decimal("1"))
            )

        assert (estimate.conflicts, estimate.total_usd) == (1, _PRICE)
        assert call_price["chars"] and call_price["chars"][0] > 0

    @pytest.mark.security
    async def test_a_merge_is_refused_where_it_cannot_run(self, db, call_price, monkeypatch):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _diverged(db, ctx)
        service = SkillImprovementService(db)
        other = await _owner(db)

        with pytest.raises(NotFoundError):
            await service.estimate_merge(ctx, skill.id, uuid.uuid4(), CATCH_UP)
        with pytest.raises(NotFoundError):
            await service.estimate_merge(other, skill.id, fork.id, CATCH_UP)
        with pytest.raises(AuthorizationError):
            await service.estimate_merge(
                replace(ctx, key_scopes=frozenset(Perm) - {Perm.RUNS_VIEW}),
                skill.id,
                fork.id,
                CATCH_UP,
            )
        await _started(db, ctx, skill, fork)
        with pytest.raises(AlreadyExistsError):
            await _started(db, ctx, skill, fork)
        row = await db.get(SkillFork, fork.id)
        assert row is not None
        row.archived_at = datetime.now(UTC)
        await db.flush()
        with pytest.raises(BadRequestError):
            await service.estimate_merge(ctx, skill.id, fork.id, TO_MAIN)

    async def test_nothing_to_merge_is_a_conflict(self, db, call_price, monkeypatch):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill = await SkillService(db).create(
            ctx,
            name=f"refunds-{uuid.uuid4().hex[:6]}",
            description="How refunds work.",
            content=_BODY,
            visibility=Visibility.ORG,
        )
        level = await _fork(db, ctx, skill)

        with pytest.raises(ConflictError):
            await SkillImprovementService(db).estimate_merge(ctx, skill.id, level.id, CATCH_UP)


class TestTheConflicts:
    async def test_the_model_proposes_them_once_and_the_merge_waits_at_changes(
        self, db, call_price, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _diverged(db, ctx, conflict=True)
        run = await _started(db, ctx, skill, fork)
        service = SkillImprovementService(db)

        await _advance(db, run)
        await _advance(db, run)
        with pytest.raises(BadRequestError):
            await service.estimate_continuation(ctx, skill.id, run.id, SkillContinue())
        merge = await SkillCatchUpService(db).merge_for_run(
            run.id, organization_id=ctx.organization_id
        )
        assert merge is not None
        await SkillCatchUpService(db).fill_conflicts(merge, ["Refunds take 30 days.\n"])
        await _finish_request(db, run, AuthoringStatus.COMPLETED.value)
        await _advance(db, run)
        await _advance(db, run)
        quote = await service.estimate_continuation(ctx, skill.id, run.id, SkillContinue())

        assert (run.status, run.stage) == ("waiting", "filtering")
        assert quote.check_estimate is not None and quote.main_alone_estimate is not None
        assert quote.total_usd == quote.check_estimate.at_most_usd * 2

    async def test_a_failed_proposal_leaves_them_for_a_person(self, db, call_price, monkeypatch):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _diverged(db, ctx, conflict=True)
        run = await _started(db, ctx, skill, fork)
        await _advance(db, run)
        await _advance(db, run)

        await _finish_request(db, run, AuthoringStatus.FAILED.value)
        await _advance(db, run)

        assert (run.status, run.stage) == ("waiting", "filtering")
        with pytest.raises(BadRequestError) as refused:
            await SkillImprovementService(db).estimate_continuation(
                ctx, skill.id, run.id, SkillContinue()
            )
        assert refused.value.details == {"unresolved": 1}
        read = await SkillImprovementService(db).read(ctx, skill.id, run.id)
        assert ("skill.improvement_conflicts_left", "failed") in [
            (event.action, event.reason) for event in read.timeline
        ]

    @pytest.mark.security
    async def test_without_the_budget_for_them_they_wait_for_a_person(
        self, db, call_price, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _diverged(db, ctx, conflict=True)
        run = await _started(db, ctx, skill, fork)
        call_price["price"] = Decimal("5")

        await _advance(db, run)
        await _advance(db, run)

        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=run.organization_id, run_id=run.id, number=1
        )
        assert iteration is not None and iteration.authoring_request_id is None
        assert (run.status, run.stage) == ("waiting", "filtering")


class TestACatchUp:
    async def test_a_limit_too_small_for_the_check_is_raised_at_its_quote(
        self, db, call_price, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx)
        run.budget_usd = Decimal("0.01")
        await db.flush()
        service = SkillImprovementService(db)

        short = await service.estimate_continuation(ctx, skill.id, run.id, SkillContinue())
        lower = await service.estimate_continuation(
            ctx, skill.id, run.id, SkillContinue(budget_usd=Decimal("0.005"))
        )
        raised = await service.estimate_continuation(
            ctx, skill.id, run.id, SkillContinue(budget_usd=Decimal("1"))
        )
        await service.continue_run(
            ctx,
            skill.id,
            run.id,
            SkillContinuationConsent(
                confirmed=True,
                estimate_usd=raised.total_usd,
                candidate_hash=raised.candidate_hash,
                budget_usd=raised.budget_usd,
            ),
        )
        await db.refresh(run)

        assert (short.affordable, short.budget_usd) == (False, Decimal("0.01"))
        assert (lower.affordable, lower.budget_usd) == (False, Decimal("0.01"))
        assert (raised.affordable, raised.budget_usd) == (True, Decimal("1"))
        assert (run.status, run.budget_usd) == ("running", Decimal("1"))

    async def test_it_checks_the_merge_and_main_alone_and_takes_the_merge_in(
        self, db, call_price, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, fork = await _at_changes(db, ctx)

        await _check_now(db, ctx, run)
        await db.refresh(run)
        ready = await _settle(db, run, "no_better", "passed")
        assert ready.status == "ready"
        read = await SkillImprovementService(db).read(ctx, skill.id, run.id)
        applied = await SkillImprovementService(db).apply(
            ctx, skill.id, run.id, SkillImprovementApply(confirmed=True)
        )

        assert [len(files) for files in fake.files] == [1, 1]
        assert read.main_alone == "checked"
        assert read.outcomes == ["catch_up", "return_to_main", "discard"]
        assert (applied.session.status, applied.session.outcome) == ("accepted", "caught_up")
        version = await db.get(SkillVersion, applied.version_id)
        row = await db.get(SkillFork, fork.id)
        assert version is not None and row is not None
        await db.refresh(skill)
        assert version.fork_id == fork.id and version.merged_from_id == skill.latest_version_id
        assert row.base_version_id == skill.latest_version_id
        assert "Refunds take 30 days." in version.content and "brief" in version.content
        decided = [call[1] for call in fake.calls if call[0] == "decided"]
        assert len(decided) == 1 and decided[0][2] == applied.version_id
        assert len([call for call in fake.calls if call[0] == "discard"]) == 1

    async def test_main_alone_off_offers_no_return_and_says_why(self, db, call_price, monkeypatch):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx)

        await _check_now(db, ctx, run, main_alone=False)
        await db.refresh(run)
        await _settle(db, run, "passed")
        read = await SkillImprovementService(db).read(ctx, skill.id, run.id)

        assert len(fake.files) == 1
        assert (read.main_alone, read.outcomes) == ("off", ["catch_up", "discard"])
        with pytest.raises(BadRequestError):
            await SkillImprovementService(db).return_to_main(
                ctx, skill.id, run.id, SkillImprovementReturn(confirmed=True)
            )

    async def test_a_merge_that_is_main_needs_no_main_alone(self, db, call_price, monkeypatch):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _diverged(db, ctx, conflict=True)
        run = await _started(db, ctx, skill, fork)
        await _advance(db, run)
        await _advance(db, run)
        merge = await SkillCatchUpService(db).merge_for_run(
            run.id, organization_id=ctx.organization_id
        )
        assert merge is not None
        await SkillCatchUpService(db).fill_conflicts(merge, ["Refunds take 21 days.\n"])
        await _finish_request(db, run, AuthoringStatus.COMPLETED.value)
        await _advance(db, run)

        await _check_now(db, ctx, run)
        await db.refresh(run)
        await _settle(db, run, "passed")
        read = await SkillImprovementService(db).read(ctx, skill.id, run.id)

        assert len(fake.files) == 1 and read.main_alone == "same"

    async def test_a_merge_that_made_agents_worse_is_not_taken_in(
        self, db, call_price, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        await db.refresh(run)

        await _settle(db, run, "blocked", "blocked")
        read = await SkillImprovementService(db).read(ctx, skill.id, run.id)

        assert read.outcomes == ["discard"]
        with pytest.raises(BadRequestError):
            await SkillImprovementService(db).apply(
                ctx, skill.id, run.id, SkillImprovementApply(confirmed=True)
            )

    @pytest.mark.parametrize("hidden", [False, True])
    async def test_agents_it_could_not_check_are_acknowledged_first(
        self, db, call_price, monkeypatch, hidden
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        await db.refresh(run)
        await _settle(db, run, "passed", "passed")
        _unknown(fake, name="Desk", hidden=hidden)
        service = SkillImprovementService(db)

        with pytest.raises(BadRequestError):
            await service.apply(ctx, skill.id, run.id, SkillImprovementApply(confirmed=True))
        applied = await service.apply(
            ctx,
            skill.id,
            run.id,
            SkillImprovementApply(confirmed=True, acknowledge_unknown=True),
        )

        assert applied.session.outcome == "caught_up"

    async def test_returning_to_main_moves_the_forks_agents_instead(
        self, db, call_price, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _diverged(db, ctx)
        await _serving(db, ctx, "Desk", _spec(skill, fork_id=str(fork.id)))
        run = await _started(db, ctx, skill, fork)
        await _advance(db, run)
        await _advance(db, run)
        await _check_now(db, ctx, run)
        await db.refresh(run)
        await _settle(db, run, "passed", "no_better")

        returned = await SkillImprovementService(db).return_to_main(
            ctx, skill.id, run.id, SkillImprovementReturn(confirmed=True)
        )

        assert (returned.session.status, returned.session.outcome) == (
            "accepted",
            "returned_to_main",
        )
        assert [item.agent.name for item in returned.returned.agents] == ["Desk"]
        assert len([call for call in fake.calls if call[0] == "discard"]) == 2

    async def test_a_return_that_moves_nobody_leaves_the_session_and_its_checks(
        self, db, call_price, monkeypatch
    ):
        """A fork read only through a specialist is changed in the Builder: nothing moved."""
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _diverged(db, ctx)
        await _serving(
            db, ctx, "Desk", _with_specialist({"name": "Desk"}, skill, fork_id=str(fork.id))
        )
        run = await _started(db, ctx, skill, fork)
        await _advance(db, run)
        await _advance(db, run)
        await _check_now(db, ctx, run)
        await db.refresh(run)
        await _settle(db, run, "passed", "no_better")

        with pytest.raises(BadRequestError) as refused:
            await SkillImprovementService(db).return_to_main(
                ctx, skill.id, run.id, SkillImprovementReturn(confirmed=True)
            )

        assert [item["name"] for item in refused.value.details["agents"]] == ["Desk"]
        assert not [call for call in fake.calls if call[0] == "discard"]
        read = await SkillImprovementService(db).read(ctx, skill.id, run.id)
        assert (read.status, read.outcome) == ("ready", None)

    @pytest.mark.parametrize("hidden", [False, True])
    async def test_agents_main_alone_could_not_check_are_acknowledged_before_returning(
        self, db, call_price, monkeypatch, hidden
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _diverged(db, ctx)
        await _serving(db, ctx, "Desk", _spec(skill, fork_id=str(fork.id)))
        run = await _started(db, ctx, skill, fork)
        await _advance(db, run)
        await _advance(db, run)
        await _check_now(db, ctx, run)
        await db.refresh(run)
        await _settle(db, run, "passed", "needs_ack")
        _unknown(fake, name="Shop", hidden=hidden)
        service = SkillImprovementService(db)

        with pytest.raises(BadRequestError) as refused:
            await service.return_to_main(
                ctx, skill.id, run.id, SkillImprovementReturn(confirmed=True)
            )
        returned = await service.return_to_main(
            ctx,
            skill.id,
            run.id,
            SkillImprovementReturn(confirmed=True, acknowledge_unknown=True),
        )

        assert refused.value.details["fields"][0]["field"] == "acknowledge_unknown"
        assert returned.session.outcome == "returned_to_main"

    async def test_a_retry_keeps_a_finished_check_of_main_alone(self, db, call_price, monkeypatch):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        await db.refresh(run)
        kept = await _alone_id(db, run)

        failed = await _settle(db, run, None, "passed")
        assert (failed.status, failed.stage) == ("failed", "evaluating")
        retried = await SkillImprovementService(db).retry(ctx, skill.id, run.id)

        assert (retried.status, retried.stage) == ("running", "evaluating")
        assert len(fake.files) == 3 and await _alone_id(db, run) == kept

    async def test_a_kept_check_of_main_alone_is_paid_for_once(self, db, call_price, monkeypatch):
        """Its cost went into the attempt when the failed check was judged."""
        _checked(db, monkeypatch)

        async def cost(*_args: object, **_kwargs: object) -> Decimal:
            return Decimal("0.10")

        monkeypatch.setattr(skill_improvement_repo, "check_cost", cost)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        await db.refresh(run)
        await _settle(db, run, None, "passed")
        kept = await db.get(SkillCheck, await _alone_id(db, run))
        assert kept is not None
        # The retry runs in a later transaction than the checks it keeps.
        kept.created_at -= timedelta(minutes=1)
        await db.flush()
        await SkillImprovementService(db).retry(ctx, skill.id, run.id)

        await _settle(db, run, "passed", "passed")

        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=run.organization_id, run_id=run.id, number=run.iteration
        )
        assert iteration is not None and iteration.cost_usd == Decimal("0.30")

    async def test_a_retry_checks_main_alone_again_when_it_failed_too(
        self, db, call_price, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        await db.refresh(run)
        first = await _alone_id(db, run)

        await _settle(db, run, None, None)
        await SkillImprovementService(db).retry(ctx, skill.id, run.id)

        assert len(fake.files) == 4 and await _alone_id(db, run) not in (None, first)


class TestAMoveToMain:
    async def test_main_takes_the_merge_in_from_the_fork(self, db, call_price, monkeypatch):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx, TO_MAIN)

        await _check_now(db, ctx, run)
        await db.refresh(run)
        await _settle(db, run, "passed")
        read = await SkillImprovementService(db).read(ctx, skill.id, run.id)
        applied = await SkillImprovementService(db).apply(
            ctx, skill.id, run.id, SkillImprovementApply(confirmed=True)
        )

        merge = await SkillCatchUpService(db).merge_for_run(
            run.id, organization_id=ctx.organization_id
        )
        assert merge is not None
        assert len(fake.files) == 1 and read.main_alone is None
        assert read.outcomes == ["apply", "discard"]
        assert fake.merged_from == [merge.fork_version_id]
        assert applied.session.outcome == "applied"

    async def test_a_fork_edit_committed_meanwhile_refuses_taking_the_merge_in(
        self, db, call_price, monkeypatch
    ):
        """The fork is read again under its lock: an edit another transaction committed
        after this one first read the fork is seen, and main does not take in an old merge."""
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx, TO_MAIN)
        await _check_now(db, ctx, run)
        await db.refresh(run)
        await _settle(db, run, "passed")
        merge = await SkillCatchUpService(db).merge_for_run(
            run.id, organization_id=ctx.organization_id
        )
        assert merge is not None
        read_before = await skill_version_repo.get_fork(
            db, merge.fork_id, organization_id=ctx.organization_id, skill_id=skill.id
        )
        await db.execute(
            text("UPDATE skill_forks SET latest_version_id = :other WHERE id = :fork"),
            {"other": merge.main_version_id, "fork": merge.fork_id},
        )

        with pytest.raises(ConcurrentChangeError, match="The fork changed"):
            await SkillImprovementService(db).apply(
                ctx, skill.id, run.id, SkillImprovementApply(confirmed=True)
            )
        assert read_before is not None

    async def test_a_limit_raised_at_the_quote_is_the_limit_it_keeps(
        self, db, call_price, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx, TO_MAIN)
        raised = run.budget_usd + Decimal("0.01")
        service = SkillImprovementService(db)

        quote = await service.estimate_continuation(
            ctx, skill.id, run.id, SkillContinue(budget_usd=raised)
        )
        await service.continue_run(
            ctx,
            skill.id,
            run.id,
            SkillContinuationConsent(
                confirmed=True,
                estimate_usd=quote.total_usd,
                candidate_hash=quote.candidate_hash,
                budget_usd=quote.budget_usd,
            ),
        )
        await db.refresh(run)

        assert quote.budget_usd == raised
        assert run.budget_usd == raised

    async def test_one_that_helped_nobody_waits_at_its_result(self, db, call_price, monkeypatch):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, _, _ = await _at_changes(db, ctx, TO_MAIN)
        await _check_now(db, ctx, run)
        await db.refresh(run)

        ready = await _settle(db, run, "no_better")

        assert (ready.status, ready.stop_reason) == ("ready", None)


class TestWhatAMergeIsNot:
    async def test_it_is_not_made_a_fork_checked_again_or_given_a_note(
        self, db, call_price, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx)
        service = SkillImprovementService(db)
        quote = await service.estimate_continuation(ctx, skill.id, run.id, SkillContinue())

        with pytest.raises(BadRequestError):
            await service.continue_run(
                ctx,
                skill.id,
                run.id,
                SkillContinuationConsent(
                    confirmed=True,
                    estimate_usd=quote.total_usd,
                    candidate_hash=quote.candidate_hash,
                    budget_usd=run.budget_usd,
                    note="Keep it short",
                ),
            )
        with pytest.raises(BadRequestError):
            await service.estimate_recheck(ctx, skill.id, run.id, SkillContinue())
        with pytest.raises(BadRequestError):
            await service.fork(
                ctx, skill.id, run.id, SkillImprovementFork(confirmed=True, name="Other")
            )
        with pytest.raises(ConcurrentChangeError):
            await service.return_to_main(
                ctx, skill.id, run.id, SkillImprovementReturn(confirmed=True)
            )
        read = await service.read(ctx, skill.id, run.id)
        assert read.can_restart is False

    async def test_a_move_to_main_returns_nobody(self, db, call_price, monkeypatch):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx, TO_MAIN)

        with pytest.raises(BadRequestError):
            await SkillImprovementService(db).return_to_main(
                ctx, skill.id, run.id, SkillImprovementReturn(confirmed=True)
            )

    async def test_a_step_off_changes_is_refused(self, db, call_price, monkeypatch):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _diverged(db, ctx)
        run = await _started(db, ctx, skill, fork)

        with pytest.raises(BadRequestError):
            await SkillImprovementService(db).estimate_continuation(
                ctx, skill.id, run.id, SkillContinue()
            )


class TestAMergeOverTaken:
    async def test_main_moving_on_ends_it_and_says_to_start_again(
        self, db, call_price, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx)
        await SkillService(db).update(ctx, skill.id, SkillUpdate(content="Newest main."))
        service = SkillImprovementService(db)

        read = await service.read(ctx, skill.id, run.id)
        with pytest.raises(ConcurrentChangeError) as refused:
            await service.estimate_continuation(ctx, skill.id, run.id, SkillContinue())
        ended = await service.sweep()
        await db.refresh(run)

        assert read.stale
        assert refused.value.code == "LINE_MOVED"
        assert refused.value.message == (
            "Main changed while you were catching up. Start again to include it."
        )
        assert ended >= 1 and (run.status, run.stop_reason) == ("stale", "stale")

    async def test_the_fork_moving_on_ends_it_while_it_works(self, db, call_price, monkeypatch):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _diverged(db, ctx)
        run = await _started(db, ctx, skill, fork, TO_MAIN)
        await _fork_moves_on(db, ctx, skill, fork)

        await _advance(db, run)

        assert (run.status, run.stop_reason) == ("stale", "stale")

    async def test_accepting_after_the_fork_moved_is_refused(self, db, call_price, monkeypatch):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, fork = await _at_changes(db, ctx, TO_MAIN)
        await _check_now(db, ctx, run)
        await db.refresh(run)
        await _settle(db, run, "passed")
        await _fork_moves_on(db, ctx, skill, fork)

        with pytest.raises(ConcurrentChangeError) as refused:
            await SkillImprovementService(db).apply(
                ctx, skill.id, run.id, SkillImprovementApply(confirmed=True)
            )

        assert refused.value.message == (
            "The fork changed while you were moving the fork to main. Start again to include it."
        )

    async def test_cancelling_stops_both_checks(self, db, call_price, monkeypatch):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)

        cancelled = await SkillImprovementService(db).cancel(ctx, skill.id, run.id)

        assert cancelled.status == ImprovementStatus.CANCELLED
        assert len([call for call in fake.calls if call[0] == "cancel"]) == 2


async def _fork_moves_on(
    db: AsyncSession, ctx: AuthContext, skill: Skill, fork: SkillForkRead
) -> None:
    row = await db.get(SkillFork, fork.id)
    assert row is not None
    latest = SkillVersionService.line_latest(skill, row)
    assert latest is not None
    await SkillVersionService(db).edit(
        ctx,
        skill.id,
        SkillVersionCreate(
            fork_id=fork.id,
            base_version_id=latest,
            description=skill.description,
            content="The fork's newest text.",
        ),
    )


class TestTheEdgesOfAMerge:
    async def test_a_catch_up_checked_without_main_alone_is_taken_in(
        self, db, call_price, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx)
        await _check_now(db, ctx, run, main_alone=False)
        await db.refresh(run)
        await _settle(db, run, "passed")

        applied = await SkillImprovementService(db).apply(
            ctx, skill.id, run.id, SkillImprovementApply(confirmed=True)
        )

        assert applied.session.outcome == "caught_up"
        assert [call for call in fake.calls if call[0] == "discard"] == []

    async def test_the_sweep_leaves_a_merge_nobody_overtook(self, db, call_price, monkeypatch):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, _, _ = await _at_changes(db, ctx)

        await SkillImprovementService(db).sweep()
        await db.refresh(run)

        assert (run.status, run.stage) == ("waiting", "filtering")

    async def test_the_conflicts_request_is_waited_on_while_it_runs(
        self, db, call_price, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _diverged(db, ctx, conflict=True)
        run = await _started(db, ctx, skill, fork)
        await _advance(db, run)
        await _advance(db, run)

        await _advance(db, run)

        assert (run.status, run.stage) == ("running", "proposing")

    @pytest.mark.security
    async def test_a_check_quoted_before_a_change_or_past_the_budget_is_refused(
        self, db, call_price, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx)
        service = SkillImprovementService(db)
        quote = await service.estimate_continuation(ctx, skill.id, run.id, SkillContinue())

        def consent(**values: Any) -> SkillContinuationConsent:
            return SkillContinuationConsent(
                **{
                    "confirmed": True,
                    "estimate_usd": quote.total_usd,
                    "candidate_hash": quote.candidate_hash,
                    "budget_usd": Decimal("0.01"),
                    **values,
                }
            )

        fake.price = Decimal("0.90")
        with pytest.raises(ConcurrentChangeError):
            await service.continue_run(ctx, skill.id, run.id, consent())
        fake.price = Decimal("5")
        dearer = await service.estimate_continuation(ctx, skill.id, run.id, SkillContinue())
        with pytest.raises(PaymentRequiredError):
            await service.continue_run(
                ctx,
                skill.id,
                run.id,
                consent(estimate_usd=dearer.total_usd, candidate_hash=dearer.candidate_hash),
            )

    @pytest.mark.security
    async def test_a_retry_past_the_budget_is_refused(self, db, call_price, monkeypatch):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        await db.refresh(run)
        await _settle(db, run, None, "passed")
        fake.price = Decimal("5")

        with pytest.raises(PaymentRequiredError):
            await SkillImprovementService(db).retry(ctx, skill.id, run.id)


@pytest.mark.usefixtures("_environment")
async def test_the_conflicts_call_is_priced_as_one_improver_call(db):
    ctx = await _owner(db)
    await _improver(db, ctx)

    priced = await AuthoringService(db).estimate_call(ctx, chars=4000)

    assert (priced.calls, priced.runs, priced.reason) == (1, 0, None)
    assert priced.estimate_usd > 0 and priced.affordable


async def _alone_id(db: AsyncSession, run: SkillImprovementRun) -> uuid.UUID | None:
    iteration = await skill_improvement_repo.get_iteration(
        db, organization_id=run.organization_id, run_id=run.id, number=run.iteration
    )
    assert iteration is not None
    await db.refresh(iteration)
    return iteration.main_alone_check_id


async def _caught_up_and_ready(
    db: AsyncSession, ctx: AuthContext
) -> tuple[SkillImprovementRun, Skill, SkillForkRead]:
    run, skill, fork = await _at_changes(db, ctx)
    await _check_now(db, ctx, run)
    await db.refresh(run)
    await _settle(db, run, "passed", "passed")
    return run, skill, fork


class TestReviewFixes:
    @pytest.mark.security
    async def test_a_result_main_moved_past_offers_only_discard_and_moves_nobody(
        self, db, call_price, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _caught_up_and_ready(db, ctx)
        await SkillService(db).update(ctx, skill.id, SkillUpdate(content="Newest main."))
        service = SkillImprovementService(db)

        read = await service.read(ctx, skill.id, run.id)
        with pytest.raises(ConcurrentChangeError) as returned:
            await service.return_to_main(
                ctx, skill.id, run.id, SkillImprovementReturn(confirmed=True)
            )
        with pytest.raises(ConcurrentChangeError) as taken:
            await service.apply(ctx, skill.id, run.id, SkillImprovementApply(confirmed=True))

        assert read.stale and read.outcomes == ["discard"]
        assert returned.value.code == taken.value.code == "LINE_MOVED"

    @pytest.mark.security
    async def test_a_line_whose_agents_changed_since_the_check_is_refused(
        self, db, call_price, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, skill, _ = await _caught_up_and_ready(db, ctx)
        fake.drift = ConcurrentChangeError(message="The line's agents changed since the check")
        service = SkillImprovementService(db)

        with pytest.raises(ConcurrentChangeError):
            await service.apply(ctx, skill.id, run.id, SkillImprovementApply(confirmed=True))
        with pytest.raises(ConcurrentChangeError):
            await service.return_to_main(
                ctx, skill.id, run.id, SkillImprovementReturn(confirmed=True)
            )

        await db.refresh(run)
        assert run.status == "ready" and run.outcome is None

    async def test_a_merged_description_past_its_limit_waits_for_a_person(
        self, db, call_price, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _described(db, ctx)
        run = await _started(db, ctx, skill, fork)
        await _advance(db, run)
        await _advance(db, run)
        merge = await SkillCatchUpService(db).merge_for_run(
            run.id, organization_id=ctx.organization_id
        )
        assert merge is not None and merge.conflicts == 1
        await SkillCatchUpService(db).fill_conflicts(merge, ["x" * 700])
        await _finish_request(db, run, AuthoringStatus.COMPLETED.value)
        await _advance(db, run)

        with pytest.raises(BadRequestError) as refused:
            await SkillImprovementService(db).estimate_continuation(
                ctx, skill.id, run.id, SkillContinue()
            )

        assert refused.value.details == {"unresolved": 1}
        assert merge.description["result"] is None

    async def test_both_checks_lead_back_to_the_session(self, db, call_price, monkeypatch):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run, _, _ = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        await db.refresh(run)
        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=run.organization_id, run_id=run.id, number=1
        )
        assert iteration is not None and iteration.main_alone_check_id is not None
        assert iteration.skill_check_id is not None

        found = await skill_improvement_repo.iteration_for_check(
            db, iteration.main_alone_check_id, organization_id=run.organization_id
        )
        sessions = await skill_improvement_repo.sessions_of_checks(
            db,
            [iteration.skill_check_id, iteration.main_alone_check_id],
            organization_id=run.organization_id,
        )

        assert found is not None and found.id == iteration.id
        assert sessions == {
            iteration.skill_check_id: run.id,
            iteration.main_alone_check_id: run.id,
        }

    async def test_conflicts_left_to_a_person_say_why_on_the_timeline(
        self, db, call_price, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill, fork = await _diverged(db, ctx, conflict=True)
        run = await _started(db, ctx, skill, fork)
        call_price["price"] = Decimal("5")
        await _advance(db, run)
        await _advance(db, run)

        read = await SkillImprovementService(db).read(ctx, skill.id, run.id)

        assert [
            (event.action, event.reason)
            for event in read.timeline
            if event.action.endswith("conflicts_left")
        ] == [("skill.improvement_conflicts_left", "budget")]


async def _described(db: AsyncSession, ctx: AuthContext) -> tuple[Skill, SkillForkRead]:
    """A skill whose fork and main each reworded its description differently."""
    skill = await SkillService(db).create(
        ctx,
        name=f"refunds-{uuid.uuid4().hex[:6]}",
        description="How refunds work.",
        content=_BODY,
        visibility=Visibility.ORG,
    )
    fork = await _fork(db, ctx, skill)
    await SkillVersionService(db).edit(
        ctx,
        skill.id,
        SkillVersionCreate(
            fork_id=fork.id,
            base_version_id=fork.base.id,
            description="How refunds and returns work.",
            content=_BODY,
        ),
    )
    await SkillService(db).update(ctx, skill.id, SkillUpdate(description="How refunds are paid."))
    await db.refresh(skill)
    return skill, fork
