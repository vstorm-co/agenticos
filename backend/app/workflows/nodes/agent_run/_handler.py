"""`agent.run`: ask a published agent, at the exact version the step pins.

The step names an agent *and* one of its published versions, and there is no
way to say "whatever is published now": a workflow that was reviewed against
version 4 keeps running version 4 until someone edits the step. The run goes
through `AgentRunnerService` like every other surface's, so the agent's budget,
approvals, guardrails and run history are the ones it always has; the run is
stamped `surface=workflow` and acts as the workflow run's principal.

**An approval parks the node, and the wake resumes the same agent run.** When
the agent stops on an approval-gated tool, the handler reports the agent run it
is waiting on and returns `Waiting(reason="approval")`; once somebody decides,
the dispatcher calls it again with `resumed_agent_run_id`, and the handler
continues *that* run. Starting a new one would re-send the prompt and drop the
decision.

**A structured answer is checked before anything downstream reads it.** With
`structured_output_schema` set, the agent's final text must parse as JSON and
validate against that schema; if it does not, the node fails with
`STRUCTURED_OUTPUT_MISMATCH` and nothing after it runs.

Cost is reported to the workflow run as it lands on the agent run - for a
resumed run, only what the continuation added.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from jsonschema import exceptions as jsonschema_errors
from jsonschema import validators
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.session import get_worker_db_context
from app.repositories import agent_run as agent_run_repo
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService
from app.services.workflow_execution import context
from app.workflows.contracts.io import FileRef, SourceRef
from app.workflows.contracts.results import (
    Completed,
    Failed,
    NodeResult,
    Waiting,
    WorkflowError,
)

logger = logging.getLogger(__name__)

MAX_SOURCES = 50
"""The most passages one step hands an agent as context."""


class AgentVersionPin(BaseModel):
    """One agent, at one of its published versions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: UUID
    version_id: UUID


class AgentRunConfig(BaseModel):
    """Which agent version answers, and the shape its answer must have, if any."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: AgentVersionPin = Field(
        json_schema_extra={"x-resource": "agent"},
        description="The agent and the published version this step runs.",
    )
    structured_output_schema: dict[str, Any] | None = Field(
        default=None,
        description="A JSON Schema the agent's answer must be JSON for, checked before the next step.",
    )

    @field_validator("structured_output_schema")
    @classmethod
    def _a_schema(cls, schema: dict[str, Any] | None) -> dict[str, Any] | None:
        if schema is None:
            return None
        try:
            validators.validator_for(schema).check_schema(schema)
        except jsonschema_errors.SchemaError as exc:
            raise ValueError(f"This is not a valid JSON Schema: {exc.message}") from exc
        return schema


class AgentRunInput(BaseModel):
    """What the agent is asked, and the passages it may ground its answer in."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = Field(min_length=1, max_length=32_000)
    sources: tuple[SourceRef, ...] = Field(default=(), max_length=MAX_SOURCES)


class AgentRunOutput(BaseModel):
    """The agent's answer, the sources it was given, and its structured value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    sources: tuple[SourceRef, ...] = ()
    artifacts: tuple[FileRef, ...] = ()
    structured: dict[str, Any] | None = None
    agent_run_id: UUID | None = None


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse an agent version the graph's author cannot run."""
    if not isinstance(config, AgentRunConfig):
        return []
    try:
        await AgentRegistryService(db).get_pinned_spec(
            ctx, config.agent.agent_id, config.agent.version_id
        )
    except AppException as exc:
        return [("agent", exc.message)]
    return []


def _prompt(node_input: AgentRunInput) -> str:
    """The prompt, with its sources appended as numbered context to cite."""
    if not node_input.sources:
        return node_input.prompt
    passages = "\n\n".join(
        f"[{index}] {source.filename}"
        + (f", page {source.page}" if source.page is not None else "")
        + f"\n{source.content}"
        for index, source in enumerate(node_input.sources, start=1)
    )
    return (
        f"{node_input.prompt}\n\n"
        "Answer from the context below where it applies, citing it inline as [1], [2]:\n\n"
        f"{passages}"
    )


def _structured(text: str, schema: dict[str, Any]) -> dict[str, Any] | Failed:
    """The answer as a JSON object that satisfies `schema`, or why it is not one."""
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1] if "\n" in body else ""
        body = body.rsplit("```", 1)[0]
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return _mismatch("The answer is not JSON")
    if not isinstance(value, dict):
        return _mismatch("The answer is JSON but not an object")
    error = jsonschema_errors.best_match(
        validators.validator_for(schema)(schema).iter_errors(value)
    )
    if error is not None:
        # The path and the rule broken, not the message: it quotes the offending
        # value, and the value is the agent's answer.
        return _mismatch(
            "The answer does not match the schema",
            path="/".join(str(part) for part in error.absolute_path),
            rule=str(error.validator),
        )
    return value


def _mismatch(message: str, **details: Any) -> Failed:
    return Failed(
        error=WorkflowError(code="STRUCTURED_OUTPUT_MISMATCH", message=message, details=details)
    )


async def _cost_so_far(db: AsyncSession, agent_run_id: UUID, organization_id: UUID) -> Decimal:
    run = await agent_run_repo.get_run(db, agent_run_id, organization_id=organization_id)
    return run.cost_usd if run is not None else Decimal(0)


def _settled(
    run: AgentRun, text: str, config: AgentRunConfig, node_input: AgentRunInput
) -> NodeResult:
    """What the agent run's final status means for this node."""
    status = RunStatus(run.status)
    if status is RunStatus.AWAITING_APPROVAL:
        context.report_waiting_agent_run(run.id)
        return Waiting(reason="approval", resume_token=str(context.current().node_run_id))
    if status is RunStatus.BUDGET_EXCEEDED:
        return Failed(
            error=WorkflowError(
                code="AGENT_BUDGET_EXCEEDED",
                message=run.error or "The agent's budget is spent",
                details={"agent_run_id": str(run.id)},
            )
        )
    if status is RunStatus.GUARDRAIL_BLOCKED:
        return Failed(
            error=WorkflowError(
                code="AGENT_GUARDRAIL_BLOCKED",
                message=run.error or "A guardrail stopped the agent",
                details={"agent_run_id": str(run.id)},
            )
        )
    if status is not RunStatus.COMPLETED:
        return Failed(
            error=WorkflowError(
                code="AGENT_RUN_FAILED",
                message="The agent did not finish",
                details={"agent_run_id": str(run.id), "status": status.value},
            )
        )
    structured: dict[str, Any] | None = None
    if config.structured_output_schema is not None:
        checked = _structured(text, config.structured_output_schema)
        if isinstance(checked, Failed):
            return checked
        structured = checked
    return Completed[AgentRunOutput](
        output=AgentRunOutput(
            text=text, sources=node_input.sources, structured=structured, agent_run_id=run.id
        )
    )


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Run the pinned agent version, or continue the run it parked on."""
    if not isinstance(config, AgentRunConfig) or not isinstance(node_input, AgentRunInput):
        return Failed(
            error=WorkflowError(
                code="AGENT_NOT_CONFIGURED", message="This step needs an agent and a bound prompt"
            )
        )
    current = context.current()
    try:
        async with get_worker_db_context() as db:
            runner = AgentRunnerService(db)
            if current.resumed_agent_run_id is not None:
                before = await _cost_so_far(
                    db, current.resumed_agent_run_id, current.organization_id
                )
                segment = await runner.resume(current.auth, current.resumed_agent_run_id)
                text, run = segment.output, segment.run
            else:
                before = Decimal(0)
                text, run = await runner.execute(
                    current.auth,
                    config.agent.agent_id,
                    _prompt(node_input),
                    said=node_input.prompt,
                    surface=RunSurface.WORKFLOW,
                    version_id=config.agent.version_id,
                )
    except AppException as exc:
        return Failed(
            error=WorkflowError(code=exc.code, message=exc.message, details=exc.details or {})
        )
    except Exception:
        # A model provider's own text can carry a request URL with a key in it.
        logger.exception(
            "workflow_agent_run_failed", extra={"agent_id": str(config.agent.agent_id)}
        )
        return Failed(
            error=WorkflowError(
                code="AGENT_RUN_FAILED", message="The agent run stopped with an error"
            )
        )
    spent = run.cost_usd - before
    if spent > 0 or run.cost_is_partial:
        context.report_cost(max(spent, Decimal(0)), partial=run.cost_is_partial)
    return _settled(run, text, config, node_input)
