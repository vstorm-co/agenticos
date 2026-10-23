"""The workflow tools: see which workflows this agent may start, start one, read how it went.

A workflow is a process somebody built and published - a lead's follow-up, a
refund, a report. Giving it to an agent as a tool means the agent decides *when*
to run it and with what, while *what it does* stays the reviewed, versioned graph
rather than steps the model improvises.

Every start goes through `WorkflowExecutionService.start` - the request the API
and the console make - as the member the run acts for, so their access, the
input the workflow declares, budgets and admission quotas all hold. The run then
goes on in the workflow worker; `run_workflow` waits for it up to the binding's
`wait_seconds` and otherwise hands back the run's id for `get_workflow_run`.

An agent running as a workflow's own step starts nothing: a workflow calls
another with a `workflow.run` step, which keeps the chain of calls and its limits.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities._failures import steer
from app.agents.deps import AgentDeps
from app.core.exceptions import AppException
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_run import WorkflowRunTrigger
from app.db.session import get_db_context
from app.repositories import workflow as workflow_repo
from app.schemas.workflow_run import WorkflowRunRead
from app.services.access import WORKFLOW, acting_member, resolve_access
from app.services.workflow_execution.facade import WorkflowExecutionService
from app.workflows.triggers import BY_HAND, DECLARES_FIELDS, WORKFLOW_CALL

POLL_SECONDS = 1.0
"""How often a waiting `run_workflow` looks at the run again."""

_STARTABLE = frozenset({*BY_HAND, WORKFLOW_CALL})
"""The live triggers an agent may start: by hand or the API, or published to be called."""

_INPUT_ERRORS = frozenset({"WORKFLOW_RUN_INPUT_INVALID", "WORKFLOW_RUN_INPUT_TOO_LARGE"})


class _Refused(Exception):
    """A start or a read the configuration, the membership or the workflow refuses."""


def _as_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _live_version(workflow: Workflow) -> UUID | None:
    """The version an agent may start, or `None` when it may start none."""
    if workflow.status == WorkflowStatus.ARCHIVED.value:
        return None
    if workflow.live_trigger is not None and workflow.live_trigger not in _STARTABLE:
        return None
    return workflow.current_version_id


async def _inputs(db: AsyncSession, workflow: Workflow, version_id: UUID) -> list[dict[str, Any]]:
    """The fields the version's entry declares, as the model reads them."""
    version = await workflow_repo.get_version(
        db, version_id, organization_id=workflow.organization_id
    )
    graph = version.graph if version is not None else {}
    entry = next(
        (node for node in graph.get("nodes", []) if node.get("id") == graph.get("entry_node_id")),
        None,
    )
    if entry is None or entry.get("definition_id") not in DECLARES_FIELDS:
        return []
    return [
        {
            key: field[key]
            for key in ("name", "type", "required", "description", "options")
            if field.get(key) not in (None, [])
        }
        for field in (entry.get("config") or {}).get("fields", [])
    ]


def _run(run: WorkflowRunRead) -> str:
    """A run as the model reads it: where it stands, and what it answered or why not."""
    shown: dict[str, Any] = {"run_id": str(run.id), "status": run.status.value}
    if run.output is not None:
        shown["output"] = run.output
    if run.error is not None:
        shown["error"] = {key: run.error.get(key) for key in ("code", "message")}
    if not run.status.is_terminal:
        shown["note"] = "Still running. Read it again later with get_workflow_run."
    return _as_json(shown)


def build_workflows_toolset(
    *, workflow_ids: tuple[UUID, ...], wait_seconds: int
) -> FunctionToolset[AgentDeps]:
    """The workflow tools for one binding's workflows."""
    toolset: FunctionToolset[AgentDeps] = FunctionToolset()
    allowed = frozenset(workflow_ids)

    async def act[T](
        ctx: RunContext[AgentDeps], work: Callable[[AsyncSession, AuthContext], Awaitable[T]]
    ) -> T | str:
        """`work`'s result, done as the run's member in a session of its own - or the
        refusal, as the text the model reads."""
        try:
            async with get_db_context() as db:
                auth = await acting_member(db, ctx.deps.organization_id, ctx.deps.user_id)
                if auth is None:
                    return "Workflows can only be started for a member of an organization."
                return await work(db, auth)
        except _Refused as refused:
            return str(refused)
        except AppException as exc:
            if exc.code in _INPUT_ERRORS:
                return steer(
                    ctx, f"The input does not fit the workflow: {exc.message} {exc.details}"
                )
            return f"Refused ({exc.code}): {exc.message}."

    async def reachable(db: AsyncSession, auth: AuthContext, workflow_id: UUID) -> Workflow:
        if workflow_id not in allowed:
            raise _Refused("This agent may not start that workflow. Use one from list_workflows.")
        workflow = await workflow_repo.get(db, workflow_id, organization_id=auth.organization_id)
        if workflow is None or not await resolve_access(
            db, auth, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
        ):
            raise _Refused(
                "That workflow is gone, or the member this agent acts for cannot run it."
            )
        return workflow

    async def read(ctx: RunContext[AgentDeps], run_id: UUID) -> WorkflowRunRead | str:
        async def work(db: AsyncSession, auth: AuthContext) -> WorkflowRunRead:
            run = await WorkflowExecutionService(db).get(auth, run_id)
            await reachable(db, auth, run.workflow_id)
            return run

        return await act(ctx, work)

    @toolset.tool
    async def list_workflows(ctx: RunContext[AgentDeps]) -> str:
        """List the workflows this agent may start, with what each needs as input.

        Use first, to choose a workflow and to learn the input fields it asks for.

        Returns:
            A JSON list of `{id, name, description, input}`, where `input` lists each
            field's `name`, `type`, whether it is `required`, and a choice's
            `options`. A workflow that is not published, archived, starts some other
            way, or that the member this agent acts for cannot run is left out.
        """

        async def work(db: AsyncSession, auth: AuthContext) -> str:
            found: list[dict[str, Any]] = []
            for workflow_id in workflow_ids:
                workflow = await workflow_repo.get(
                    db, workflow_id, organization_id=auth.organization_id
                )
                version_id = None if workflow is None else _live_version(workflow)
                if (
                    workflow is None
                    or version_id is None
                    or not await resolve_access(
                        db, auth, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
                    )
                ):
                    continue
                found.append(
                    {
                        "id": str(workflow.id),
                        "name": workflow.name,
                        "description": workflow.description,
                        "input": await _inputs(db, workflow, version_id),
                    }
                )
            return _as_json(found)

        return await act(ctx, work)

    @toolset.tool
    async def run_workflow(
        ctx: RunContext[AgentDeps],
        workflow_id: UUID,
        fields: Annotated[
            dict[str, Any] | None,
            Field(description="The workflow's input fields by name, as list_workflows names them"),
        ] = None,
        wait: Annotated[
            bool,
            Field(description="Wait for the workflow to finish and read its answer. Usually true"),
        ] = True,
    ) -> str:
        """Start one of this agent's workflows, and wait for what it answers.

        Use when a request is exactly what a workflow does - the workflow carries the
        process out, with its own steps, approvals and limits. Call list_workflows
        first for its id and input.

        Args:
            workflow_id: The workflow's id, from list_workflows.
            fields: Its input fields by name.
            wait: Whether to wait for it to finish.

        Returns:
            JSON `{run_id, status}`, with `output` once it succeeded or `error` once
            it failed. A run still going when the wait ends says so; read it again
            with get_workflow_run.
        """

        async def work(db: AsyncSession, auth: AuthContext) -> WorkflowRunRead:
            if ctx.deps.run_id is not None:
                run = await db.get(AgentRun, ctx.deps.run_id)
                if run is not None and run.surface == RunSurface.WORKFLOW.value:
                    raise _Refused(
                        "An agent running as a workflow's step starts no workflow; "
                        "a workflow.run step calls one."
                    )
            if ctx.deps.run_person is None:
                raise _Refused("Workflows can only be started by a run acting for a member.")
            workflow = await reachable(db, auth, workflow_id)
            if _live_version(workflow) is None:
                raise _Refused(
                    "That workflow is not published to start by hand, by the API or by a call."
                )
            return await WorkflowExecutionService(db).start(
                auth,
                workflow.id,
                triggered_by=WorkflowRunTrigger.AGENT,
                run_input=fields or {},
                impersonated=ctx.deps.impersonated,
            )

        run = await act(ctx, work)
        deadline = asyncio.get_running_loop().time() + wait_seconds
        # Read again in a session of its own each time: the worker writes the run.
        while (
            wait
            and not isinstance(run, str)
            and not run.status.is_terminal
            and asyncio.get_running_loop().time() < deadline
        ):
            await asyncio.sleep(POLL_SECONDS)
            run = await read(ctx, run.id)
        return run if isinstance(run, str) else _run(run)

    @toolset.tool
    async def get_workflow_run(ctx: RunContext[AgentDeps], run_id: UUID) -> str:
        """Read how a workflow run this agent started stands now.

        Use for a run run_workflow left still going.

        Args:
            run_id: The run's id, from run_workflow.

        Returns:
            JSON `{run_id, status}`, with `output` once it succeeded or `error` once
            it failed.
        """
        run = await read(ctx, run_id)
        return run if isinstance(run, str) else _run(run)

    return toolset
