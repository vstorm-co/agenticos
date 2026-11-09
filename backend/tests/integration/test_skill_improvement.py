"""A session on one line of a skill, step by step, against a real database.

What the improver reads and costs is fixed here - the evidence of a line and the
price of reading it - so each step's move is the service's own: queuing the
analysis, stopping at Understand, proposing, filtering to Changes, and every
refusal on the way.
"""

import asyncio
import contextlib
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
    PaymentRequiredError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.authoring import AuthoringRequest, AuthoringStatus, HunkKind
from app.db.models.organization import OrganizationMember
from app.db.models.skill import Skill
from app.db.models.skill_check import (
    AgentState,
    CheckMode,
    CheckOutcome,
    CheckSource,
    CheckStatus,
    CheckVerdict,
    SkillCheck,
    SkillCheckAgent,
)
from app.db.models.skill_improvement import SkillImprovementRun
from app.repositories import (
    authoring_repo,
    skill_check_repo,
    skill_improvement_repo,
    skill_repo,
    skill_version_repo,
)
from app.schemas.authoring import AuthoringEstimate, InstructionChange
from app.schemas.improvement import ChangeEdit, ImprovementDiscard, ImprovementSelection
from app.schemas.skill import SkillUpdate
from app.schemas.skill_check import (
    AgentRef,
    CandidateText,
    LineRef,
    SkillCheckAgentRead,
    SkillCheckApply,
    SkillCheckEstimate,
    SkillCheckFork,
    SkillCheckRead,
    SkillCheckStart,
)
from app.schemas.skill_improvement import (
    SkillContinuationConsent,
    SkillContinue,
    SkillImprovementApply,
    SkillImprovementFork,
    SkillImprovementRead,
    SkillImprovementStart,
    SkillImprovementTarget,
)
from app.schemas.skill_version import SkillForkRead, VersionNumberRef, VersionRef
from app.services import authoring_hunks
from app.services.authoring import AuthoringService
from app.services.authoring_evidence import EvidencePack, PackedRun
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.improvement_skills import SkillSeed
from app.services.personal_data import PersonalDataService
from app.services.skill_agents import SkillAgentService
from app.services.skill_check import SkillCheckService
from app.services.skill_improvement import SkillImprovementService
from app.services.skill_versions import SkillVersionService
from app.services.skills import SkillService
from tests.integration.test_authoring import _member, _owner, _published, _rated
from tests.integration.test_skill_bindings import (
    _fork,
    _serving,
    _skill,
    _spec,
    _waiting_for_a_lock,
)

pytestmark = pytest.mark.anyio

_PRICE = Decimal("0.05")
_CONVERSATION = uuid.uuid4()
_BODY = "Refunds take 14 days.\nAlways ask for the order number.\nBe polite."


def _packed(run_id: uuid.UUID | None = None) -> PackedRun:
    return PackedRun(
        run_id=run_id or uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        status="completed",
        rating=-1,
        comments=["Wrong: refunds take 30 days"],
        prompt="How long do refunds take?",
        answer="Refunds take 14 days.",
        calls=[],
        error=None,
        skill_use="used",
    )


@pytest.fixture
def evidence(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The line's evidence and its price, as each test sets them."""
    return fixed_evidence(monkeypatch)


def fixed_evidence(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Fix what a line's evidence holds and what reading it costs; returns the knobs."""
    state: dict[str, Any] = {"runs": [_packed()], "affordable": True, "price": _PRICE}

    async def pack(self, ctx, line, window_days):
        state["versions_read"] = line
        return EvidencePack(runs=list(state["runs"]), unknown_runs=2)

    async def priced(self, ctx, pack, *, improver_agent_id=None):
        state.setdefault("helpers", []).append(improver_agent_id)
        return AuthoringEstimate(
            runs=len(pack.runs),
            rated_down=len(pack.runs),
            calls=1,
            estimate_usd=state["price"],
            affordable=state["affordable"],
            reason=None if pack.runs else "no_evidence",
        )

    monkeypatch.setattr(SkillImprovementService, "_evidence", pack)
    monkeypatch.setattr(AuthoringService, "estimate_pack", priced)
    return state


async def _skill_on_main(db: AsyncSession, ctx: AuthContext) -> Skill:
    skill = await _skill(db, ctx, f"refunds-{uuid.uuid4().hex[:6]}")
    await SkillService(db).update(ctx, skill.id, SkillUpdate(content=_BODY))
    await _serving(db, ctx, "Clerk", _spec(skill))
    return skill


def _start(**values: Any) -> SkillImprovementStart:
    return SkillImprovementStart(budget_usd=Decimal("1"), **values)


async def _row(db: AsyncSession, read: SkillImprovementRead) -> SkillImprovementRun:
    run = await db.get(SkillImprovementRun, read.id)
    assert run is not None
    await db.refresh(run)
    return run


async def _finish(db: AsyncSession, request_id: uuid.UUID, report: dict[str, Any]) -> None:
    request = await db.get(AuthoringRequest, request_id)
    assert request is not None
    request.status = AuthoringStatus.COMPLETED.value
    request.report = report
    request.cost_usd = Decimal("0.02")
    request.finished_at = datetime.now(UTC)
    await db.flush()


async def _at_understand(
    db: AsyncSession, ctx: AuthContext, skill: Skill, run_ids: list[str] | None = None
) -> SkillImprovementRun:
    service = SkillImprovementService(db)
    read = await service.start(ctx, skill.id, _start())
    await service.advance(read.id, ctx.organization_id)
    run = await _row(db, read)
    assert run.analysis_request_id is not None
    await _finish(
        db,
        run.analysis_request_id,
        {
            "problems": [
                {
                    "title": "Wrong refund window",
                    "summary": "The skill says 14 days; the policy is 30.",
                    "cause": "skill",
                    "run_ids": run_ids or [],
                    "evidence": [],
                },
                {"title": "Rude", "summary": "", "cause": "not_the_skill", "run_ids": []},
            ],
            "usage_unknown": 2,
        },
    )
    await service.advance(read.id, ctx.organization_id)
    return await _row(db, read)


async def _propose(
    db: AsyncSession, ctx: AuthContext, run: SkillImprovementRun, changes: list[dict[str, Any]]
) -> None:
    """Take the next step, and answer its proposal with these edits."""
    service = SkillImprovementService(db)
    quote = await service.estimate_continuation(ctx, run.skill_id, run.id, SkillContinue())
    await service.continue_run(
        ctx,
        run.skill_id,
        run.id,
        SkillContinuationConsent(
            confirmed=True,
            estimate_usd=quote.total_usd,
            candidate_hash=quote.candidate_hash,
            budget_usd=run.budget_usd,
        ),
    )
    await service.advance(run.id, ctx.organization_id)
    iteration = await skill_improvement_repo.get_iteration(
        db, organization_id=ctx.organization_id, run_id=run.id, number=run.iteration
    )
    assert iteration is not None and iteration.authoring_request_id is not None
    request = await db.get(AuthoringRequest, iteration.authoring_request_id)
    assert request is not None
    batch = await authoring_repo.create_skill_batch(
        db,
        organization_id=ctx.organization_id,
        skill_id=run.skill_id,
        fork_id=run.fork_id,
        base_skill_version_id=run.base_version_id,
        skill_improvement_run_id=run.id,
        request_id=request.id,
        source_started_at=request.created_at,
        expected_effect="Right refund window",
        evidence_conversation_ids=[_CONVERSATION],
    )
    await authoring_repo.add_hunks(
        db, organization_id=ctx.organization_id, batch_id=batch.id, hunks=changes
    )
    await _finish(db, request.id, {"summary": "", "expected_effect": ""})
    await service.advance(run.id, ctx.organization_id)
    await service.advance(run.id, ctx.organization_id)


def _body_edit(old: str, new: str) -> dict[str, Any]:
    columns = authoring_hunks.anchor_change(
        _BODY, InstructionChange(old_text=old, new_text=new, rationale="Policy")
    )
    assert isinstance(columns, dict)
    return {
        **columns,
        "kind": HunkKind.SKILL_BODY.value,
        "origin": "improve",
        "rationale": "Policy",
        "evidence": [],
        "evidence_dropped": 0,
    }


def _description(new: str) -> dict[str, Any]:
    return {
        "kind": HunkKind.SKILL_DESCRIPTION.value,
        "origin": "improve",
        "base_description": "How refunds work.",
        "new_description": new,
        "rationale": "Opened for returns too",
        "evidence": [],
        "evidence_dropped": 0,
    }


class TestEstimateAndStart:
    async def test_the_estimate_names_the_line_its_base_and_the_agents_it_serves(
        self, db, evidence
    ):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        await _published(db, ctx, name="Drafting", spec=_spec(skill))

        quote = await SkillImprovementService(db).estimate(ctx, skill.id, SkillImprovementTarget())

        assert (quote.line.fork_id, quote.line.name) == (None, "main")
        assert quote.base_version.id == skill.latest_version_id
        assert (quote.agents, quote.hidden_agents) == (1, 0)
        assert (quote.total_usd, quote.proposal_usd) == (_PRICE, _PRICE * 2)
        assert (quote.evidence_runs, quote.usage_unknown, quote.reason) == (1, 2, None)

    async def test_an_attempt_is_priced_with_a_quick_check_of_the_line_as_it_is(
        self, db, evidence, monkeypatch
    ):
        """A spending limit made from it leaves room for each attempt's check."""
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)

        quote = await SkillImprovementService(db).estimate(ctx, skill.id, SkillImprovementTarget())

        assert (quote.check_usd, quote.per_round_usd) == (fake.price, _PRICE + fake.price)
        [(_, priced)] = fake.calls
        assert (priced.candidate.content, priced.mode) == (skill.content, CheckMode.QUICK)
        assert fake.excluded == [[run.conversation_id for run in evidence["runs"]]]

    async def test_a_line_holds_one_open_session_and_main_counts_as_one_line(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        fork = await _fork(db, ctx, skill, "fork text")
        service = SkillImprovementService(db)

        first = await service.start(ctx, skill.id, _start())
        on_fork = await service.start(ctx, skill.id, _start(fork_id=fork.id))
        with pytest.raises(AlreadyExistsError):
            await service.start(ctx, skill.id, _start())

        assert (first.status, first.line_name, first.iteration) == ("queued", "main", 1)
        assert (on_fork.fork_id, on_fork.line_name) == (fork.id, "returns")

    async def test_a_session_on_a_fork_reads_its_line_and_counts_its_agents(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        fork = await _fork(db, ctx, skill, "fork text")
        await _serving(db, ctx, "Returns", _spec(skill, fork_id=str(fork.id)))

        quote = await SkillImprovementService(db).estimate(
            ctx, skill.id, SkillImprovementTarget(fork_id=fork.id)
        )

        assert (quote.line.name, quote.agents) == ("returns", 1)
        assert evidence["versions_read"].fork.id == fork.id

    @pytest.mark.security
    async def test_nothing_to_learn_from_and_a_short_budget_are_refused(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        service = SkillImprovementService(db)

        evidence["runs"] = []
        with pytest.raises(BadRequestError):
            await service.start(ctx, skill.id, _start())
        evidence["runs"] = [_packed()]
        with pytest.raises(PaymentRequiredError):
            await service.start(ctx, skill.id, SkillImprovementStart(budget_usd=Decimal("0.01")))
        evidence["affordable"] = False
        with pytest.raises(PaymentRequiredError):
            await service.start(ctx, skill.id, _start())

    async def test_an_archived_fork_and_another_skills_fork_are_refused_on_fork_id(
        self, db, evidence
    ):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        other = await _skill(db, ctx, "invoices")
        foreign = await _fork(db, ctx, other)
        fork = await _fork(db, ctx, skill, "fork text")
        await SkillVersionService(db).archive_fork(ctx, skill.id, fork.id)
        service = SkillImprovementService(db)

        with pytest.raises(BadRequestError) as archived:
            await service.start(ctx, skill.id, _start(fork_id=fork.id))
        with pytest.raises(BadRequestError) as elsewhere:
            await service.estimate(ctx, skill.id, SkillImprovementTarget(fork_id=foreign.id))

        assert archived.value.details["fields"][0]["field"] == "fork_id"
        assert elsewhere.value.details["fields"][0]["field"] == "fork_id"


class TestWhoMay:
    async def test_another_organizations_skill_and_session_are_not_found(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        read = await SkillImprovementService(db).start(ctx, skill.id, _start())
        stranger = await _owner(db)
        service = SkillImprovementService(db)

        with pytest.raises(NotFoundError):
            await service.estimate(stranger, skill.id, SkillImprovementTarget())
        with pytest.raises(NotFoundError):
            await service.read(stranger, skill.id, read.id)
        other = await _skill_on_main(db, stranger)
        with pytest.raises(NotFoundError):
            await service.read(stranger, other.id, read.id)

    async def test_starting_needs_edit_access_and_runs_view(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        service = SkillImprovementService(db)

        with pytest.raises(AuthorizationError):
            await service.estimate(
                _narrowed(ctx, Perm.SKILLS_VIEW, Perm.SKILLS_EDIT),
                skill.id,
                SkillImprovementTarget(),
            )
        with pytest.raises(NotFoundError):
            await service.estimate(
                _narrowed(ctx, Perm.SKILLS_VIEW, Perm.RUNS_VIEW), skill.id, SkillImprovementTarget()
            )

    async def test_a_reader_without_edit_access_may_read_but_not_take_a_step(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)
        reader = _narrowed(ctx, Perm.SKILLS_VIEW, Perm.RUNS_VIEW, Perm.AGENTS_VIEW)
        service = SkillImprovementService(db)

        read = await service.read(reader, skill.id, run.id)

        assert read.status == "waiting"
        with pytest.raises(AuthorizationError):
            await service.cancel(reader, skill.id, run.id)
        with pytest.raises(AuthorizationError):
            await service.read(_narrowed(ctx, Perm.SKILLS_VIEW), skill.id, run.id)


def _narrowed(ctx: AuthContext, *perms: Perm) -> AuthContext:
    """The owner acting through a key issued for these permissions only."""
    return replace(ctx, key_scopes=frozenset(perms))


class TestSteps:
    async def test_a_session_groups_the_problems_and_stops_at_understand(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        agent_run = await _agent_run(db, ctx, skill)

        run = await _at_understand(db, ctx, skill, [str(agent_run.id)])
        service = SkillImprovementService(db)
        read = await service.read(ctx, skill.id, run.id)
        problems = await service.problems(ctx, skill.id, run.id)

        assert (run.status, run.stage) == ("waiting", "classifying")
        assert read.next_step == "propose" and read.expires_at is not None
        assert [problem.title for problem in problems.problems] == ["Wrong refund window"]
        assert [(agent.name, agent.runs) for agent in problems.problems[0].agents] == [("Clerk", 1)]
        assert (problems.not_the_skill, problems.usage_unknown) == (1, 2)
        assert [event.action for event in read.timeline][:2] == [
            "skill.improvement_started",
            "skill.improvement_child_started",
        ]

    async def test_an_agent_the_reader_may_not_see_is_counted_not_named(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        agent_run = await _agent_run(db, ctx, skill)
        run = await _at_understand(db, ctx, skill, [str(agent_run.id)])
        reader = _narrowed(ctx, Perm.SKILLS_VIEW, Perm.RUNS_VIEW)

        [problem] = (await SkillImprovementService(db).problems(reader, skill.id, run.id)).problems

        assert (problem.agents, problem.hidden_agents) == ([], 1)

    async def test_proposed_edits_are_filtered_to_changes_and_measured_as_chosen(
        self, db, evidence
    ):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)

        await _propose(
            db,
            ctx,
            run,
            [
                _body_edit("Refunds take 14 days.", "Refunds take 30 days."),
                _body_edit("Refunds take 14 days.", "Refunds take 30 days."),
                _body_edit("Refunds take 14 days.", "Refunds take 60 days."),
                _description("How refunds and returns work."),
                _description("Something else."),
            ],
        )
        run = await _row(db, SkillImprovementRead.model_validate(run))
        service = SkillImprovementService(db)
        read = await service.read(ctx, skill.id, run.id)
        changes = await service.changes(ctx, skill.id, run.id)
        [attempt] = read.iterations

        assert (run.status, run.stage, read.next_step) == ("waiting", "filtering", "check")
        assert len(changes) == 5 and all(change.applies for change in changes)
        assert [change.kind for change in changes].count("skill_description") == 2
        assert sorted(item["reason"] for item in attempt.dropped) == [
            "overlaps",
            "repeated",
            "repeated",
        ]
        assert attempt.description_changed and attempt.candidate_spec_hash is not None

        body = next(change for change in changes if change.kind == "skill_body")
        reworded = await service.edit_change(
            ctx, skill.id, run.id, body.id, ChangeEdit(edited_text="Refunds take 30 calendar days.")
        )
        chosen = await service.choose_changes(
            ctx, skill.id, run.id, ImprovementSelection(hunk_ids=[body.id])
        )

        assert reworded.edited_text == "Refunds take 30 calendar days."
        [measured] = chosen.iterations
        assert measured.included_hunk_ids == [body.id] and not measured.description_changed
        assert measured.candidate_spec_hash != attempt.candidate_spec_hash

    async def test_changes_are_chosen_only_among_the_attempts_own_while_it_waits(
        self, db, evidence
    ):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)
        service = SkillImprovementService(db)

        with pytest.raises(BadRequestError):
            await service.choose_changes(
                ctx, skill.id, run.id, ImprovementSelection(hunk_ids=[uuid.uuid4()])
            )
        await _propose(db, ctx, run, [_body_edit("Be polite.", "Be kind.")])
        with pytest.raises(BadRequestError):
            await service.choose_changes(
                ctx, skill.id, run.id, ImprovementSelection(hunk_ids=[uuid.uuid4()])
            )
        with pytest.raises(NotFoundError):
            await service.edit_change(
                ctx, skill.id, run.id, uuid.uuid4(), ChangeEdit(edited_text="x")
            )
        with pytest.raises(NotFoundError):
            await service.changes(ctx, skill.id, run.id, attempt=4)

    async def test_a_proposal_with_no_edit_stops_the_session(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)

        await _propose(db, ctx, run, [])
        run = await _row(db, SkillImprovementRead.model_validate(run))

        assert (run.status, run.stage, run.stop_reason) == ("stopped", "proposing", "no_proposal")

    async def test_try_again_carries_a_note_into_a_new_attempt(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)
        await _propose(db, ctx, run, [])
        service = SkillImprovementService(db)

        quote = await service.estimate_continuation(ctx, skill.id, run.id, SkillContinue())
        read = await service.continue_run(
            ctx,
            skill.id,
            run.id,
            SkillContinuationConsent(
                confirmed=True,
                estimate_usd=quote.total_usd,
                candidate_hash=quote.candidate_hash,
                budget_usd=Decimal("2"),
                note="Keep the order number rule",
            ),
        )

        assert (quote.mode, quote.number) == ("next_round", 2)
        assert (read.iteration, read.status, read.stage) == (2, "running", "proposing")
        assert read.iterations[-1].note == "Keep the order number rule"
        assert read.budget_usd == Decimal("2")

    async def test_a_moved_price_a_note_on_the_next_step_and_no_step_are_refused(
        self, db, evidence
    ):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        service = SkillImprovementService(db)
        started = await service.start(ctx, skill.id, _start())
        with pytest.raises(BadRequestError):
            await service.estimate_continuation(ctx, skill.id, started.id, SkillContinue())
        run = await _at_understand(db, ctx, await _skill_on_main(db, ctx))
        quote = await service.estimate_continuation(ctx, run.skill_id, run.id, SkillContinue())

        def consent(**values: Any) -> SkillContinuationConsent:
            return SkillContinuationConsent(
                **{
                    "confirmed": True,
                    "estimate_usd": quote.total_usd,
                    "candidate_hash": quote.candidate_hash,
                    "budget_usd": run.budget_usd,
                    **values,
                }
            )

        with pytest.raises(ConcurrentChangeError):
            await service.continue_run(ctx, run.skill_id, run.id, consent(candidate_hash="0" * 64))
        with pytest.raises(BadRequestError):
            await service.continue_run(ctx, run.skill_id, run.id, consent(note="no"))
        evidence["price"] = Decimal("5")
        with pytest.raises(ConcurrentChangeError):
            await service.continue_run(ctx, run.skill_id, run.id, consent())
        with pytest.raises(PaymentRequiredError):
            await service.continue_run(
                ctx, run.skill_id, run.id, consent(estimate_usd=Decimal("5"))
            )

    async def test_every_attempt_used_leaves_no_try_again(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        service = SkillImprovementService(db)
        read = await service.start(ctx, skill.id, _start(max_iterations=1))
        run = await _row(db, read)
        await skill_improvement_repo.update_run(
            db, run=run, values={"status": "stopped", "stage": "filtering"}
        )

        with pytest.raises(BadRequestError):
            await service.estimate_continuation(ctx, skill.id, run.id, SkillContinue())


class TestStops:
    @pytest.mark.security
    async def test_no_evidence_left_and_no_budget_left_stop_the_analysis(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        service = SkillImprovementService(db)
        read = await service.start(ctx, skill.id, _start())

        evidence["runs"] = []
        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)
        assert (run.status, run.stop_reason) == ("stopped", "no_data")

        other = await _skill_on_main(db, ctx)
        evidence["runs"] = [_packed()]
        read = await service.start(ctx, other.id, _start())
        evidence["price"] = Decimal("2")
        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)
        assert (run.status, run.stop_reason) == ("stopped", "budget")

    async def test_an_analysis_that_failed_fails_the_step_and_a_retry_runs_it_again(
        self, db, evidence
    ):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        service = SkillImprovementService(db)
        read = await service.start(ctx, skill.id, _start())
        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)
        request = await db.get(AuthoringRequest, run.analysis_request_id)
        assert request is not None
        request.status = AuthoringStatus.FAILED.value
        await db.flush()

        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)
        assert (run.status, run.stage, run.stop_reason) == ("failed", "classifying", "proposal")

        retried = await service.retry(ctx, skill.id, run.id)
        assert (retried.status, retried.stage) == ("running", "analyzing")
        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)
        assert run.analysis_request_id not in (None, request.id)
        with pytest.raises(BadRequestError):
            await service.retry(ctx, skill.id, run.id)

    async def test_a_failed_proposal_is_retried_as_a_proposal(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)
        service = SkillImprovementService(db)
        quote = await service.estimate_continuation(ctx, skill.id, run.id, SkillContinue())
        await service.continue_run(
            ctx,
            skill.id,
            run.id,
            SkillContinuationConsent(
                confirmed=True,
                estimate_usd=quote.total_usd,
                candidate_hash=quote.candidate_hash,
                budget_usd=run.budget_usd,
            ),
        )
        await service.advance(run.id, ctx.organization_id)
        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=run.id, number=1
        )
        assert iteration is not None and iteration.authoring_request_id is not None
        request = await db.get(AuthoringRequest, iteration.authoring_request_id)
        assert request is not None
        request.status = AuthoringStatus.FAILED.value
        await db.flush()

        await service.advance(run.id, ctx.organization_id)
        run = await _row(db, SkillImprovementRead.model_validate(run))
        assert (run.status, run.stage) == ("failed", "proposing")
        retried = await service.retry(ctx, skill.id, run.id)
        assert (retried.status, retried.stage) == ("running", "proposing")
        assert retried.iterations[0].authoring_request_id is None

    async def test_an_analysis_with_no_problem_in_the_skill_stops_there(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        service = SkillImprovementService(db)
        read = await service.start(ctx, skill.id, _start())
        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)
        assert run.analysis_request_id is not None
        await _finish(db, run.analysis_request_id, {"problems": []})

        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)

        assert (run.status, run.stop_reason) == ("stopped", "no_proposal")

    async def test_an_analysis_whose_worker_went_silent_fails_the_step(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        service = SkillImprovementService(db)
        read = await service.start(ctx, skill.id, _start())
        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)
        request = await db.get(AuthoringRequest, run.analysis_request_id)
        assert request is not None
        request.status = AuthoringStatus.RUNNING.value
        request.started_at = request.heartbeat_at = datetime.now(UTC) - timedelta(minutes=5)
        await db.flush()

        await service.advance(read.id, ctx.organization_id)
        assert (await _row(db, read)).status == "running"
        request.heartbeat_at = datetime.now(UTC) - timedelta(hours=1)
        await db.flush()
        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)

        assert (run.status, run.stop_reason) == ("failed", "proposal")

    async def test_a_line_that_moved_on_makes_the_session_stale(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        service = SkillImprovementService(db)
        read = await service.start(ctx, skill.id, _start())
        await SkillService(db).update(ctx, skill.id, SkillUpdate(content="Moved on."))

        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)

        assert (run.status, run.stop_reason) == ("stale", "stale")

    async def test_whoever_acts_losing_access_stops_the_session(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        service = SkillImprovementService(db)
        read = await service.start(ctx, skill.id, _start())
        member = (
            await db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == ctx.organization_id,
                    OrganizationMember.user_id == ctx.user_id,
                )
            )
        ).scalar_one()
        member.role = "viewer"
        await db.flush()

        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)
        assert (run.status, run.stop_reason) == ("stopped", "permission")

        other = await _owner(db)
        skill = await _skill_on_main(db, other)
        read = await service.start(other, skill.id, _start())
        await db.delete(
            (
                await db.execute(
                    select(OrganizationMember).where(OrganizationMember.user_id == other.user_id)
                )
            ).scalar_one()
        )
        await db.flush()
        await service.advance(read.id, other.organization_id)
        assert (await _row(db, read)).stop_reason == "permission"

    async def test_a_session_nobody_took_on_for_a_week_ends_as_expired(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)
        fresh = await _at_understand(db, ctx, await _skill_on_main(db, ctx))
        run.stage_started_at = datetime.now(UTC) - timedelta(days=8)
        await db.flush()
        working = await SkillImprovementService(db).start(
            ctx, (await _skill_on_main(db, ctx)).id, _start()
        )

        swept = await SkillImprovementService(db).sweep()

        assert swept >= 2
        run = await _row(db, SkillImprovementRead.model_validate(run))
        assert (run.status, run.stop_reason) == ("stale", "expired")
        assert (await _row(db, SkillImprovementRead.model_validate(fresh))).status == "waiting"
        assert (await _row(db, working)).status == "queued"

    async def test_a_session_decided_while_the_sweep_waited_is_left_alone(
        self, db, evidence, monkeypatch
    ):
        """Listed while it rested, accepted before its lock came: nothing to end, no crash."""
        ctx = await _owner(db)
        run = await _at_understand(db, ctx, await _skill_on_main(db, ctx))
        run.stage_started_at = datetime.now(UTC) - timedelta(days=8)
        run.status = "accepted"
        await db.flush()
        listed = iter([[(run.id, ctx.organization_id)], []])

        async def resting(*_args: object, **_kwargs: object) -> list[tuple[uuid.UUID, uuid.UUID]]:
            return next(listed)

        monkeypatch.setattr(skill_improvement_repo, "list_resting", resting)

        assert await SkillImprovementService(db).sweep() == 0
        assert (await _row(db, SkillImprovementRead.model_validate(run))).status == "accepted"


class TestEnding:
    async def test_cancel_and_discard_end_the_session_and_free_the_line(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)
        service = SkillImprovementService(db)

        cancelled = await service.cancel(ctx, skill.id, run.id)
        discarded = await service.discard(ctx, skill.id, run.id, ImprovementDiscard(confirmed=True))
        again = await service.start(ctx, skill.id, _start())

        assert cancelled.status == "cancelled"
        assert (discarded.status, discarded.outcome) == ("rejected", "discarded")
        assert again.status == "queued"
        with pytest.raises(ConcurrentChangeError):
            await service.cancel(ctx, skill.id, run.id)

    async def test_only_the_creator_or_an_admin_discards(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)
        builder = await _member(db, ctx, OrgRoleName.BUILDER)

        read = await SkillImprovementService(db).read(builder, skill.id, run.id)
        assert not read.can_discard
        with pytest.raises(AuthorizationError) as refused:
            await SkillImprovementService(db).discard(
                builder, skill.id, run.id, ImprovementDiscard(confirmed=True)
            )
        assert refused.value.details == {"permission": "org:settings"}

    @pytest.mark.security
    async def test_only_the_creator_or_an_admin_stops_it(self, db, evidence):
        """Stopping sets aside the session's check, which its creator paid for."""
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)
        builder = await _member(db, ctx, OrgRoleName.BUILDER)

        with pytest.raises(AuthorizationError) as refused:
            await SkillImprovementService(db).cancel(builder, skill.id, run.id)
        assert refused.value.details == {"permission": "org:settings"}
        stopped = await SkillImprovementService(db).cancel(ctx, skill.id, run.id)

        assert stopped.status == "cancelled"


class TestListing:
    async def test_a_page_reads_each_lines_agents_once(self, db, evidence, monkeypatch):
        """Every session on a line counts the same agents, so a page asks once per line."""
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        service = SkillImprovementService(db)
        for _ in range(2):
            read = await service.start(ctx, skill.id, _start())
            await service.cancel(ctx, skill.id, read.id)
        await service.start(ctx, skill.id, _start())
        asked: list[uuid.UUID | None] = []
        original = SkillAgentService.line_agents

        async def counted(self, skill, fork_id):
            asked.append(fork_id)
            return await original(self, skill, fork_id)

        monkeypatch.setattr(SkillAgentService, "line_agents", counted)

        listed = await service.list_for_skill(
            ctx, skill.id, fork_id=None, main_only=True, skip=0, limit=50
        )

        assert len(listed) == 3 and asked == [None]
        assert {(read.agents, read.hidden_agents) for read in listed} == {(1, 0)}

    async def test_sessions_list_by_line_and_waiting_ones_reach_waiting_for_you(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        fork = await _fork(db, ctx, skill, "fork text")
        on_main = await _at_understand(db, ctx, skill)
        service = SkillImprovementService(db)
        on_fork = await service.start(ctx, skill.id, _start(fork_id=fork.id))

        everything = await service.list_for_skill(
            ctx, skill.id, fork_id=None, main_only=False, skip=0, limit=50
        )
        main = await service.list_for_skill(
            ctx, skill.id, fork_id=None, main_only=True, skip=0, limit=50
        )
        forked = await service.list_for_skill(
            ctx, skill.id, fork_id=fork.id, main_only=False, skip=0, limit=50
        )
        awaiting = await service.awaiting(ctx)

        assert [item.id for item in everything] == [on_fork.id, on_main.id]
        assert {item.created_by.id for item in everything if item.created_by} == {ctx.user_id}
        assert [item.id for item in main] == [on_main.id]
        assert [item.id for item in forked] == [on_fork.id]
        assert [(item.id, item.skill_name, item.line_name) for item in awaiting] == [
            (on_main.id, skill.name, "main")
        ]
        stranger = await _owner(db)
        assert await service.awaiting(stranger) == []
        assert await service.awaiting(_narrowed(ctx, Perm.RUNS_VIEW)) == []


async def _agent_run(db: AsyncSession, ctx: AuthContext, skill: Skill) -> AgentRun:
    agents = await SkillImprovementService(db).skill_agents.line_agents(skill, None)
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        agent_id=agents[0].agent.id,
        surface="web",
        status="completed",
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    return run


class TestEdges:
    async def test_an_attempt_without_edits_lists_none(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)

        service = SkillImprovementService(db)
        assert await service.changes(ctx, skill.id, run.id) == []
        [problem] = (await service.problems(ctx, skill.id, run.id)).problems
        assert (problem.runs, problem.agents) == (0, [])

    async def test_a_reworded_description_holds_at_most_500_characters(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)
        await _propose(db, ctx, run, [_description("How refunds and returns work.")])
        service = SkillImprovementService(db)
        [change] = await service.changes(ctx, skill.id, run.id)

        with pytest.raises(BadRequestError):
            await service.edit_change(
                ctx, skill.id, run.id, change.id, ChangeEdit(edited_text="x" * 501)
            )
        kept = await service.edit_change(
            ctx, skill.id, run.id, change.id, ChangeEdit(edited_text="How returns work.")
        )
        read = await service.read(ctx, skill.id, run.id)

        assert kept.edited_text == "How returns work." and read.iterations[0].description_changed

    @pytest.mark.security
    async def test_a_session_started_with_a_revoked_key_stops_for_permission(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        service = SkillImprovementService(db)
        read = await service.start(ctx, skill.id, _start())
        run = await _row(db, read)
        run.created_by_api_key_id = uuid.uuid4()
        await db.flush()

        await service.advance(read.id, ctx.organization_id)

        assert (await _row(db, read)).stop_reason == "permission"

    async def test_a_session_wakes_only_while_it_works(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)
        service = SkillImprovementService(db)

        await service.wake(run.id, organization_id=ctx.organization_id)
        await service.wake(uuid.uuid4(), organization_id=ctx.organization_id)
        await service.advance(uuid.uuid4(), ctx.organization_id)
        await service.advance(run.id, ctx.organization_id)

        assert (await _row(db, SkillImprovementRead.model_validate(run))).status == "waiting"

    async def test_a_step_whose_request_was_removed_asks_again(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        service = SkillImprovementService(db)
        read = await service.start(ctx, skill.id, _start())
        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)
        await db.delete(await db.get(AuthoringRequest, run.analysis_request_id))
        await db.flush()

        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)
        assert (run.status, run.stage) == ("running", "analyzing")

        other = await _at_understand(db, ctx, await _skill_on_main(db, ctx))
        await _continue(db, ctx, other)
        await service.advance(other.id, ctx.organization_id)
        await service.advance(other.id, ctx.organization_id)
        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=other.id, number=1
        )
        assert iteration is not None and iteration.authoring_request_id is not None
        first = iteration.authoring_request_id
        assert (await _row(db, SkillImprovementRead.model_validate(other))).status == "running"
        await db.delete(await db.get(AuthoringRequest, first))
        await db.flush()
        await db.refresh(iteration)
        await service.advance(other.id, ctx.organization_id)
        await db.refresh(iteration)

        assert iteration.authoring_request_id not in (None, first)

    @pytest.mark.security
    async def test_a_proposal_the_budget_no_longer_covers_stops_before_it_starts(
        self, db, evidence
    ):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)
        await _continue(db, ctx, run)
        evidence["price"] = Decimal("5")

        await SkillImprovementService(db).advance(run.id, ctx.organization_id)
        run = await _row(db, SkillImprovementRead.model_validate(run))

        assert (run.status, run.stage, run.stop_reason) == ("stopped", "proposing", "budget")

    @pytest.mark.security
    async def test_a_last_attempt_stopped_for_its_budget_resumes_the_same_attempt(
        self, db, evidence
    ):
        """Nothing was written yet, so a raised limit takes the same step, not a new attempt."""
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)
        run.max_iterations = 1
        await db.flush()
        await _continue(db, ctx, run)
        evidence["price"] = Decimal("5")
        service = SkillImprovementService(db)
        await service.advance(run.id, ctx.organization_id)

        quote = await service.estimate_continuation(ctx, skill.id, run.id, SkillContinue())
        read = await service.continue_run(
            ctx,
            skill.id,
            run.id,
            SkillContinuationConsent(
                confirmed=True,
                estimate_usd=quote.total_usd,
                candidate_hash=quote.candidate_hash,
                budget_usd=Decimal("10"),
            ),
        )

        assert (quote.mode, quote.number) == ("resume", 1)
        assert (read.status, read.stage, read.iteration) == ("running", "proposing", 1)

    @pytest.mark.security
    async def test_a_proposal_the_organization_cannot_afford_is_refused_not_queued(
        self, db, evidence
    ):
        """The session's own limit can be raised with consent; the organization's cannot."""
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)
        evidence["affordable"] = False
        service = SkillImprovementService(db)

        quote = await service.estimate_continuation(ctx, skill.id, run.id, SkillContinue())
        with pytest.raises(PaymentRequiredError):
            await _continue(db, ctx, run)

        assert quote.affordable is False
        read = await service.read(ctx, skill.id, run.id)
        assert (read.status, read.stage) == ("waiting", "classifying")

    async def test_a_proposal_with_nothing_left_to_learn_from_is_refused(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        run = await _at_understand(db, ctx, skill)
        evidence["runs"] = []

        with pytest.raises(BadRequestError) as refused:
            await SkillImprovementService(db).estimate_continuation(
                ctx, skill.id, run.id, SkillContinue()
            )

        assert refused.value.details == {"reason": "no_evidence"}


class TestTheLinesEvidence:
    async def test_main_reads_its_versions_and_a_fork_without_its_own_reads_its_base(
        self, db, monkeypatch
    ):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        fork = await _fork(db, ctx, skill)
        on_fork = await _serving(db, ctx, "Returns", _spec(skill, fork_id=str(fork.id)))
        asked: list[list[uuid.UUID]] = []
        reading: list[set[uuid.UUID]] = []

        async def for_skill(self, ctx, skill_id, *, window_days, versions=None, readers=None):
            asked.append(list(versions or []))
            reading.append(set(readers or []))
            return EvidencePack()

        monkeypatch.setattr(type(AuthoringService(db).evidence), "for_skill", for_skill)
        service = SkillImprovementService(db)
        main = await service.line_for_session(
            ctx, SkillImprovementRun(skill_id=skill.id, fork_id=None, window_days=30)
        )
        forked = await service.line_for_session(
            ctx, SkillImprovementRun(skill_id=skill.id, fork_id=fork.id, window_days=30)
        )
        await service.evidence_of(ctx, main, SkillImprovementRun(window_days=30))
        await service.evidence_of(ctx, forked, SkillImprovementRun(window_days=30))

        versions, _ = await skill_version_repo.list_versions(
            db, organization_id=ctx.organization_id, skill_id=skill.id, fork_id=None
        )
        assert sorted(asked[0]) == sorted(version.id for version in versions)
        assert asked[1] == [fork.base.id]
        assert on_fork.id not in reading[0]
        assert reading[0] and reading[1] == {on_fork.id}
        with pytest.raises(NotFoundError):
            await service.line_for_session(
                ctx, SkillImprovementRun(skill_id=uuid.uuid4(), fork_id=None, window_days=30)
            )


async def _continue(db: AsyncSession, ctx: AuthContext, run: SkillImprovementRun) -> None:
    service = SkillImprovementService(db)
    quote = await service.estimate_continuation(ctx, run.skill_id, run.id, SkillContinue())
    await service.continue_run(
        ctx,
        run.skill_id,
        run.id,
        SkillContinuationConsent(
            confirmed=True,
            estimate_usd=quote.total_usd,
            candidate_hash=quote.candidate_hash,
            budget_usd=run.budget_usd,
        ),
    )


async def _check_id(db: AsyncSession, run: SkillImprovementRun) -> uuid.UUID | None:
    iteration = await skill_improvement_repo.get_iteration(
        db, organization_id=run.organization_id, run_id=run.id, number=run.iteration
    )
    assert iteration is not None
    return iteration.skill_check_id


class FakeChecks:
    """Stands in for the multi-agent check: writes its rows, and decides as told."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.calls: list[tuple[str, Any]] = []
        self.price = Decimal("0.30")
        self.refuse: Exception | None = None
        self.excluded: list[list[uuid.UUID]] = []
        self.conflict = False
        self.base_version_id = uuid.uuid4()
        self.agents: list[SkillCheckAgentRead] = []
        self.hidden_unknown = 0
        self.files: list[Any] = []
        self.merged_from: list[uuid.UUID | None] = []
        self.drift: Exception | None = None

    def _estimate(self, data: SkillCheckStart) -> SkillCheckEstimate:
        return SkillCheckEstimate(
            line=LineRef(fork_id=data.fork_id, name="main"),
            base_version=VersionRef(id=self.base_version_id, number=1, fork_id=data.fork_id),
            mode=data.mode,
            description_changed=False,
            agents=self.agents,
            hidden=self.hidden_unknown,
            hidden_unknown=self.hidden_unknown,
            expected_usd=self.price / 3,
            at_most_usd=self.price,
            org_remaining_usd=None,
            affordable=True,
        )

    async def estimate(self, ctx, skill_id, data, *, exclude_conversations=(), files=None):
        self.calls.append(("estimate", data))
        self.excluded.append(list(exclude_conversations))
        return self._estimate(data)

    async def start(
        self, ctx, skill_id, data, *, source=None, exclude_conversations=(), files=None
    ):
        if self.refuse is not None:
            raise self.refuse
        self.excluded.append(list(exclude_conversations))
        self.calls.append(("start", (data, source)))
        self.files.append(files)
        assert data.candidate is not None
        skill = await self.db.get(Skill, skill_id)
        assert skill is not None and skill.latest_version_id is not None
        check = await skill_check_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            check=SkillCheck(
                skill_id=skill_id,
                fork_id=data.fork_id,
                base_version_id=skill.latest_version_id,
                candidate_description=data.candidate.description,
                candidate_content=data.candidate.content,
                candidate_hash="c" * 64,
                description_changed=False,
                mode=data.mode.value,
                source=source.value,
                status=CheckStatus.RUNNING.value,
                expected_usd=self.price / 3,
                at_most_usd=self.price,
            ),
        )
        return SimpleNamespace(id=check.id)

    async def read(self, ctx, skill_id, check_id):
        check = await skill_check_repo.get(self.db, check_id, organization_id=ctx.organization_id)
        assert check is not None
        return SkillCheckRead(
            **self._estimate(SkillCheckStart(candidate=_TEXT)).model_dump(),
            id=check.id,
            skill_id=skill_id,
            source=check.source,
            status=check.status,
            verdict=check.verdict,
            outcomes=[CheckOutcome.APPLY, CheckOutcome.DISCARD] if check.verdict else [],
            candidate=_TEXT,
            created_at=check.created_at,
        )

    async def apply(
        self, ctx, skill_id, check_id, data, *, from_session=False, merged_from_id=None
    ):
        assert from_session
        if self.conflict:
            raise ConcurrentChangeError(message="The line's agents changed since the check")
        self.calls.append(("apply", data))
        self.merged_from.append(merged_from_id)
        pinned = [SimpleNamespace(id=uuid.uuid4(), name="Clerk")] if data.pin_worse else []
        return SimpleNamespace(version=SimpleNamespace(id=uuid.uuid4(), number=4), pinned=pinned)

    async def fork(self, ctx, skill_id, check_id, data, *, from_session=False):
        assert from_session
        self.calls.append(("fork", data))
        latest = VersionNumberRef(id=uuid.uuid4(), number=1)
        return SimpleNamespace(
            fork=SkillForkRead.model_construct(id=uuid.uuid4(), name=data.name, latest=latest),
            moved=[],
            draft_only=[],
        )

    async def cancel(self, ctx, skill_id, check_id, *, from_session=False):
        assert from_session
        self.calls.append(("cancel", check_id))
        check = await self.db.get(SkillCheck, check_id)
        assert check is not None
        check.status = CheckStatus.CANCELLED.value
        await self.db.flush()

    async def stop_for_session(self, check):
        self.calls.append(("cancel", check.id))
        check.status = CheckStatus.CANCELLED.value
        await self.db.flush()

    async def set_aside_for_session(self, check):
        self.calls.append(("set_aside", check.id))
        check.status = CheckStatus.DISCARDED.value
        await self.db.flush()

    async def discard(self, ctx, skill_id, check_id, *, from_session=False):
        assert from_session
        self.calls.append(("discard", check_id))

    async def decidable_for_session(self, ctx, skill_id, check_id):
        if self.drift is not None:
            raise self.drift
        self.calls.append(("decidable", check_id))
        check = await self.db.get(SkillCheck, check_id)
        assert check is not None
        return check

    async def record_decision(self, ctx, check, outcome, version_id, *, acknowledged):
        self.calls.append(("decided", (check.id, outcome, version_id, acknowledged)))


_TEXT = CandidateText(description="How refunds work.", content="x")


async def _at_changes(
    db: AsyncSession, ctx: AuthContext, changes: list[dict[str, Any]] | None = None
) -> SkillImprovementRun:
    run = await _at_understand(db, ctx, await _skill_on_main(db, ctx))
    await _propose(
        db, ctx, run, changes or [_body_edit("Refunds take 14 days.", "Refunds take 30 days.")]
    )
    return await _row(db, SkillImprovementRead.model_validate(run))


def _checked(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> FakeChecks:
    fake = FakeChecks(db)
    monkeypatch.setattr(SkillImprovementService, "checks", fake, raising=False)
    original = SkillImprovementService.__init__

    def init(self, session):
        original(self, session)
        self.checks = fake

    monkeypatch.setattr(SkillImprovementService, "__init__", init)
    return fake


async def _check_now(
    db: AsyncSession, ctx: AuthContext, run: SkillImprovementRun, **consent: Any
) -> SkillImprovementRead:
    service = SkillImprovementService(db)
    quote = await service.estimate_continuation(
        ctx, run.skill_id, run.id, SkillContinue(mode=consent.get("mode"))
    )
    return await service.continue_run(
        ctx,
        run.skill_id,
        run.id,
        SkillContinuationConsent(
            **{
                "confirmed": True,
                "estimate_usd": quote.total_usd,
                "candidate_hash": quote.candidate_hash,
                "budget_usd": run.budget_usd,
                **consent,
            }
        ),
    )


async def _settle(
    db: AsyncSession,
    run: SkillImprovementRun,
    *,
    measured: str | None = "better",
    **values: Any,
) -> SkillImprovementRun:
    """Finish the attempt's check with `values`, one agent of it in state `measured`;
    `None` leaves the check with no agent, as on a line nobody reads."""
    iteration = await skill_improvement_repo.get_iteration(
        db, organization_id=run.organization_id, run_id=run.id, number=run.iteration
    )
    assert iteration is not None and iteration.skill_check_id is not None
    check = await db.get(SkillCheck, iteration.skill_check_id)
    assert check is not None
    for key, value in values.items():
        setattr(check, key, value)
    if measured is not None and "verdict" in values:
        agent = Agent(
            organization_id=run.organization_id,
            slug=f"measured-{uuid.uuid4().hex[:8]}",
            name="Measured",
            draft_spec={},
        )
        db.add(agent)
        await db.flush()
        db.add(
            SkillCheckAgent(
                organization_id=run.organization_id,
                check_id=check.id,
                agent_id=agent.id,
                agent_version=1,
                state=measured,
                expected_usd=Decimal(0),
                at_most_usd=Decimal(0),
            )
        )
    await db.flush()
    await SkillImprovementService(db).advance(run.id, run.organization_id)
    return await _row(db, SkillImprovementRead.model_validate(run))


class TestCheckAndResult:
    async def test_the_check_is_priced_across_the_line_and_started_on_the_chosen_text(
        self, db, evidence, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        fake.excluded.clear()
        service = SkillImprovementService(db)

        quote = await service.estimate_continuation(
            ctx, run.skill_id, run.id, SkillContinue(mode=CheckMode.THOROUGH)
        )
        read = await _check_now(db, ctx, run, mode="thorough")

        assert (quote.mode, quote.total_usd) == ("next_step", fake.price)
        assert quote.check_estimate is not None and quote.check_estimate.mode == "thorough"
        [(_, (started, source))] = [call for call in fake.calls if call[0] == "start"]
        assert started.candidate.content.startswith("Refunds take 30 days.")
        assert (started.mode, source) == (CheckMode.THOROUGH, CheckSource.SESSION)
        assert fake.excluded and all(item == [_CONVERSATION] for item in fake.excluded)
        assert (read.status, read.stage) == ("running", "evaluating")
        assert read.check is not None and read.check.status == "running"
        assert read.outcomes == []

    async def test_a_limit_raised_at_the_quote_is_the_limit_the_session_keeps(
        self, db, evidence, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        raised = run.budget_usd + Decimal("0.01")
        service = SkillImprovementService(db)

        quote = await service.estimate_continuation(
            ctx, run.skill_id, run.id, SkillContinue(budget_usd=raised)
        )
        await service.continue_run(
            ctx,
            run.skill_id,
            run.id,
            SkillContinuationConsent(
                confirmed=True,
                estimate_usd=quote.total_usd,
                candidate_hash=quote.candidate_hash,
                budget_usd=quote.budget_usd,
            ),
        )

        assert quote.budget_usd == raised
        assert (await db.get(SkillImprovementRun, run.id)).budget_usd == raised

    async def test_a_check_still_running_leaves_the_session_working(
        self, db, evidence, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)

        run = await _settle(db, run)

        assert (run.status, run.stage) == ("running", "evaluating")

    async def test_a_persons_verdict_rewrites_the_attempts_result_and_not_where_it_went(
        self, db, evidence, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        service = SkillImprovementService(db)
        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=run.organization_id, run_id=run.id, number=run.iteration
        )
        assert iteration is not None and iteration.skill_check_id is not None
        check = await db.get(SkillCheck, iteration.skill_check_id)
        assert check is not None
        # A check still running has given the attempt nothing to rewrite.
        await service.refresh_check_verdict(check, CheckVerdict.PASSED)
        assert iteration.check_verdict is None
        run = await _settle(db, run, status="done", verdict="blocked")

        await service.refresh_check_verdict(check, CheckVerdict.PASSED)

        read = await service.read(ctx, run.skill_id, run.id)
        [attempt] = read.iterations
        assert (attempt.check_verdict, attempt.verdict) == ("passed", "better")
        assert (read.status, read.stage) == (run.status, run.stage)

    @pytest.mark.parametrize(
        ("verdict", "status", "stop", "measured"),
        [
            ("passed", "ready", None, "better"),
            ("needs_ack", "ready", None, "better"),
            ("blocked", "ready", None, "regression"),
            ("no_better", "ready", None, "no_change"),
        ],
    )
    async def test_a_finished_check_becomes_the_attempts_result(
        self, db, evidence, monkeypatch, verdict, status, stop, measured
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)

        run = await _settle(db, run, status="done", verdict=verdict, measured="better")
        read = await SkillImprovementService(db).read(ctx, run.skill_id, run.id)

        assert (run.status, run.stop_reason) == (status, stop)
        [attempt] = read.iterations
        assert (attempt.check_verdict, attempt.verdict) == (verdict, measured)
        assert read.outcomes == [CheckOutcome.APPLY, CheckOutcome.DISCARD]

    @pytest.mark.parametrize(
        ("first", "then"), [("blocked", "no_better"), ("no_better", "blocked")]
    )
    async def test_a_verdict_a_person_overturns_leaves_the_session_where_that_verdict_would(
        self, db, evidence, monkeypatch, first, then
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        service = SkillImprovementService(db)

        async def judged(verdict: str) -> SkillImprovementRun:
            run = await _at_changes(db, ctx)
            await _check_now(db, ctx, run)
            return await _settle(db, run, status="done", verdict=verdict)

        straight = await judged(then)
        overturned = await judged(first)
        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=overturned.id, number=1
        )
        assert iteration is not None and iteration.skill_check_id is not None
        check = await db.get(SkillCheck, iteration.skill_check_id)
        assert check is not None
        check.verdict = then
        await service.refresh_check_verdict(check, CheckVerdict(then))

        reads = [await service.read(ctx, run.skill_id, run.id) for run in (straight, overturned)]
        waiting = {item.id for item in await service.awaiting(ctx)}

        assert [
            (read.status, read.stage, read.stop_reason, read.outcomes, read.id in waiting)
            for read in reads
        ] == [("ready", "judging", None, [CheckOutcome.APPLY, CheckOutcome.DISCARD], True)] * 2

    @pytest.mark.parametrize(("verdict", "measured"), [("passed", None), ("needs_ack", "unknown")])
    async def test_a_check_that_measured_no_agent_is_no_better_result_yet_may_be_applied(
        self, db, evidence, monkeypatch, verdict, measured
    ):
        """A line nobody reads, or one none of whose agents could be checked, leaves the
        attempt inconclusive; it is still offered, the unknown agents acknowledged."""
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)

        run = await _settle(db, run, status="done", verdict=verdict, measured=measured)
        service = SkillImprovementService(db)
        read = await service.read(ctx, run.skill_id, run.id)

        assert run.status == "ready"
        [attempt] = read.iterations
        assert (attempt.check_verdict, attempt.verdict) == (verdict, "inconclusive")
        check = await db.get(SkillCheck, attempt.check_id)
        assert check is not None
        await service.refresh_check_verdict(check, CheckVerdict(verdict))
        [attempt] = (await service.read(ctx, run.skill_id, run.id)).iterations
        assert attempt.verdict == "inconclusive"

    async def test_a_check_cancelled_elsewhere_fails_the_step(self, db, evidence, monkeypatch):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)

        run = await _settle(db, run, status="cancelled")

        assert (run.status, run.stage, run.stop_reason) == ("failed", "evaluating", "eval")

    async def test_a_check_no_agent_can_take_is_refused_and_leaves_the_session_at_changes(
        self, db, evidence, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        fake.refuse = BadRequestError(message="No agent of this line can be checked")
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)

        with pytest.raises(BadRequestError):
            await _check_now(db, ctx, run)

    async def test_changes_that_no_longer_apply_together_are_chosen_again(
        self, db, evidence, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(
            db,
            ctx,
            [
                _body_edit("Refunds take 14 days.", "Refunds take 30 days."),
                _body_edit("Refunds take 14 days.", "Refunds take 60 days."),
            ],
        )
        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=run.id, number=1
        )
        assert iteration is not None
        await skill_improvement_repo.update_iteration(
            db,
            iteration=iteration,
            values={
                "included_hunk_ids": [*iteration.included_hunk_ids, *iteration.dropped_hunk_ids]
            },
        )

        with pytest.raises(BadRequestError) as refused:
            await SkillImprovementService(db).estimate_continuation(
                ctx, run.skill_id, run.id, SkillContinue()
            )

        assert refused.value.details["fields"][0]["field"] == "hunk_ids"


class TestOutcomes:
    async def test_apply_makes_a_version_and_accepts_the_session(self, db, evidence, monkeypatch):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        run = await _settle(db, run, status="done", verdict="blocked")
        service = SkillImprovementService(db)

        applied = await service.apply(
            ctx,
            run.skill_id,
            run.id,
            SkillImprovementApply(confirmed=True, pin_worse=True, acknowledge_unknown=True),
        )

        assert (applied.session.status, applied.session.outcome) == ("accepted", "applied_pinned")
        assert applied.version == 4 and applied.session.applied_version_id == applied.version_id
        [(_, sent)] = [call for call in fake.calls if call[0] == "apply"]
        assert sent.pin_worse and sent.acknowledge_unknown
        with pytest.raises(ConcurrentChangeError):
            await service.apply(ctx, run.skill_id, run.id, SkillImprovementApply(confirmed=True))

    async def test_apply_without_a_worse_agent_is_a_plain_apply(self, db, evidence, monkeypatch):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        run = await _settle(db, run, status="done", verdict="passed")

        applied = await SkillImprovementService(db).apply(
            ctx, run.skill_id, run.id, SkillImprovementApply(confirmed=True)
        )

        assert applied.session.outcome == "applied" and applied.pinned == []

    async def test_fork_for_the_agents_it_helped_accepts_the_session(
        self, db, evidence, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        run = await _settle(db, run, status="done", verdict="blocked")

        forked = await SkillImprovementService(db).fork(
            ctx, run.skill_id, run.id, SkillImprovementFork(confirmed=True, name="Returns")
        )

        assert (forked.session.status, forked.session.outcome) == ("accepted", "forked")
        assert forked.session.applied_version_id == forked.fork.latest.id
        assert [call[1].name for call in fake.calls if call[0] == "fork"] == ["Returns"]

    async def test_an_outcome_before_the_result_is_refused(self, db, evidence, monkeypatch):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)

        with pytest.raises(ConcurrentChangeError):
            await SkillImprovementService(db).fork(
                ctx, run.skill_id, run.id, SkillImprovementFork(confirmed=True, name="Returns")
            )

    async def test_a_check_plan_that_changed_at_the_same_price_asks_again(
        self, db, evidence, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        service = SkillImprovementService(db)
        quote = await service.estimate_continuation(ctx, run.skill_id, run.id, SkillContinue())
        fake.agents = [
            SkillCheckAgentRead(
                agent=AgentRef(id=uuid.uuid4(), name="Desk"),
                agent_version=2,
                state=AgentState.QUEUED,
                stages=[],
                expected_usd=Decimal("0"),
                at_most_usd=Decimal("0"),
            )
        ]

        with pytest.raises(ConcurrentChangeError):
            await service.continue_run(
                ctx,
                run.skill_id,
                run.id,
                SkillContinuationConsent(
                    confirmed=True,
                    estimate_usd=quote.total_usd,
                    candidate_hash=quote.candidate_hash,
                    budget_usd=run.budget_usd,
                ),
            )
        assert [call for call in fake.calls if call[0] == "start"] == []

    async def test_cancelling_during_the_check_cancels_it_and_discarding_a_result_discards_it(
        self, db, evidence, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        service = SkillImprovementService(db)

        await service.cancel(ctx, run.skill_id, run.id)
        other = await _at_changes(db, ctx)
        await _check_now(db, ctx, other)
        other = await _settle(db, other, status="done", verdict="passed")
        await service.discard(ctx, other.skill_id, other.id, ImprovementDiscard(confirmed=True))
        decided = await _at_changes(db, ctx)
        await _check_now(db, ctx, decided)
        decided = await _settle(db, decided, status="done", verdict="passed")
        await _settle(db, decided, status="applied")
        await service.discard(ctx, decided.skill_id, decided.id, ImprovementDiscard(confirmed=True))
        await service.discard(ctx, run.skill_id, run.id, ImprovementDiscard(confirmed=True))

        assert [name for name, _ in fake.calls if name in {"cancel", "discard"}] == [
            "cancel",
            "discard",
        ]

    async def test_try_again_after_a_result_starts_a_new_attempt(self, db, evidence, monkeypatch):
        """The last attempt's check is set aside: only the session could decide it."""
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        run = await _settle(db, run, status="done", verdict="blocked")
        checked = await _check_id(db, run)
        service = SkillImprovementService(db)

        quote = await service.estimate_continuation(ctx, run.skill_id, run.id, SkillContinue())
        read = await service.continue_run(
            ctx,
            run.skill_id,
            run.id,
            SkillContinuationConsent(
                confirmed=True,
                estimate_usd=quote.total_usd,
                candidate_hash=quote.candidate_hash,
                budget_usd=run.budget_usd,
                note="Keep main's other rules",
            ),
        )

        assert (quote.mode, read.iteration, read.stage) == ("next_round", 2, "proposing")
        assert read.check is None
        assert ("set_aside", checked) in fake.calls

    async def test_a_result_nobody_decided_for_a_week_sets_its_check_aside(
        self, db, evidence, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        run = await _settle(db, run, status="done", verdict="passed")
        checked = await _check_id(db, run)
        run.stage_started_at = datetime.now(UTC) - timedelta(days=8)
        await db.flush()

        await SkillImprovementService(db).sweep()

        assert (await _row(db, SkillImprovementRead.model_validate(run))).status == "stale"
        assert ("set_aside", checked) in fake.calls


class TestHandedOver:
    async def test_a_session_started_from_an_agents_improve_runs_on_that_agents_line(
        self, db, evidence, monkeypatch
    ):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        fork = await _fork(db, ctx, skill, "fork text")
        handed = uuid.uuid4()
        seed = SkillSeed(
            agent_id=uuid.uuid4(),
            fork_id=fork.id,
            run_ids=[uuid.uuid4()],
            problems=["The window is wrong"],
            quotes=["Refunds take 14 days."],
        )
        asked: list[tuple[uuid.UUID, uuid.UUID]] = []

        async def skill_seed(self, ctx, run_id, skill_id):
            asked.append((run_id, skill_id))
            return seed

        monkeypatch.setattr(ImprovementPipelineService, "skill_seed", skill_seed)
        service = SkillImprovementService(db)

        quote = await service.estimate(ctx, skill.id, SkillImprovementTarget(from_run=handed))
        read = await service.start(ctx, skill.id, _start(from_run=handed))
        run = await _row(db, read)

        assert asked == [(handed, skill.id), (handed, skill.id)]
        assert (quote.line.fork_id, read.fork_id, read.line_name) == (fork.id, fork.id, "returns")
        assert run.seed == {
            "agent_id": str(seed.agent_id),
            "run_ids": [str(seed.run_ids[0])],
            "problems": ["The window is wrong"],
            "quotes": ["Refunds take 14 days."],
        }

    async def test_a_hand_off_the_agents_session_refuses_is_refused(
        self, db, evidence, monkeypatch
    ):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)

        async def skill_seed(self, ctx, run_id, skill_id):
            raise BadRequestError(message="The session found no problem in that skill")

        monkeypatch.setattr(ImprovementPipelineService, "skill_seed", skill_seed)

        with pytest.raises(BadRequestError):
            await SkillImprovementService(db).start(ctx, skill.id, _start(from_run=uuid.uuid4()))


class TestErasingAPerson:
    async def test_their_quotes_go_from_an_open_sessions_problems_and_its_seed(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        person = await _member(db, ctx, OrgRoleName.BUILDER)
        agent = (await SkillImprovementService(db).skill_agents.line_agents(skill, None))[0].agent
        theirs = await _rated(db, person, agent)
        others = await _rated(db, ctx, agent, comment=None)
        run = await _at_understand(db, ctx, skill)
        assert run.analysis_request_id is not None
        await _finish(
            db,
            run.analysis_request_id,
            {
                "problems": [
                    {
                        "title": "Wrong window",
                        "summary": "",
                        "cause": "skill",
                        "run_ids": [str(theirs.id), str(others.id)],
                        "evidence": [
                            {"run_id": str(theirs.id), "quote": "My refund is late"},
                            {"run_id": str(others.id), "quote": "Where is my parcel?"},
                        ],
                    }
                ]
            },
        )
        other_session = await _row(
            db,
            await SkillImprovementService(db).start(
                ctx, (await _skill_on_main(db, ctx)).id, _start()
            ),
        )
        for session, cited in ((run, theirs), (other_session, others)):
            session.seed = {
                "agent_id": str(agent.id),
                "run_ids": [str(cited.id)],
                "problems": ["The window is wrong"],
                "quotes": ["Quoted from that run"],
            }
        await db.flush()

        await PersonalDataService(db).purge(person.user_id)

        request = await db.get(AuthoringRequest, run.analysis_request_id)
        assert request is not None
        await db.refresh(request)
        await db.refresh(run)
        await db.refresh(other_session)
        [problem] = request.report["problems"]
        assert [quote["quote"] for quote in problem["evidence"]] == ["Where is my parcel?"]
        assert run.seed is not None and run.seed["quotes"] == []
        assert run.seed["problems"] == ["The window is wrong"]
        assert other_session.seed is not None
        assert other_session.seed["quotes"] == ["Quoted from that run"]
        [shown] = (await SkillImprovementService(db).problems(ctx, skill.id, run.id)).problems
        assert [example.quote for example in shown.examples] == ["Where is my parcel?"]


async def _recheck(
    db: AsyncSession, ctx: AuthContext, run: SkillImprovementRun, **consent: Any
) -> SkillImprovementRead:
    service = SkillImprovementService(db)
    quote = await service.estimate_recheck(ctx, run.skill_id, run.id, SkillContinue())
    return await service.recheck(
        ctx,
        run.skill_id,
        run.id,
        SkillContinuationConsent(
            **{
                "confirmed": True,
                "estimate_usd": quote.total_usd,
                "candidate_hash": quote.candidate_hash,
                "budget_usd": run.budget_usd,
                **consent,
            }
        ),
    )


async def _with_result(
    db: AsyncSession, ctx: AuthContext, monkeypatch: pytest.MonkeyPatch
) -> tuple[FakeChecks, SkillImprovementRun]:
    fake = _checked(db, monkeypatch)
    run = await _at_changes(db, ctx)
    await _check_now(db, ctx, run)
    return fake, await _settle(db, run, status="done", verdict="passed")


class TestCheckAgain:
    async def test_a_limit_raised_at_its_quote_is_quoted_and_never_lowered(
        self, db, evidence, monkeypatch
    ):
        ctx = await _owner(db)
        _, run = await _with_result(db, ctx, monkeypatch)
        service = SkillImprovementService(db)
        raised = run.budget_usd + Decimal("1")

        quotes = [
            await service.estimate_recheck(ctx, run.skill_id, run.id, SkillContinue(budget_usd=b))
            for b in (raised, Decimal("0.000001"))
        ]

        assert [quote.budget_usd for quote in quotes] == [raised, run.budget_usd]

    async def test_a_result_its_line_moved_past_is_stale_and_checked_again_on_the_new_text(
        self, db, evidence, monkeypatch
    ):
        ctx = await _owner(db)
        fake, run = await _with_result(db, ctx, monkeypatch)
        service = SkillImprovementService(db)
        first = (await service.read(ctx, run.skill_id, run.id)).check
        assert first is not None and not (await service.read(ctx, run.skill_id, run.id)).stale
        await SkillService(db).update(ctx, run.skill_id, SkillUpdate(content=f"{_BODY}\nBe brief."))

        stale = await service.read(ctx, run.skill_id, run.id)
        rechecked = await _recheck(db, ctx, run)

        assert stale.stale and stale.status == "ready"
        assert (rechecked.status, rechecked.stage) == ("running", "evaluating")
        assert rechecked.check is not None and rechecked.check.id != first.id
        assert not rechecked.stale and rechecked.base_version is not None
        assert rechecked.base_version.number == stale.base_version.number + 1
        [*_, (_, (started, _))] = [call for call in fake.calls if call[0] == "start"]
        assert started.candidate.content.endswith("Be brief.")
        assert started.candidate.content.startswith("Refunds take 30 days.")
        assert [name for name, _ in fake.calls if name == "discard"] == ["discard"]

    async def test_a_decision_refused_for_a_changed_line_is_checked_again(
        self, db, evidence, monkeypatch
    ):
        ctx = await _owner(db)
        fake, run = await _with_result(db, ctx, monkeypatch)
        fake.conflict = True
        service = SkillImprovementService(db)

        with pytest.raises(ConcurrentChangeError):
            await service.apply(ctx, run.skill_id, run.id, SkillImprovementApply(confirmed=True))
        before = await service.read(ctx, run.skill_id, run.id)
        rechecked = await _recheck(db, ctx, run)
        run = await _settle(db, run, status="done", verdict="passed")

        assert before.status == "ready" and before.check is not None
        assert rechecked.check is not None and rechecked.check.id != before.check.id
        assert (run.status, run.iteration) == ("ready", 1)

    @pytest.mark.security
    async def test_checking_again_needs_consent_to_its_price_and_the_budget_for_it(
        self, db, evidence, monkeypatch
    ):
        ctx = await _owner(db)
        fake, run = await _with_result(db, ctx, monkeypatch)

        with pytest.raises(ConcurrentChangeError):
            await _recheck(db, ctx, run, candidate_hash="0" * 64)
        with pytest.raises(ConcurrentChangeError):
            await _recheck(db, ctx, run, estimate_usd=Decimal("0.01"))
        fake.price = Decimal("5")
        with pytest.raises(PaymentRequiredError):
            await _recheck(db, ctx, run)
        assert (await _row(db, SkillImprovementRead.model_validate(run))).status == "ready"

    async def test_only_a_result_of_this_organization_is_checked_again(
        self, db, evidence, monkeypatch
    ):
        ctx = await _owner(db)
        _, run = await _with_result(db, ctx, monkeypatch)
        stranger = await _owner(db)
        service = SkillImprovementService(db)

        with pytest.raises(NotFoundError):
            await service.estimate_recheck(stranger, run.skill_id, run.id, SkillContinue())
        other = await _at_changes(db, ctx)
        with pytest.raises(BadRequestError):
            await service.estimate_recheck(ctx, other.skill_id, other.id, SkillContinue())

    async def test_every_check_of_an_attempt_counts_toward_what_it_spent(
        self, db, evidence, monkeypatch
    ):
        ctx = await _owner(db)
        _, run = await _with_result(db, ctx, monkeypatch)
        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=run.id, number=1
        )
        assert iteration is not None
        iteration.cost_usd = Decimal("0.10")
        await db.flush()

        await _recheck(db, ctx, run)
        await _settle(db, run, status="done", verdict="passed")
        await db.refresh(iteration)

        assert iteration.cost_usd == Decimal("0.10")

    async def test_a_check_decided_elsewhere_is_not_discarded_by_checking_again(
        self, db, evidence, monkeypatch
    ):
        ctx = await _owner(db)
        fake, run = await _with_result(db, ctx, monkeypatch)
        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=run.id, number=1
        )
        assert iteration is not None and iteration.skill_check_id is not None
        decided = await db.get(SkillCheck, iteration.skill_check_id)
        assert decided is not None
        decided.status = CheckStatus.DISCARDED.value
        await db.flush()

        await _recheck(db, ctx, run)

        assert [name for name, _ in fake.calls if name == "discard"] == []


class TestReviewFixes:
    async def test_a_reader_sees_no_quote_from_an_agent_they_may_not_see(
        self, db, evidence, monkeypatch
    ):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        clerk = (await SkillImprovementService(db).skill_agents.line_agents(skill, None))[0].agent
        hidden = await _serving(db, ctx, "Ledger", _spec(skill))
        seen, unseen = await _rated(db, ctx, clerk), await _rated(db, ctx, hidden)
        run = await _at_understand(db, ctx, skill)
        assert run.analysis_request_id is not None
        evidence_items = [
            {"run_id": str(seen.id), "quote": "Seen quote"},
            {"run_id": str(unseen.id), "quote": "Hidden quote"},
        ]
        await _finish(
            db,
            run.analysis_request_id,
            {
                "problems": [
                    {
                        "title": "Wrong window",
                        "summary": "",
                        "cause": "skill",
                        "run_ids": [str(seen.id), str(unseen.id)],
                        "evidence": evidence_items,
                    }
                ]
            },
        )
        await _propose(
            db,
            ctx,
            run,
            [
                {
                    **_body_edit("Refunds take 14 days.", "Refunds take 30 days."),
                    "evidence": evidence_items,
                }
            ],
        )
        service = SkillImprovementService(db)
        visible = {clerk.id}

        async def agents_seen(db, ctx, rows, perm, *, resource_type):
            return {row.id for row in rows if row.id in visible}

        monkeypatch.setattr("app.services.skill_improvement.accessible_ids", agents_seen)
        [problem] = (await service.problems(ctx, skill.id, run.id)).problems
        [change] = await service.changes(ctx, skill.id, run.id)
        visible.add(hidden.id)
        [everything] = await service.changes(ctx, skill.id, run.id)

        assert [example.quote for example in problem.examples] == ["Seen quote"]
        assert (problem.hidden_examples, problem.hidden_agents) == (1, 1)
        assert [item.quote for item in change.evidence] == ["Seen quote"]
        assert change.evidence_hidden == 1
        assert (len(everything.evidence), everything.evidence_hidden) == (2, 0)

    async def test_a_failed_session_expires_and_frees_its_line(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        service = SkillImprovementService(db)
        read = await service.start(ctx, skill.id, _start())
        run = await _row(db, read)
        run.status, run.stage = "failed", "classifying"
        run.stage_started_at = datetime.now(UTC) - timedelta(days=8)
        await db.flush()

        await service.sweep()
        again = await service.start(ctx, skill.id, _start())

        assert ((await _row(db, read)).status, (await _row(db, read)).stop_reason) == (
            "stale",
            "expired",
        )
        assert again.status == "queued"

    async def test_a_line_moving_ends_a_session_at_understand_but_not_at_changes(
        self, db, evidence
    ):
        ctx = await _owner(db)
        understand = await _at_understand(db, ctx, await _skill_on_main(db, ctx))
        changes = await _at_changes(db, ctx)
        for run in (understand, changes):
            await SkillService(db).update(ctx, run.skill_id, SkillUpdate(content=f"{_BODY}\nNew."))

        await SkillImprovementService(db).sweep()

        assert (await _row(db, SkillImprovementRead.model_validate(understand))).status == "stale"
        kept = await SkillImprovementService(db).read(ctx, changes.skill_id, changes.id)
        assert (kept.status, kept.stale) == ("waiting", True)

    async def test_a_step_quoted_before_the_line_moved_is_refused_and_priced_again(
        self, db, evidence, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        service = SkillImprovementService(db)
        old = await service.estimate_continuation(ctx, run.skill_id, run.id, SkillContinue())
        await SkillService(db).update(ctx, run.skill_id, SkillUpdate(content=f"{_BODY}\nNew."))

        read = await service.read(ctx, run.skill_id, run.id)
        with pytest.raises(ConcurrentChangeError) as refused:
            await service.continue_run(
                ctx,
                run.skill_id,
                run.id,
                SkillContinuationConsent(
                    confirmed=True,
                    estimate_usd=old.total_usd,
                    candidate_hash=old.candidate_hash,
                    budget_usd=run.budget_usd,
                ),
            )
        with pytest.raises(BadRequestError):
            await service.estimate_recheck(ctx, run.skill_id, run.id, SkillContinue())
        started = await _check_now(db, ctx, run)

        assert read.stale and refused.value.code == "LINE_MOVED"
        assert (started.status, started.stage, started.stale) == ("running", "evaluating", False)
        [(_, (checked, _))] = [call for call in fake.calls if call[0] == "start"]
        assert checked.candidate.content.endswith("New.")
        assert started.base_version is not None and read.base_version is not None
        assert started.base_version.number == read.base_version.number + 1

    async def test_changes_that_do_not_apply_to_the_moved_line_are_refused_when_priced(
        self, db, evidence, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await SkillService(db).update(ctx, run.skill_id, SkillUpdate(content="Rewritten."))

        with pytest.raises(BadRequestError) as refused:
            await SkillImprovementService(db).estimate_continuation(
                ctx, run.skill_id, run.id, SkillContinue()
            )

        assert refused.value.details["fields"][0]["field"] == "hunk_ids"

    async def test_a_session_that_goes_stale_mid_check_stops_the_check_and_keeps_its_cost(
        self, db, evidence, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=run.id, number=1
        )
        assert iteration is not None
        iteration.cost_usd = Decimal("0.05")
        await db.flush()
        await SkillService(db).update(ctx, run.skill_id, SkillUpdate(content="Moved on."))

        await SkillImprovementService(db).advance(run.id, ctx.organization_id)
        await db.refresh(iteration)

        assert (await _row(db, SkillImprovementRead.model_validate(run))).status == "stale"
        assert [name for name, _ in fake.calls if name == "cancel"] == ["cancel"]
        assert iteration.cost_usd == Decimal("0.05")

    async def test_a_session_whose_actor_lost_access_mid_check_still_stops_it(
        self, db, evidence, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        run = await _row(db, SkillImprovementRead.model_validate(run))
        run.actor_api_key_id = uuid.uuid4()
        await db.flush()

        await SkillImprovementService(db).advance(run.id, ctx.organization_id)

        assert (await _row(db, SkillImprovementRead.model_validate(run))).stop_reason == (
            "permission"
        )
        assert [name for name, _ in fake.calls if name == "cancel"] == ["cancel"]

    async def test_an_accepted_session_cannot_be_discarded(self, db, evidence, monkeypatch):
        _, run = await _with_result(db, await _owner(db), monkeypatch)
        ctx = await _owner_of(db, run)
        service = SkillImprovementService(db)
        await service.apply(ctx, run.skill_id, run.id, SkillImprovementApply(confirmed=True))

        with pytest.raises(ConcurrentChangeError):
            await service.discard(ctx, run.skill_id, run.id, ImprovementDiscard(confirmed=True))

    async def test_a_failed_check_is_retried_as_a_check_without_a_new_proposal(
        self, db, evidence, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        run = await _settle(db, run, status="cancelled")
        requests_before = await _requests_of(db, run)

        retried = await SkillImprovementService(db).retry(ctx, run.skill_id, run.id)

        assert (retried.status, retried.stage) == ("running", "evaluating")
        assert [name for name, _ in fake.calls if name == "start"] == ["start", "start"]
        assert await _requests_of(db, run) == requests_before
        fake.price = Decimal("5")
        await _settle(db, run, status="cancelled")
        with pytest.raises(PaymentRequiredError):
            await SkillImprovementService(db).retry(ctx, run.skill_id, run.id)

    async def test_cancelling_stops_an_unfinished_analysis_and_sets_aside_a_result(
        self, db, evidence, monkeypatch
    ):
        ctx = await _owner(db)
        service = SkillImprovementService(db)
        read = await service.start(ctx, (await _skill_on_main(db, ctx)).id, _start())
        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)

        await service.cancel(ctx, run.skill_id, run.id)
        fake, result = await _with_result(db, ctx, monkeypatch)
        await SkillImprovementService(db).cancel(ctx, result.skill_id, result.id)

        analysis = await db.get(AuthoringRequest, run.analysis_request_id)
        assert analysis is not None
        await db.refresh(analysis)
        assert (analysis.status, analysis.error) == ("failed", "The improvement session stopped.")
        assert "discard" in [name for name, _ in fake.calls]

    async def test_a_second_continue_reads_the_working_session_back(self, db, evidence):
        ctx = await _owner(db)
        run = await _at_understand(db, ctx, await _skill_on_main(db, ctx))
        await _continue(db, ctx, run)

        again = await SkillImprovementService(db).continue_run(
            ctx,
            run.skill_id,
            run.id,
            SkillContinuationConsent(
                confirmed=True,
                estimate_usd=Decimal("0"),
                candidate_hash="0" * 64,
                budget_usd=Decimal("1"),
            ),
        )

        assert (again.status, again.stage) == ("running", "proposing")

    async def test_waiting_for_you_fills_its_page_past_skills_the_reader_may_not_see(
        self, db, evidence, monkeypatch
    ):
        ctx = await _owner(db)
        visible = await _at_understand(db, ctx, await _skill_on_main(db, ctx))
        hidden: set[uuid.UUID] = set()
        for _ in range(21):
            skill = await _skill_on_main(db, ctx)
            hidden.add(skill.id)
            row = await _row(db, await SkillImprovementService(db).start(ctx, skill.id, _start()))
            row.status, row.stage = "waiting", "classifying"
        await db.flush()
        everything = await SkillImprovementService(db).awaiting(ctx)

        async def readable(db, ctx, skill, perm, *, resource_type):
            return skill.id not in hidden

        monkeypatch.setattr("app.services.skill_improvement.resolve_access", readable)
        listed = await SkillImprovementService(db).awaiting(ctx)

        assert [item.id for item in listed] == [visible.id]
        assert len(everything) == 20

    async def test_a_check_leaves_out_the_analysis_and_the_handed_over_conversations(
        self, db, evidence, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        clerk = (await SkillImprovementService(db).skill_agents.line_agents(skill, None))[0].agent
        handed = await _rated(db, ctx, clerk)
        analysed = uuid.uuid4()
        run = await _at_understand(db, ctx, skill)
        request = await db.get(AuthoringRequest, run.analysis_request_id)
        assert request is not None
        request.evidence = {"conversation_ids": [str(analysed)]}
        run.seed = {"run_ids": [str(handed.id)], "problems": [], "quotes": []}
        await db.flush()
        await _propose(db, ctx, run, [_body_edit("Be polite.", "Be kind.")])

        await _check_now(db, ctx, await _row(db, SkillImprovementRead.model_validate(run)))

        assert set(fake.excluded[-1]) == {_CONVERSATION, analysed, handed.conversation_id}

    async def test_a_finished_check_wakes_its_session(self, db, evidence, monkeypatch):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=run.id, number=1
        )
        assert iteration is not None and iteration.skill_check_id is not None
        woken: list[uuid.UUID] = []

        async def wake(self, run_id, *, organization_id):
            woken.append(run_id)

        monkeypatch.setattr(SkillImprovementService, "wake", wake)
        await SkillImprovementService(db).wake_for_check(
            iteration.skill_check_id, organization_id=ctx.organization_id
        )
        await SkillImprovementService(db).wake_for_check(
            uuid.uuid4(), organization_id=ctx.organization_id
        )

        assert woken == [run.id]


async def _owner_of(db: AsyncSession, run: SkillImprovementRun) -> AuthContext:
    return AuthContext(
        user_id=run.created_by_user_id, organization_id=run.organization_id, role="owner"
    )


async def _requests_of(db: AsyncSession, run: SkillImprovementRun) -> int:
    rows = await db.scalars(
        select(AuthoringRequest).where(AuthoringRequest.skill_improvement_run_id == run.id)
    )
    return len(list(rows))


class TestASessionsCheck:
    async def test_a_check_a_session_started_is_decided_and_stopped_only_through_it(
        self, db, evidence
    ):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        checks = SkillCheckService(db)

        async def owned(status: CheckStatus) -> SkillCheck:
            assert skill.latest_version_id is not None
            return await skill_check_repo.create(
                db,
                organization_id=ctx.organization_id,
                check=SkillCheck(
                    skill_id=skill.id,
                    base_version_id=skill.latest_version_id,
                    candidate_description="How refunds work.",
                    candidate_content="x",
                    candidate_hash="c" * 64,
                    description_changed=False,
                    mode="quick",
                    source=CheckSource.SESSION.value,
                    status=status.value,
                    verdict="passed" if status is CheckStatus.DONE else None,
                    expected_usd=Decimal(0),
                    at_most_usd=Decimal(0),
                ),
            )

        done, running = await owned(CheckStatus.DONE), await owned(CheckStatus.RUNNING)

        for refused in (
            checks.apply(ctx, skill.id, done.id, SkillCheckApply()),
            checks.fork(ctx, skill.id, done.id, SkillCheckFork(name="Returns")),
            checks.discard(ctx, skill.id, done.id),
            checks.cancel(ctx, skill.id, running.id),
        ):
            with pytest.raises(ConcurrentChangeError) as raised:
                await refused
            assert raised.value.code == "DECIDE_IN_SESSION"
            assert raised.value.details["check_id"] in (done.id, running.id)
        stopped = await checks.cancel(ctx, skill.id, running.id, from_session=True)
        discarded = await checks.discard(ctx, skill.id, done.id, from_session=True)
        still_running = await owned(CheckStatus.RUNNING)
        set_aside = await checks.discard(ctx, skill.id, still_running.id, from_session=True)

        assert (stopped.status, discarded.status) == ("cancelled", "discarded")
        assert set_aside.status == "discarded"

    async def test_a_finished_session_check_wakes_the_session_it_belongs_to(
        self, db, evidence, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=run.id, number=1
        )
        assert iteration is not None and iteration.skill_check_id is not None
        check = await db.get(SkillCheck, iteration.skill_check_id)
        assert check is not None
        woken: list[uuid.UUID] = []

        async def wake(self, run_id, *, organization_id):
            woken.append(run_id)

        monkeypatch.setattr(SkillImprovementService, "wake", wake)
        await SkillCheckService(db)._settle(check)

        assert check.status == "done" and woken == [run.id]


class TestReviewEdges:
    async def test_a_line_moving_after_the_check_finished_cancels_nothing(
        self, db, evidence, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=run.id, number=1
        )
        assert iteration is not None and iteration.skill_check_id is not None
        check = await db.get(SkillCheck, iteration.skill_check_id)
        assert check is not None
        check.status, check.verdict = "done", "passed"
        await SkillService(db).update(ctx, run.skill_id, SkillUpdate(content="Moved on."))

        await SkillImprovementService(db).advance(run.id, ctx.organization_id)

        assert (await _row(db, SkillImprovementRead.model_validate(run))).status == "stale"
        assert [name for name, _ in fake.calls if name == "cancel"] == []

    async def test_a_check_after_its_analysis_was_removed_still_leaves_out_the_proposals(
        self, db, evidence, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        run.analysis_request_id = None
        await db.flush()

        await _check_now(db, ctx, run)

        assert fake.excluded[-1] == [_CONVERSATION]

    async def test_waiting_for_you_lists_both_lines_of_one_skill(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        fork = await _fork(db, ctx, skill, "fork text")
        on_main = await _at_understand(db, ctx, skill)
        on_fork = await _row(
            db, await SkillImprovementService(db).start(ctx, skill.id, _start(fork_id=fork.id))
        )
        on_fork.status, on_fork.stage = "waiting", "classifying"
        await db.flush()

        listed = await SkillImprovementService(db).awaiting(ctx)

        assert {item.id for item in listed} == {on_main.id, on_fork.id}


class TestTheSessionOfACheck:
    async def test_a_sessions_check_names_its_session_when_read_and_when_refused(
        self, db, evidence, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        run = await _settle(db, run, status="done", verdict="passed")
        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=run.id, number=1
        )
        assert iteration is not None and iteration.skill_check_id is not None
        checks = SkillCheckService(db)

        read = await checks.read(ctx, run.skill_id, iteration.skill_check_id)
        with pytest.raises(ConcurrentChangeError) as refused:
            await checks.discard(ctx, run.skill_id, iteration.skill_check_id)

        assert read.session_id == run.id
        assert refused.value.code == "DECIDE_IN_SESSION"
        assert refused.value.details == {
            "check_id": iteration.skill_check_id,
            "session_id": run.id,
        }


class TestArchivedLines:
    async def test_the_next_step_on_a_fork_archived_since_changes_is_refused(
        self, db, evidence, monkeypatch
    ):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        fork = await _fork(db, ctx, skill)
        service = SkillImprovementService(db)
        read = await service.start(ctx, skill.id, _start(fork_id=fork.id))
        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)
        assert run.analysis_request_id is not None
        await _finish(
            db,
            run.analysis_request_id,
            {"problems": [{"title": "t", "summary": "", "cause": "skill", "run_ids": []}]},
        )
        await service.advance(read.id, ctx.organization_id)
        await _propose(db, ctx, await _row(db, read), [_body_edit("Be polite.", "Be kind.")])
        await SkillVersionService(db).archive_fork(ctx, skill.id, fork.id)

        with pytest.raises(ConcurrentChangeError) as refused:
            await service.estimate_continuation(ctx, skill.id, read.id, SkillContinue())

        assert refused.value.code == "LINE_MOVED"
        assert (
            await skill_improvement_repo.sessions_of_checks(
                db, [], organization_id=ctx.organization_id
            )
            == {}
        )


class TestApprovedFollowUps:
    async def test_the_platform_stops_a_sessions_check_whatever_the_person_may_read(
        self, db, evidence, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=run.id, number=1
        )
        assert iteration is not None and iteration.skill_check_id is not None
        check = await db.get(SkillCheck, iteration.skill_check_id)
        assert check is not None
        del fake

        await SkillCheckService(db).stop_for_session(check)

        assert check.status == "cancelled" and check.finished_at is not None

    async def test_a_session_stopped_on_a_moved_line_offers_no_try_again_and_ends(
        self, db, evidence
    ):
        ctx = await _owner(db)
        run = await _at_understand(db, ctx, await _skill_on_main(db, ctx))
        await _propose(db, ctx, run, [])
        await SkillService(db).update(ctx, run.skill_id, SkillUpdate(content="Moved on."))
        service = SkillImprovementService(db)

        read = await service.read(ctx, run.skill_id, run.id)
        await service.sweep()

        assert (read.status, read.can_restart) == ("stopped", False)
        assert (await _row(db, read)).status == "stale"

    async def test_retrying_and_checking_again_keep_how_the_check_measured(
        self, db, evidence, monkeypatch
    ):
        fake = _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run, mode="thorough")
        run = await _settle(db, run, status="cancelled")
        service = SkillImprovementService(db)

        retried = await service.retry(ctx, run.skill_id, run.id)
        run = await _settle(db, run, status="done", verdict="passed")
        rechecked = await _recheck(db, ctx, run)

        started = [
            data
            for name, (data, _) in ((name, value) for name, value in fake.calls if name == "start")
        ]
        assert [data.mode for data in started] == [CheckMode.THOROUGH] * 3
        assert retried.iterations[0].check_verdict is None
        assert rechecked.stage == "evaluating"

    async def test_cancelling_during_a_check_keeps_what_it_cost(self, db, evidence, monkeypatch):
        _checked(db, monkeypatch)
        ctx = await _owner(db)
        run = await _at_changes(db, ctx)
        await _check_now(db, ctx, run)
        cost = Decimal("0.07")
        monkeypatch.setattr(skill_improvement_repo, "check_cost", AsyncMock(return_value=cost))

        cancelled = await SkillImprovementService(db).cancel(ctx, run.skill_id, run.id)

        assert cancelled.iterations[0].cost_usd == cost


class TestAChosenHelper:
    async def test_every_step_runs_on_the_helper_the_session_was_started_with(self, db, evidence):
        ctx = await _owner(db)
        helper = await _published(
            db, ctx, name="Strict helper", spec={"name": "Strict helper"}, kind="improver"
        )
        skill = await _skill_on_main(db, ctx)
        service = SkillImprovementService(db)

        read = await service.start(ctx, skill.id, _start(improver_agent_id=helper.id))
        await service.advance(read.id, ctx.organization_id)
        run = await _row(db, read)
        assert run.analysis_request_id is not None
        analysis = await db.get(AuthoringRequest, run.analysis_request_id)

        assert read.improver_agent_id == helper.id == run.improver_agent_id
        assert analysis is not None and analysis.improver_agent_id == helper.id
        assert evidence["helpers"] == [helper.id, helper.id]

    @pytest.mark.security
    async def test_a_helper_of_another_organization_or_out_of_sight_is_missing(self, db, evidence):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        other = await _owner(db)
        elsewhere = await _published(
            db, other, name="Their helper", spec={"name": "Their helper"}, kind="improver"
        )
        helper = await _published(
            db, ctx, name="Strict helper", spec={"name": "Strict helper"}, kind="improver"
        )
        blind = replace(ctx, key_scopes=frozenset(Perm) - {Perm.AGENTS_VIEW})
        service = SkillImprovementService(db)

        with pytest.raises(NotFoundError):
            await service.estimate(
                ctx, skill.id, SkillImprovementTarget(improver_agent_id=elsewhere.id)
            )
        with pytest.raises(NotFoundError):
            await service.start(ctx, skill.id, _start(improver_agent_id=uuid.uuid4()))
        with pytest.raises(NotFoundError):
            await service.start(blind, skill.id, _start(improver_agent_id=helper.id))


class TestADecisionBesideTheSkillsDelete:
    async def test_a_decision_waits_for_the_delete_instead_of_deadlocking(
        self, db: AsyncSession, engine: AsyncEngine, evidence
    ):
        """Deleting a skill locks it and then cascades into its sessions; a session's
        decision locks the skill before the session too, so it waits and finds it gone."""
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        read = await SkillImprovementService(db).start(ctx, skill.id, _start())
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def deciding() -> None:
            async with factory() as session:
                service = SkillImprovementService(session)
                await service._editable_row(ctx, skill.id, read.id, lock=True)
                await skill_repo.lock(session, skill.id)

        task: asyncio.Task[None] | None = None
        async with factory() as deleting:
            try:
                await skill_repo.lock_for_delete(deleting, skill.id)
                task = asyncio.create_task(deciding())
                await _waiting_for_a_lock(factory, task)

                gone = await skill_repo.get(deleting, skill.id, organization_id=ctx.organization_id)
                assert gone is not None
                await asyncio.wait_for(skill_repo.delete(deleting, gone), 5)
                await deleting.commit()
                with pytest.raises(NotFoundError):
                    await task
                task = None
            finally:
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
