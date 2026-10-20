"""`agent.run`: ask an agent - one from the catalog, or one configured in the step.

**A catalog agent is pinned.** The step names an agent *and* one of its
published versions, and there is no way to say "whatever is published now": a
workflow that was reviewed against version 4 keeps running version 4 until
someone edits the step.

**An agent configured here is the workflow's own.** Its spec - model,
instructions, capabilities, knowledge, MCP servers - is the step's `inline`
configuration, versioned with the graph. The step's first run creates it and a
changed spec publishes a version first, checked as publishing an agent is (see
`app/services/workflow_agents.py`); it never appears in the catalog.

Either way the run goes through `AgentRunnerService` like every other surface's,
so the agent's budget, approvals, guardrails and run history are the ones it
always has; the run is stamped `surface=workflow` and acts as the workflow
run's principal. `max_cost_usd` is a ceiling on one execution of the step,
checked before every model request beside the agent's and the organization's.

**An approval parks the node, and the wake resumes the same agent run.** When
the agent stops on an approval-gated tool, the handler reports the agent run it
is waiting on and returns `Waiting(reason="approval")`; once somebody decides,
the dispatcher calls it again with `resumed_agent_run_id`, and the handler
continues *that* run. Starting a new one would re-send the prompt and drop the
decision.

**A structured answer is asked for, not parsed out of prose.** With
`structured_output_schema` set, the agent is run with that schema in place of
its own `output_schema`: the model answers with an object of that shape, and is
sent back to fix one that breaks it. An agent with an `output_schema` of its own
hands its object on the same way. The object is checked against the schema once
more before anything downstream reads it, and a node whose agent answered no
object, or one that does not fit, fails with `STRUCTURED_OUTPUT_MISMATCH`.

Cost is reported to the workflow run as it lands on the agent run - for a
resumed run, only what the continuation added.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from jsonschema import exceptions as jsonschema_errors
from jsonschema import validators
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_ai.messages import BinaryContent
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, checked_output_schema
from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.session import get_worker_db_context
from app.repositories import agent_run as agent_run_repo
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService
from app.services.workflow_agents import WorkflowAgentService
from app.services.workflow_execution import context
from app.services.workflow_execution.errors import workflow_error
from app.workflows import files
from app.workflows.contracts.io import FileRef, SourceRef
from app.workflows.contracts.results import (
    Completed,
    Failed,
    NodeResult,
    Waiting,
    WorkflowError,
)
from app.workflows.nodes._model_step import outcome

logger = logging.getLogger(__name__)

MAX_SOURCES = 50
"""The most passages one step hands an agent as context."""

MAX_ATTACHMENTS = 10
"""The most images one step shows an agent."""

MAX_ATTACHMENT_BYTES = 20_000_000
"""The largest image one step shows an agent - the size vision APIs take inline."""

_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})


class AgentVersionPin(BaseModel):
    """One agent, at one of its published versions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: UUID
    version_id: UUID


class AgentRunConfig(BaseModel):
    """Which agent answers - pinned from the catalog or configured here - and how."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: AgentVersionPin | None = Field(
        default=None,
        json_schema_extra={"x-resource": "agent"},
        description="An agent from the catalog, and the published version this step runs.",
    )
    inline: AgentSpec | None = Field(
        default=None,
        json_schema_extra={"x-agent-spec": True},
        description=(
            "An agent configured in this step - model, instructions, capabilities, "
            "knowledge and MCP servers - versioned with the workflow."
        ),
    )
    max_cost_usd: float | None = Field(
        default=None,
        title="Max cost (USD)",
        gt=0,
        le=1000,
        description=(
            "The most one execution of this step may spend on model requests, in USD. "
            "Empty leaves only the agent's, the workflow's and the organization's limits."
        ),
    )
    structured_output_schema: dict[str, Any] | None = Field(
        default=None,
        description=(
            "The JSON Schema of an object the agent answers with, in place of its own "
            "answer format. Empty keeps the agent's."
        ),
    )

    _a_schema = field_validator("structured_output_schema")(checked_output_schema)

    @model_validator(mode="after")
    def _one_agent(self) -> AgentRunConfig:
        if (self.agent is None) == (self.inline is None):
            raise ValueError("Pick an agent from the catalog or configure one in this step")
        return self


class AgentRunInput(BaseModel):
    """What the agent is asked, and the passages it may ground its answer in."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = Field(min_length=1, max_length=32_000)
    sources: tuple[SourceRef, ...] = Field(default=(), max_length=MAX_SOURCES)
    attachments: tuple[FileRef, ...] = Field(
        default=(),
        max_length=MAX_ATTACHMENTS,
        description="Images from the run's files, shown to the agent as pictures.",
    )


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
    """Refuse an agent version the graph's author cannot run, or a spec they could
    not publish."""
    if not isinstance(config, AgentRunConfig):
        return []
    if config.inline is not None:
        problems = await WorkflowAgentService(db).problems(ctx, config.inline)
        return [("inline", problem) for problem in problems]
    if config.agent is None:  # pragma: no cover - `_one_agent` holds one of the two
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


def _structured(answer: dict[str, Any] | None, schema: dict[str, Any]) -> dict[str, Any] | Failed:
    """The agent's object if it satisfies `schema`, or why it does not."""
    if answer is None:
        return _mismatch("The agent answered in text, not with an object")
    error = jsonschema_errors.best_match(
        validators.validator_for(schema)(schema).iter_errors(answer)
    )
    if error is not None:
        # The path and the rule broken, not the message: it quotes the offending
        # value, and the value is the agent's answer.
        return _mismatch(
            "The answer does not match the schema",
            path="/".join(str(part) for part in error.absolute_path),
            rule=str(error.validator),
        )
    return answer


def _mismatch(message: str, **details: Any) -> Failed:
    return Failed(
        error=WorkflowError(code="STRUCTURED_OUTPUT_MISMATCH", message=message, details=details)
    )


async def _cost_so_far(db: AsyncSession, agent_run_id: UUID, organization_id: UUID) -> Decimal:
    run = await agent_run_repo.get_run(db, agent_run_id, organization_id=organization_id)
    return run.cost_usd if run is not None else Decimal(0)


def _settled(
    run: AgentRun,
    text: str,
    answer: dict[str, Any] | None,
    config: AgentRunConfig,
    node_input: AgentRunInput,
) -> NodeResult:
    """What the agent run's final status means for this node."""
    if RunStatus(run.status) is RunStatus.AWAITING_APPROVAL:
        context.report_waiting_agent_run(run.id)
        return Waiting(reason="approval", resume_token=str(context.current().node_run_id))
    failed = outcome(run)
    if failed is not None:
        return failed
    structured = answer
    if config.structured_output_schema is not None:
        checked = _structured(answer, config.structured_output_schema)
        if isinstance(checked, Failed):
            return checked
        structured = checked
    return Completed[AgentRunOutput](
        output=AgentRunOutput(
            text=text, sources=node_input.sources, structured=structured, agent_run_id=run.id
        )
    )


async def _images(refs: tuple[FileRef, ...]) -> list[BinaryContent] | Failed:
    """The run's image files as content a model can look at, never a URL it cannot open.

    Only images: a document is read with `text.extract` first, and a type the
    step cannot show fails here rather than being dropped without a word.
    """
    images: list[BinaryContent] = []
    for ref in refs:
        stored = await files.load(ref, max_bytes=MAX_ATTACHMENT_BYTES)
        if isinstance(stored, Failed):
            return stored
        if stored.content_type not in _IMAGE_TYPES:
            return files.failed(
                "UNSUPPORTED_ATTACHMENT_TYPE",
                f"An agent is shown PNG, JPEG, WebP or GIF images, not {stored.content_type} - "
                "extract a document's text with an Extract text step first",
                content_type=stored.content_type,
            )
        images.append(BinaryContent(data=stored.data, media_type=stored.content_type))
    return images


async def _pinned(db: AsyncSession, config: AgentRunConfig) -> tuple[UUID, UUID] | Failed:
    """The agent and version this step runs: the catalog pin, or the version of the
    agent configured here that matches its spec, published first if it changed."""
    if config.inline is None:
        if config.agent is None:  # pragma: no cover - `_one_agent` holds one of the two
            raise AssertionError("an agent.run config with no agent")
        return config.agent.agent_id, config.agent.version_id
    current = context.current()
    if current.workflow_id is None:
        return Failed(
            error=WorkflowError(
                code="AGENT_NOT_CONFIGURED",
                message="An agent configured in a step runs only as part of its workflow",
            )
        )
    return await WorkflowAgentService(db).version_for(
        current.auth,
        workflow_id=current.workflow_id,
        node_id=current.node_instance_id,
        spec=config.inline,
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
                text, run, answer = segment.output, segment.run, segment.structured
            else:
                before = Decimal(0)
                images = await _images(node_input.attachments)
                if isinstance(images, Failed):
                    return images
                pinned = await _pinned(db, config)
                if isinstance(pinned, Failed):
                    return pinned
                agent_id, version_id = pinned
                answers: list[dict[str, Any]] = []
                text, run = await runner.execute(
                    current.auth,
                    agent_id,
                    _prompt(node_input),
                    said=node_input.prompt,
                    surface=RunSurface.WORKFLOW,
                    version_id=version_id,
                    content=images,
                    output_schema=config.structured_output_schema,
                    structured=answers,
                    run_limit_usd=(
                        None if config.max_cost_usd is None else Decimal(str(config.max_cost_usd))
                    ),
                    public_origin=current.public_origin,
                )
                answer = answers[0] if answers else None
    except AppException as exc:
        return Failed(error=workflow_error(exc))
    except Exception:
        # A model provider's own text can carry a request URL with a key in it.
        logger.exception(
            "workflow_agent_run_failed", extra={"node_run_id": str(current.node_run_id)}
        )
        return Failed(
            error=WorkflowError(
                code="AGENT_RUN_FAILED", message="The agent run stopped with an error"
            )
        )
    spent = run.cost_usd - before
    if spent > 0 or run.cost_is_partial:
        context.report_cost(max(spent, Decimal(0)), partial=run.cost_is_partial)
    return _settled(run, text, answer, config, node_input)
