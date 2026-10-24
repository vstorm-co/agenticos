"""A model step's evals against a real Postgres: cases, tries, and how a try is judged.

Starting each case's test run is `WorkflowExecutionService.start` with a step -
**Test step**'s request, which `test_workflow_step_tests` and the facade's tests
cover. Here it is stood in for, so a case's run can be put in any state and the
judgement read back the way the editor reads it.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.resource_grant import Visibility
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_run import NodeAttempt, WorkflowRun, WorkflowRunMode
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow_eval import EvalCaseCreate, EvalExpectation
from app.services.workflow_evals import WorkflowEvalService, judge
from app.services.workflow_execution.exceptions import WorkflowBudgetReachedError
from app.workflows.graph.model import (
    MAX_PINNED_BYTES,
    Edge,
    NodeInstance,
    NodePosition,
    WorkflowGraph,
)
from tests.integration.workflow_run_support import seed_member

pytestmark = pytest.mark.anyio

TRIGGER, ASK, OUT = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _graph() -> WorkflowGraph:
    def node(node_id: uuid.UUID, definition_id: str, x: int) -> NodeInstance:
        return NodeInstance(
            id=node_id,
            definition_id=definition_id,
            definition_version=1,
            layout=NodePosition(x=x, y=0),
        )

    return WorkflowGraph(
        entry_node_id=TRIGGER,
        nodes=(
            node(TRIGGER, "trigger.manual", 0),
            node(ASK, "ai.classify", 1),
            node(OUT, "core.output", 2),
        ),
        edges=(
            Edge(
                id=uuid.uuid4(),
                source_node_id=TRIGGER,
                source_port="out",
                target_node_id=ASK,
                target_port="in",
            ),
            Edge(
                id=uuid.uuid4(),
                source_node_id=ASK,
                source_port="other",
                target_node_id=OUT,
                target_port="in",
            ),
        ),
    )


@pytest.fixture
async def owner(db: AsyncSession) -> AuthContext:
    principal, org = await seed_member(db)
    return AuthContext(user_id=principal.id, organization_id=org.id, role="owner")


@pytest.fixture
async def workflow(db: AsyncSession, owner: AuthContext) -> Workflow:
    row = Workflow(
        id=uuid.uuid4(),
        organization_id=owner.organization_id,
        owner_user_id=owner.subject_id,
        slug=f"wf-{uuid.uuid4().hex[:8]}",
        name="Support triage",
        status=WorkflowStatus.DRAFT.value,
        visibility=Visibility.ORG.value,
        draft_graph=_graph().model_dump(mode="json"),
    )
    db.add(row)
    await db.flush()
    return row


def _case(name: str = "Refund", kind: str = "equals", value: str = "billing", **rest: Any):
    return EvalCaseCreate(
        name=name,
        run_input={"message": "I want my money back"},
        outputs={TRIGGER: {"payload": {"message": "I want my money back"}, "triggered_by": "api"}},
        expectation=EvalExpectation(kind=kind, field=rest.pop("field", "category"), value=value),
        **rest,
    )


async def _run(db: AsyncSession, ctx: AuthContext, workflow: Workflow) -> WorkflowRun:
    """A test run of the step, as `start` would have admitted it."""
    return await workflow_run_repo.create_run(
        db,
        organization_id=ctx.organization_id,
        workflow_id=workflow.id,
        workflow_version_id=None,
        draft_graph_snapshot=workflow.draft_graph,
        mode=WorkflowRunMode.TEST.value,
        triggered_by="api",
        execution_principal_user_id=ctx.subject_id,
        budget_limit=None,
        node_count=2,
        deadline_at=None,
        root_run_id=None,
        causation_run_id=None,
        visited_trigger_ids=[],
        depth=0,
        started_at=datetime.now(UTC),
        run_input={},
    )


async def _ended(
    db: AsyncSession,
    run: WorkflowRun,
    *,
    status: str = "succeeded",
    output: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """End `run`, its model step having answered `output` - or failed with `error`."""
    step = await workflow_run_repo.create_node_run(
        db,
        organization_id=run.organization_id,
        workflow_run_id=run.id,
        node_instance_id=ASK,
        scope_path=[],
    )
    attempt_status = "failed" if error else "completed"
    result: dict[str, Any] = (
        {"status": "failed", "error": {"code": "MODEL_FAILED", "message": error}}
        if error
        else {"status": "completed", "output": output}
    )
    db.add(
        NodeAttempt(
            organization_id=run.organization_id,
            node_run_id=step.id,
            attempt_no=1,
            idempotency_key=f"k-{uuid.uuid4()}",
            retry_guarantee="idempotent",
            status=attempt_status,
            result=result,
            cost=Decimal("0.001"),
            started_at=datetime.now(UTC),
        )
    )
    run.status = status
    run.spent_cost = Decimal("0.001")
    run.ended_at = datetime.now(UTC)
    await db.flush()


def _starting(*runs: WorkflowRun | Exception) -> AsyncMock:
    """`start`, answering each case with the next run - or refusing it."""
    answers = [run if isinstance(run, Exception) else SimpleNamespace(id=run.id) for run in runs]
    return AsyncMock(side_effect=answers)


class TestCases:
    async def test_a_case_is_written_listed_and_removed(self, db, owner, workflow):
        service = WorkflowEvalService(db)

        written = await service.create_case(owner, workflow.id, ASK, _case())
        listed = await service.list_cases(owner, workflow.id, ASK)

        assert [case.name for case in listed.items] == ["Refund"]
        assert listed.items[0].outputs == {TRIGGER: _case().outputs[TRIGGER]}
        assert listed.latest is None
        await service.delete_case(owner, workflow.id, written.id)
        assert (await service.list_cases(owner, workflow.id, ASK)).items == []
        with pytest.raises(NotFoundError):
            await service.delete_case(owner, workflow.id, written.id)

    @pytest.mark.parametrize("node_id", [TRIGGER, uuid.uuid4()], ids=["no-model", "no-step"])
    async def test_only_a_step_that_asks_a_model_has_cases(self, db, owner, workflow, node_id):
        with pytest.raises(BadRequestError, match="asks a model"):
            await WorkflowEvalService(db).create_case(owner, workflow.id, node_id, _case())

    async def test_a_draft_with_no_steps_has_no_step_to_eval(self, db, owner, workflow):
        workflow.draft_graph = {}
        await db.flush()
        with pytest.raises(BadRequestError):
            await WorkflowEvalService(db).create_case(owner, workflow.id, ASK, _case())

    async def test_a_step_holds_a_bounded_number_of_cases(self, db, owner, workflow):
        service = WorkflowEvalService(db)
        with patch("app.services.workflow_evals.MAX_CASES", 1):
            await service.create_case(owner, workflow.id, ASK, _case())
            with pytest.raises(BadRequestError, match="at most 1"):
                await service.create_case(owner, workflow.id, ASK, _case("Second"))

    @pytest.mark.security
    async def test_another_organization_reaches_no_case(self, db, owner, workflow):
        stranger, elsewhere = await seed_member(db)
        other = AuthContext(user_id=stranger.id, organization_id=elsewhere.id, role="owner")
        with pytest.raises(NotFoundError):
            await WorkflowEvalService(db).list_cases(other, workflow.id, ASK)


class TestTheCaseRequest:
    def test_known_outputs_are_bounded_each_and_together(self):
        with pytest.raises(ValidationError, match="Pinned data may take at most"):
            EvalCaseCreate(
                name="Big",
                outputs={TRIGGER: {"text": "x" * MAX_PINNED_BYTES}},
                expectation=EvalExpectation(value="billing"),
            )
        half = {"text": "x" * (MAX_PINNED_BYTES // 2)}
        with pytest.raises(ValidationError, match="Known outputs may take at most"):
            EvalCaseCreate(
                name="Many",
                outputs={uuid.uuid4(): half for _ in range(10)},
                expectation=EvalExpectation(value="billing"),
            )


class TestTrying:
    @pytest.mark.security
    @pytest.mark.parametrize("precharged", [False, True])
    async def test_every_case_spends_the_shared_run_allowance(
        self, db, owner, workflow, precharged
    ):
        from app.services.rate_limit import Decision

        service = WorkflowEvalService(db)
        for name in ("First", "Second", "Third"):
            await service.create_case(owner, workflow.id, ASK, _case(name))
        run = await _run(db, owner, workflow)
        start = _starting(run)
        allowance = AsyncMock(
            side_effect=([Decision(True, 0)] if not precharged else [])
            + [Decision(False, 60), Decision(False, 60)]
        )
        with (
            patch.object(service.runs, "start", start),
            patch("app.services.workflow_evals.rate_limit.consume", allowance),
        ):
            tried = await service.try_cases(owner, workflow.id, ASK, first_case_charged=precharged)
        assert start.await_count == 1 and allowance.await_count + int(precharged) == 3
        assert [result.status for result in tried.results][1:] == ["refused", "refused"]
        assert all(
            call.kwargs["surface"] == "workflow_run"
            and call.kwargs["caller"] == f"user:{owner.subject_id}"
            for call in allowance.await_args_list
        )

    async def test_each_case_is_tried_as_a_test_of_the_step_and_judged(self, db, owner, workflow):
        service = WorkflowEvalService(db)
        await service.create_case(owner, workflow.id, ASK, _case("Refund"))
        await service.create_case(owner, workflow.id, ASK, _case("Bug", value="engineering"))
        await service.create_case(
            owner, workflow.id, ASK, _case("Broken", kind="contains", value="x")
        )
        await service.create_case(owner, workflow.id, ASK, _case("Over budget"))
        runs = [await _run(db, owner, workflow) for _ in range(3)]
        refused = WorkflowBudgetReachedError(budget=Decimal(1), spent=Decimal(1))
        start = _starting(*runs, refused)

        with patch.object(service.runs, "start", start):
            tried = await service.try_cases(owner, workflow.id, ASK)

        first = start.await_args_list[0]
        assert first.kwargs["mode"] is WorkflowRunMode.TEST
        assert first.kwargs["run_input"] == {"message": "I want my money back"}
        assert first.kwargs["step"].node_id == ASK and TRIGGER in first.kwargs["step"].outputs
        assert (tried.passed, tried.failed, tried.pending) == (0, 1, 3)
        assert tried.results[3].status == "refused"
        assert "monthly budget" in (tried.results[3].reason or "")

        await _ended(db, runs[0], output={"category": "Billing ", "reason": "money"})
        await _ended(db, runs[1], output={"category": "billing"})
        await _ended(db, runs[2], status="failed", error="The model is unavailable")
        judged = await service.get_try(owner, workflow.id, tried.id)

        assert [result.passed for result in judged.results] == [True, False, False, False]
        assert judged.results[1].actual == "billing"
        assert judged.results[2].reason == "The model is unavailable"
        assert (judged.passed, judged.failed, judged.pending) == (1, 3, 0)
        assert judged.cost_usd == pytest.approx(0.003)
        latest = (await service.list_cases(owner, workflow.id, ASK)).latest
        assert latest is not None and latest.id == tried.id

    async def test_a_run_that_ended_without_reaching_the_step_says_why(self, db, owner, workflow):
        service = WorkflowEvalService(db)
        await service.create_case(owner, workflow.id, ASK, _case())
        run = await _run(db, owner, workflow)
        with patch.object(service.runs, "start", _starting(run)):
            tried = await service.try_cases(owner, workflow.id, ASK)
        run.status = "failed"
        run.error = {"code": "X", "message": "The trigger refused the input"}
        await db.flush()

        (result,) = (await service.get_try(owner, workflow.id, tried.id)).results

        assert (result.passed, result.reason) == (False, "The trigger refused the input")

    async def test_a_removed_run_is_said_to_be_removed(self, db, owner, workflow):
        service = WorkflowEvalService(db)
        await service.create_case(owner, workflow.id, ASK, _case())
        run = await _run(db, owner, workflow)
        with patch.object(service.runs, "start", _starting(run)):
            tried = await service.try_cases(owner, workflow.id, ASK)
        await db.delete(run)
        await db.flush()

        (result,) = (await service.get_try(owner, workflow.id, tried.id)).results

        assert (result.status, result.passed) == ("removed", None)

    async def test_a_step_with_no_cases_has_nothing_to_try(self, db, owner, workflow):
        with pytest.raises(BadRequestError, match="Write a case"):
            await WorkflowEvalService(db).try_cases(owner, workflow.id, ASK)

    async def test_an_unknown_try_is_not_found(self, db, owner, workflow):
        with pytest.raises(NotFoundError):
            await WorkflowEvalService(db).get_try(owner, workflow.id, uuid.uuid4())


@pytest.mark.parametrize(
    ("kind", "field", "value", "output", "verdict"),
    [
        ("equals", "category", "billing", {"category": " Billing"}, (True, " Billing")),
        ("contains", "text", "refund", {"text": "A REFUND is due"}, (True, "A REFUND is due")),
        ("not_contains", "text", "sorry", {"text": "Sorry!"}, (False, "Sorry!")),
        ("equals", "structured.amount", "42", {"structured": {"amount": 42}}, (True, "42")),
        ("contains", "missing.path", "x", {"text": "x"}, (False, "")),
        ("contains", None, "billing", {"category": "billing"}, (True, '{"category": "billing"}')),
    ],
)
def test_an_answer_is_judged_by_the_path_and_the_kind(kind, field, value, output, verdict):
    assert judge(EvalExpectation(kind=kind, field=field, value=value), output) == verdict


@pytest.mark.security
@pytest.mark.parametrize("value", ["x" * 300_000, "bad\x00", "bad\ud800", float("nan")])
def test_an_eval_case_refuses_input_that_a_run_cannot_store(value):
    with pytest.raises(ValidationError):
        EvalCaseCreate(
            name="invalid", run_input={"input": value}, expectation=EvalExpectation(value="ok")
        )


@pytest.mark.security
def test_eval_input_budget_measures_compact_utf8_at_its_exact_boundary(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "WORKFLOW_RUN_MAX_INPUT_BYTES", 16)
    assert EvalCaseCreate(
        name="fits", run_input={"x": "😀😀"}, expectation=EvalExpectation(value="ok")
    ).run_input == {"x": "😀😀"}
    with pytest.raises(ValidationError):
        EvalCaseCreate(
            name="large", run_input={"x": "😀😀a"}, expectation=EvalExpectation(value="ok")
        )


def test_an_older_oversized_eval_remains_readable_for_removal():
    from app.schemas.workflow_eval import EvalCaseRead

    stored = EvalCaseRead(
        id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        name="older",
        run_input={"text": "x" * 300_000},
        expectation=EvalExpectation(value="ok"),
    )
    assert len(stored.run_input["text"]) == 300_000


@pytest.mark.parametrize("field", ["name", "expectation", "outputs"])
def test_new_eval_cases_reject_unstorable_text_outside_the_run_input(field):
    payload = {"name": "case", "expectation": {"value": "ok"}}
    payload[field] = (
        {"value": "bad\x00"}
        if field == "expectation"
        else {str(ASK): {"text": "bad\x00"}}
        if field == "outputs"
        else "bad\x00"
    )
    with pytest.raises(ValidationError):
        EvalCaseCreate.model_validate(payload)


@pytest.mark.security
async def test_concurrent_case_creators_share_the_case_ceiling(engine, monkeypatch):
    from app.repositories import workflow_eval as eval_repo

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.services.workflow_evals.MAX_CASES", 1)
    async with factory() as db:
        principal, org = await seed_member(db)
        ctx = AuthContext(user_id=principal.id, organization_id=org.id, role="owner")
        workflow = Workflow(
            id=uuid.uuid4(),
            organization_id=org.id,
            owner_user_id=principal.id,
            slug=f"cases-{uuid.uuid4().hex[:8]}",
            name="Concurrent cases",
            status=WorkflowStatus.DRAFT.value,
            visibility=Visibility.ORG.value,
            draft_graph=_graph().model_dump(mode="json"),
        )
        db.add(workflow)
        await db.commit()

    async def create(name: str) -> str:
        async with factory() as db:
            try:
                await WorkflowEvalService(db).create_case(ctx, workflow.id, ASK, _case(name))
                await db.commit()
                return "created"
            except BadRequestError:
                await db.rollback()
                return "refused"

    assert sorted(await asyncio.gather(create("one"), create("two"))) == ["created", "refused"]
    async with factory() as db:
        cases = await eval_repo.list_cases(db, **WorkflowEvalService._scope(workflow, ASK))
        assert len(cases) == 1
