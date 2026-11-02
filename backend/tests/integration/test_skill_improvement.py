"""A session on one line of a skill, step by step, against a real database.

What the improver reads and costs is fixed here - the evidence of a line and the
price of reading it - so each step's move is the service's own: queuing the
analysis, stopping at Understand, proposing, filtering to Changes, and every
refusal on the way.
"""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
    PaymentRequiredError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent_run import AgentRun
from app.db.models.authoring import AuthoringRequest, AuthoringStatus, HunkKind
from app.db.models.organization import OrganizationMember
from app.db.models.skill import Skill
from app.db.models.skill_improvement import SkillImprovementRun
from app.repositories import authoring_repo, skill_improvement_repo, skill_version_repo
from app.schemas.authoring import AuthoringEstimate, InstructionChange
from app.schemas.improvement import ChangeEdit, ImprovementDiscard, ImprovementSelection
from app.schemas.skill import SkillUpdate
from app.schemas.skill_improvement import (
    SkillContinuationConsent,
    SkillImprovementRead,
    SkillImprovementStart,
    SkillImprovementTarget,
)
from app.services import authoring_hunks
from app.services.authoring import AuthoringService
from app.services.authoring_evidence import EvidencePack, PackedRun
from app.services.skill_improvement import SkillImprovementService
from app.services.skill_versions import SkillVersionService
from app.services.skills import SkillService
from tests.integration.test_authoring import _member, _owner, _published
from tests.integration.test_skill_bindings import _fork, _serving, _skill, _spec

pytestmark = pytest.mark.anyio

_PRICE = Decimal("0.05")
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

    async def priced(self, ctx, pack):
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
    quote = await service.estimate_continuation(ctx, run.skill_id, run.id)
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
        evidence_conversation_ids=[],
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

        quote = await service.estimate_continuation(ctx, skill.id, run.id)
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
            await service.estimate_continuation(ctx, skill.id, started.id)
        run = await _at_understand(db, ctx, await _skill_on_main(db, ctx))
        quote = await service.estimate_continuation(ctx, run.skill_id, run.id)

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
            await service.estimate_continuation(ctx, skill.id, run.id)


class TestStops:
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
        quote = await service.estimate_continuation(ctx, skill.id, run.id)
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
        with pytest.raises(AuthorizationError):
            await SkillImprovementService(db).discard(
                builder, skill.id, run.id, ImprovementDiscard(confirmed=True)
            )


class TestListing:
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
        agent_id=agents[0].id,
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


class TestTheLinesEvidence:
    async def test_main_reads_its_versions_and_a_fork_without_its_own_reads_its_base(
        self, db, monkeypatch
    ):
        ctx = await _owner(db)
        skill = await _skill_on_main(db, ctx)
        fork = await _fork(db, ctx, skill)
        asked: list[list[uuid.UUID]] = []

        async def for_skill(self, ctx, skill_id, *, window_days, versions=None):
            asked.append(list(versions or []))
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
        with pytest.raises(NotFoundError):
            await service.line_for_session(
                ctx, SkillImprovementRun(skill_id=uuid.uuid4(), fork_id=None, window_days=30)
            )


async def _continue(db: AsyncSession, ctx: AuthContext, run: SkillImprovementRun) -> None:
    service = SkillImprovementService(db)
    quote = await service.estimate_continuation(ctx, run.skill_id, run.id)
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
