"""`WorkflowEvalService` - try a model step on the cases written for it.

A step that asks a model answers differently as its prompt, its model or its
instructions change, and nothing but trying it says whether it still answers
right. A case is one input the step should handle and what its answer should
then say; trying the step's cases starts one test run of the step per case -
**Test step**'s own request, so the run is checked, billed and audited like any
test run - and a case is judged by reading that run's answer for the step.

Writing cases and trying them needs `workflows:edit`, as testing the draft does:
a case holds test data, and trying one runs the draft.
"""

import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, BadRequestError, NotFoundError, RateLimitError
from app.core.permissions import AuthContext, Perm
from app.db.models.workflow import Workflow
from app.db.models.workflow_eval import WorkflowEvalRun, WorkflowStepEval
from app.db.models.workflow_run import WorkflowRunMode, WorkflowRunStatus
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_eval as eval_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow_eval import (
    MAX_CASES,
    EvalCaseCreate,
    EvalCaseList,
    EvalCaseRead,
    EvalExpectation,
    EvalResult,
    EvalRunRead,
)
from app.schemas.workflow_run import WorkflowStepTest
from app.services import rate_limit
from app.services.access import WORKFLOW, resolve_access
from app.services.workflow_execution.facade import WorkflowExecutionService, node_run_read
from app.workflows.graph.model import WorkflowGraph

MODEL_STEPS = frozenset(
    {
        "agent.run",
        "ai.prompt",
        "ai.classify",
        "ai.extract",
        "ai.rewrite",
        "decide.choose",
        "decide.yes_no",
        "decide.score",
    }
)
"""The steps whose answer a model writes - the ones evals are for."""

_SHOWN = 500
"""How much of an answer a result shows: enough to see what it said."""


def _at(output: dict[str, Any], field: str | None) -> Any:
    """The value at a dotted path into a step's output, or `None` past its end."""
    if field is None:
        return output
    value: Any = output
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def judge(expectation: EvalExpectation, output: dict[str, Any]) -> tuple[bool, str]:
    """Whether `output` says what `expectation` asks, and what it said there."""
    value = _at(output, expectation.field)
    actual = "" if value is None else _as_text(value)
    said, wanted = actual.strip().casefold(), expectation.value.strip().casefold()
    if expectation.kind == "equals":
        passed = said == wanted
    elif expectation.kind == "contains":
        passed = wanted in said
    else:
        passed = wanted not in said
    return passed, actual[:_SHOWN]


class WorkflowEvalService:
    """Write a model step's cases, try them, and read how a try went."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runs = WorkflowExecutionService(db)

    async def list_cases(self, ctx: AuthContext, workflow_id: UUID, node_id: UUID) -> EvalCaseList:
        """The step's cases, and how its latest try went.

        Raises:
            NotFoundError: The workflow is out of reach, or this caller may not edit it.
        """
        workflow = await self._workflow(ctx, workflow_id)
        scope = self._scope(workflow, node_id)
        cases = await eval_repo.list_cases(self.db, **scope)
        latest = await eval_repo.latest_run(self.db, **scope)
        return EvalCaseList(
            items=[_case_read(case) for case in cases],
            latest=None if latest is None else await self._judged(latest),
        )

    async def create_case(
        self, ctx: AuthContext, workflow_id: UUID, node_id: UUID, data: EvalCaseCreate
    ) -> EvalCaseRead:
        """A new case for the step.

        The workflow row serializes case count and position allocation against
        other creators and draft edits.

        Raises:
            NotFoundError: As `list_cases`.
            BadRequestError: The draft has no such step, it asks no model, or it
                already holds `MAX_CASES` cases.
        """
        workflow = await self._workflow(ctx, workflow_id, lock=True)
        self._model_step(workflow, node_id)
        scope = self._scope(workflow, node_id)
        if await eval_repo.count_cases(self.db, **scope) >= MAX_CASES:
            raise BadRequestError(
                message=f"A step holds at most {MAX_CASES} eval cases",
                details={"node_id": str(node_id)},
            )
        case = await eval_repo.create_case(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow.id,
            node_instance_id=node_id,
            name=data.name,
            position=await eval_repo.last_position(self.db, **scope) + 1,
            run_input=data.run_input,
            outputs={str(step): output for step, output in data.outputs.items()},
            expectation=data.expectation.model_dump(mode="json"),
            created_by_user_id=ctx.subject_id,
        )
        return _case_read(case)

    async def delete_case(self, ctx: AuthContext, workflow_id: UUID, case_id: UUID) -> None:
        """Remove a case. Tries already made keep what it said then.

        Raises:
            NotFoundError: The workflow or the case is out of reach.
        """
        workflow = await self._workflow(ctx, workflow_id)
        case = await eval_repo.get_case(
            self.db, case_id, organization_id=ctx.organization_id, workflow_id=workflow.id
        )
        if case is None:
            raise NotFoundError(message="Eval case not found", details={"eval_id": str(case_id)})
        await eval_repo.delete_case(self.db, case=case)

    async def try_cases(
        self,
        ctx: AuthContext,
        workflow_id: UUID,
        node_id: UUID,
        *,
        first_case_charged: bool = False,
    ) -> EvalRunRead:
        """Start a test run of the step for each of its cases.

        A case whose run cannot start - the organization's work is in flight, the
        workflow's monthly budget is spent, its input no longer fits - is recorded
        as refused with the reason, and the others still start.

        Raises:
            NotFoundError: As `list_cases`.
            BadRequestError: The draft has no such step, it asks no model, or it
                has no cases to try.
        """
        workflow = await self._workflow(ctx, workflow_id)
        self._model_step(workflow, node_id)
        cases = await eval_repo.list_cases(self.db, **self._scope(workflow, node_id))
        if not cases:
            raise BadRequestError(
                message="Write a case before trying the step", details={"node_id": str(node_id)}
            )
        tried: list[dict[str, Any]] = []
        for index, case in enumerate(cases):
            entry: dict[str, Any] = {
                "eval_id": str(case.id),
                "name": case.name,
                "expectation": case.expectation,
                "workflow_run_id": None,
                "refused": None,
            }
            try:
                if index != 0 or not first_case_charged:
                    decision = await rate_limit.consume(
                        surface="workflow_run",
                        caller=f"user:{ctx.subject_id}",
                        limit=rate_limit.run_limit(),
                    )
                    if not decision.allowed:
                        raise RateLimitError(
                            message="Too many workflow runs in the last minute. Wait and try again.",
                            details={"retry_after_seconds": decision.retry_after_seconds},
                        )
                run = await self.runs.start(
                    ctx,
                    workflow.id,
                    mode=WorkflowRunMode.TEST,
                    run_input=case.run_input,
                    step=WorkflowStepTest(
                        node_id=node_id,
                        outputs={UUID(step): output for step, output in case.outputs.items()},
                    ),
                )
                entry["workflow_run_id"] = str(run.id)
            except AppException as exc:
                entry["refused"] = exc.message
            tried.append(entry)
        run_row = await eval_repo.create_run(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow.id,
            node_instance_id=node_id,
            started_by_user_id=ctx.subject_id,
            cases=tried,
        )
        return await self._judged(run_row)

    async def get_try(self, ctx: AuthContext, workflow_id: UUID, eval_run_id: UUID) -> EvalRunRead:
        """A try of a step's cases, judged as its runs stand now.

        Raises:
            NotFoundError: The workflow or the try is out of reach.
        """
        workflow = await self._workflow(ctx, workflow_id)
        run = await eval_repo.get_run(
            self.db, eval_run_id, organization_id=ctx.organization_id, workflow_id=workflow.id
        )
        if run is None:
            raise NotFoundError(
                message="Eval run not found", details={"eval_run_id": str(eval_run_id)}
            )
        return await self._judged(run)

    async def _judged(self, eval_run: WorkflowEvalRun) -> EvalRunRead:
        results = [await self._result(eval_run, entry) for entry in eval_run.cases]
        return EvalRunRead(
            id=eval_run.id,
            node_instance_id=eval_run.node_instance_id,
            created_at=eval_run.created_at,
            results=results,
            passed=sum(1 for result in results if result.passed is True),
            failed=sum(1 for result in results if result.passed is False),
            pending=sum(1 for result in results if result.passed is None),
            cost_usd=sum(result.cost_usd for result in results),
        )

    async def _result(self, eval_run: WorkflowEvalRun, entry: dict[str, Any]) -> EvalResult:
        """One case as its run stands: still going, answered, or failed without one."""
        eval_id, name = UUID(entry["eval_id"]), str(entry["name"])
        if entry["workflow_run_id"] is None:
            return EvalResult(
                eval_id=eval_id, name=name, status="refused", passed=False, reason=entry["refused"]
            )
        run_id = UUID(entry["workflow_run_id"])
        run = await workflow_run_repo.get_run(
            self.db, run_id, organization_id=eval_run.organization_id
        )
        if run is None:
            return EvalResult(
                eval_id=eval_id,
                name=name,
                workflow_run_id=run_id,
                status="removed",
                reason="The run was removed",
            )
        if not WorkflowRunStatus(run.status).is_terminal:
            return EvalResult(
                eval_id=eval_id,
                name=name,
                workflow_run_id=run.id,
                status=run.status,
                cost_usd=float(run.spent_cost),
            )
        passed, actual, reason = await self._verdict(eval_run, entry, run.id)
        return EvalResult(
            eval_id=eval_id,
            name=name,
            workflow_run_id=run.id,
            status=run.status,
            passed=passed,
            actual=actual,
            reason=reason
            if reason is not None
            else None
            if passed
            else (run.error or {}).get("message"),
            cost_usd=float(run.spent_cost),
        )

    async def _verdict(
        self, eval_run: WorkflowEvalRun, entry: dict[str, Any], run_id: UUID
    ) -> tuple[bool, str | None, str | None]:
        """Whether an ended run's answer for the step passed, what it said, and - when
        it gave none - why."""
        steps = await workflow_run_repo.list_node_runs_of(
            self.db, workflow_run_id=run_id, node_instance_ids=[eval_run.node_instance_id]
        )
        attempts = await workflow_run_repo.list_attempts_of(
            self.db, node_run_ids=[step.id for step in steps]
        )
        reads = [
            node_run_read(step, [one for one in attempts if one.node_run_id == step.id])
            for step in steps
        ]
        output = next((read.output for read in reads if read.output is not None), None)
        if output is None:
            error = next((read.error for read in reads if read.error), None)
            message = error.get("message") if isinstance(error, dict) else None
            return False, None, message
        passed, actual = judge(EvalExpectation.model_validate(entry["expectation"]), output)
        return passed, actual, None

    async def _workflow(
        self, ctx: AuthContext, workflow_id: UUID, *, lock: bool = False
    ) -> Workflow:
        read = workflow_repo.get_for_update if lock else workflow_repo.get
        workflow = await read(self.db, workflow_id, organization_id=ctx.organization_id)
        if workflow is None or not await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_EDIT, resource_type=WORKFLOW
        ):
            raise NotFoundError(message="Workflow not found", details={"workflow_id": workflow_id})
        return workflow

    @staticmethod
    def _model_step(workflow: Workflow, node_id: UUID) -> None:
        """Refuse a step the draft does not have, or one that asks no model."""
        graph = WorkflowGraph.model_validate(
            workflow.draft_graph or {"nodes": [], "entry_node_id": node_id}
        )
        node = graph.node_by_id.get(node_id)
        if node is None or node.definition_id not in MODEL_STEPS:
            raise BadRequestError(
                message="Evals are for a step of the draft that asks a model",
                details={"node_id": str(node_id)},
            )

    @staticmethod
    def _scope(workflow: Workflow, node_id: UUID) -> dict[str, UUID]:
        return {
            "organization_id": workflow.organization_id,
            "workflow_id": workflow.id,
            "node_instance_id": node_id,
        }


def _case_read(case: WorkflowStepEval) -> EvalCaseRead:
    return EvalCaseRead(
        id=case.id,
        node_instance_id=case.node_instance_id,
        name=case.name,
        run_input=case.run_input,
        outputs={UUID(step): output for step, output in case.outputs.items()},
        expectation=EvalExpectation.model_validate(case.expectation),
        created_at=case.created_at,
    )
