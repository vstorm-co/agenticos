"""What the model steps share: one model request, made as a step's own agent.

`ai.prompt`, `ai.classify`, `ai.extract` and `ai.rewrite` each ask a model one
thing. None of them is a bare model call: each builds a spec - its model, the
instructions it writes for its task, the answer shape it needs, no tools - and
runs it as the step's own agent through `WorkflowAgentService` and the agent
runner, exactly as an `agent.run` step configured in place runs. So a model step
has what every agent run has without a line of its own: the organization's and
the step's spending limits checked before the request, its cost on the workflow
run and in Activity, a trace, and publish-time checks that its author may use
the model.

`outcome` is also what `agent.run` reads an agent run's ending through, so the
two kinds of step fail with the same codes for the same reasons.
"""

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.settings import ThinkingEffort
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, CapabilityBindingSpec, ModelSettingsSpec
from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.session import get_worker_db_context
from app.services.agent_runner import AgentRunnerService
from app.services.workflow_agents import WorkflowAgentService
from app.services.workflow_execution import budget, context
from app.services.workflow_execution.errors import workflow_error
from app.workflows.contracts.results import Failed, WorkflowError

logger = logging.getLogger(__name__)

MAX_TEXT = 100_000
"""The most text one model step is handed - a long document goes through
`text.extract` and a summary first, not into one request whole."""


class ModelStepConfig(BaseModel):
    """What every model step is set with: which model, and how much it may spend."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_profile_id: UUID = Field(
        title="Model",
        json_schema_extra={"x-resource": "model_profile"},
        description="One of the organization's models.",
    )
    temperature: float | None = Field(
        default=None,
        ge=0,
        le=2,
        description="Answer variation. Leave unset for models that do not support temperature.",
    )
    effort: ThinkingEffort | None = Field(
        default=None,
        title="Reasoning effort",
        description="How hard the model reasons. Empty keeps the provider's default.",
    )
    max_cost_usd: float | None = Field(
        default=None,
        gt=0,
        le=1000,
        title="Max cost (USD)",
        description="The most one execution of this step may spend. Empty leaves the "
        "workflow's and the organization's limits.",
    )


def spec_for(
    config: ModelStepConfig,
    *,
    name: str,
    instructions: str,
    output_schema: dict[str, Any] | None = None,
) -> AgentSpec:
    """The spec a model step runs as: its model and its task's instructions, no tools."""
    return AgentSpec(
        name=name,
        instructions=instructions,
        model_profile_id=config.model_profile_id,
        output_schema=output_schema,
        model_settings=ModelSettingsSpec(temperature=config.temperature),
        capabilities=(
            [CapabilityBindingSpec(id="thinking", config={"effort": config.effort})]
            if config.effort is not None
            else []
        ),
        # One request is the whole task; a second is the model fixing an answer
        # that broke its shape.
        max_steps=3,
    )


async def problems(db: AsyncSession, ctx: AuthContext, spec: AgentSpec) -> list[tuple[str, str]]:
    """What stops the step's author from publishing this spec, on the model field."""
    found = await WorkflowAgentService(db).problems(ctx, spec)
    return [("model_profile_id", problem) for problem in found]


def outcome(run: AgentRun) -> Failed | None:
    """What an agent run that did not complete means for its step; `None` when it did."""
    status = RunStatus(run.status)
    if status is RunStatus.COMPLETED:
        return None
    if status is RunStatus.BUDGET_EXCEEDED:
        return Failed(
            error=WorkflowError(
                code="AGENT_BUDGET_EXCEEDED",
                message=run.error or "The agent's budget is spent",
                details={"agent_run_id": str(run.id)},
                bypassable=False,
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
    return Failed(
        error=WorkflowError(
            code="AGENT_RUN_FAILED",
            message="The agent did not finish",
            details={"agent_run_id": str(run.id), "status": status.value},
        )
    )


@dataclass(frozen=True)
class Answer:
    """What a model step's request came back with."""

    text: str
    structured: dict[str, Any] | None
    agent_run_id: UUID


async def ask(config: ModelStepConfig, spec: AgentSpec, prompt: str) -> Answer | Failed:
    """Run `spec` as this step's own agent on `prompt`, and book what it cost."""
    current = context.current()
    if current.workflow_id is None:
        return Failed(
            error=WorkflowError(
                code="MODEL_STEP_OUTSIDE_WORKFLOW",
                message="A model step runs only as part of its workflow",
            )
        )
    try:
        async with get_worker_db_context() as db:
            agent_id, version_id = await WorkflowAgentService(db).version_for(
                current.auth,
                workflow_id=current.workflow_id,
                node_id=current.node_instance_id,
                spec=spec,
            )
            answers: list[dict[str, Any]] = []
            text, run = await AgentRunnerService(db).execute(
                current.auth,
                agent_id,
                prompt,
                surface=RunSurface.WORKFLOW,
                version_id=version_id,
                structured=answers,
                run_limit_usd=budget.node_limit(current.budget_remaining, config.max_cost_usd),
            )
    except AppException as exc:
        return Failed(error=workflow_error(exc))
    except Exception:
        # A provider's own text can carry a request URL with a key in it.
        logger.exception(
            "workflow_model_step_failed", extra={"node_run_id": str(current.node_run_id)}
        )
        return Failed(
            error=WorkflowError(code="AGENT_RUN_FAILED", message="The model request failed")
        )
    if run.cost_usd > 0 or run.cost_is_partial:
        context.report_cost(run.cost_usd, partial=run.cost_is_partial)
    failed = outcome(run)
    if failed is not None:
        return failed
    return Answer(text=text, structured=answers[0] if answers else None, agent_run_id=run.id)
