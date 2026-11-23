"""Run a system agent for a typed result.

The judge, the case generator and the authoring assistant each hand a system
agent a prompt and want a structured answer back. They run it the same way any
agent runs - `AgentRunnerService.execute`, budget-checked before each model
call, priced, recorded in Activity under the `eval` surface - and read the answer
here, so none of them builds a second path to a model.

Every run is isolated as an eval's is: its reads execute, and any tool that
would change something is held and recorded instead. A system agent reads text
nobody here vetted - a candidate's answer, a document, a conversation - and an
instruction planted in it must not reach a production connection through a tool
an editor added to the agent's spec.

The answer comes back as a structured output: the result type's JSON schema is
the run's `output_schema`, so the model answers through a tool call whose
arguments are checked against it and is sent back to fix one that does not fit.
It is set on the run rather than in the agent's spec, because the spec is the
organization's to edit, and an edit may change how the agent judges but must not
change whether its answer can be read.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.knowledge import FoundPassage
from app.agents.factory import OUTPUT_RETRIES, OutputSchemaRetry
from app.agents.isolation import RunIsolation, RunKnowledge
from app.agents.system_agents import system_agent
from app.core.exceptions import (
    BadRequestError,
    NotFoundError,
    RunFailedError,
    SystemAgentOutputError,
    SystemAgentRunError,
    SystemAgentUnavailableError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentStatus
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.repositories import agent_repo, agent_run_repo
from app.services.access import AGENT, resolve_access
from app.services.agent_registry import PublishedCandidate
from app.services.agent_runner import AgentRunnerService
from app.services.model_profile import ModelProfileService
from app.services.system_agents import SystemAgentService


@dataclass(frozen=True)
class SystemAgentResult[T]:
    """What a system agent answered, and the run that answered it.

    Attributes:
        output: The answer, validated as the caller's result type.
        run: The recorded run - its id, cost and status, as Activity shows them.
        found: What its searches of the run's knowledge bases returned.
    """

    output: T
    run: AgentRun
    found: list[FoundPassage] = field(default_factory=list)


def output_schema(output_type: type[object]) -> dict[str, Any]:
    """The JSON schema a run's answer is given in, for `output_type`."""
    return TypeAdapter(output_type).json_schema()


def _unreadable(exc: PydanticValidationError) -> str:
    """Why an answer could not be read, field by field, and never the answer itself.

    A run's error is read by everyone who reads runs, whatever datasets they may
    see, and a system agent's answer can repeat the private case it was given.
    """
    problems = "; ".join(
        f"{'.'.join(str(step) for step in error['loc']) or 'answer'}: {error['msg']}"
        for error in exc.errors(include_url=False, include_input=False)[:10]
    )
    return f"The answer did not match the shape asked for - {problems}"


def read_output[T](answer: object, output_type: type[T]) -> T:
    """Read a structured answer as `output_type`.

    The schema check before it covers the JSON shape; this applies the result
    type's own rules, which a schema cannot state.

    Raises:
        pydantic.ValidationError: When the answer is not of that shape - or is
            missing, `None`, for a run that answered no object.
    """
    return TypeAdapter(output_type).validate_python(answer)


def _output_failure(cause: BaseException | None) -> str | None:
    """Recognize the pinned SDK's output budget, separately from tool/protocol failures."""
    if not isinstance(cause, UnexpectedModelBehavior) or str(cause) != (
        f"Exceeded maximum output retries ({OUTPUT_RETRIES})"
    ):
        return None
    nested = cause.__cause__
    while nested is not None:
        if isinstance(nested, OutputSchemaRetry):
            return nested.diagnosis
        nested = nested.__cause__
    return f"The answer did not match its output schema after {OUTPUT_RETRIES} retries"


class SystemAgentRunner:
    """Run an organization's system agent and read its answer as a typed result.

    Attributes:
        failed_run_id: The recorded run of the last call that failed, also when the
            failure is re-raised as its original exception rather than one carrying
            a `run_id`, so a caller can still link or forget what the run kept.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.agents = SystemAgentService(db)
        self.failed_run_id: UUID | None = None

    async def run[T](
        self,
        ctx: AuthContext,
        *,
        key: str,
        prompt: str,
        output_type: type[T],
        agent_id: UUID | None = None,
        model_profile_id: UUID | None = None,
        instructions: str | None = None,
        version_id: UUID | None = None,
        improvement_run_id: UUID | None = None,
        knowledge_base_ids: Sequence[UUID] = (),
        schema: dict[str, Any] | None = None,
    ) -> SystemAgentResult[T]:
        """Run system agent `key` on `prompt` as the caller, and validate its answer.

        The caller's own access applies: the run is attributed to them, charged to
        the agent's and the organization's budgets, and refused if they may not
        run the agent. Model readiness and budgets are checked before execution.

        Args:
            ctx: Who is asking; the run is theirs.
            key: The system agent, as registered in `app.agents.system_agents`.
            prompt: The task.
            output_type: What the answer is validated as; its JSON schema is the
                shape the run must answer in.
            agent_id: Run this agent of the definition's kind - a dataset's own
                judge - rather than the seeded one.
            model_profile_id: Run on this model rather than the one the agent
                publishes on.
            knowledge_base_ids: What the run is about - the graded agent's
                knowledge bases, a gap's, a generation's sources. An agent that
                searches searches these alone, as far as the caller may read them.
            schema: The shape the run answers in, when this call narrows the
                result type's own - the ids a verdict must grade. Whatever it
                allows must still validate as `output_type`.

        Raises:
            NotFoundError: The chosen agent is missing or the caller may not view it.
            SystemAgentUnavailableError: The agent cannot run - `not_seeded`,
                `missing` when `agent_id` names an agent of another kind,
                `unpublished`, `archived`, `no_access` for this caller, or
                `no_model` when the model it would run on is gone or has no key.
            SystemAgentRunError: The run was recorded but ended without an answer:
                a budget refusal, a guardrail block, a failure, a parked approval,
                or a search that used up its steps.
            SystemAgentOutputError: The agent's answer still did not validate
                once the run's own retries were spent. The run is not repeated.
        """
        agent = await self.require_runnable(
            ctx,
            key=key,
            agent_id=agent_id,
            model_profile_id=model_profile_id,
            version_id=version_id,
        )

        selected_version = version_id or agent.current_version_id
        assert selected_version is not None
        knowledge = RunKnowledge(tuple(knowledge_base_ids))
        structured: list[dict[str, Any]] = []
        try:
            text, run = await AgentRunnerService(self.db).execute(
                ctx,
                agent.id,
                prompt,
                surface=RunSurface.EVAL,
                output_schema=schema or output_schema(output_type),
                structured=structured,
                model_profile_id=model_profile_id,
                isolation=RunIsolation(improvement_run_id=improvement_run_id, knowledge=knowledge),
                candidate=(
                    PublishedCandidate(
                        version_id=selected_version,
                        instructions=instructions,
                    )
                    if version_id is not None or instructions is not None
                    else None
                ),
                reports_failure=True,
            )
        except RunFailedError as failure:
            cause = failure.__cause__
            recorded = failure.details or {}
            self.failed_run_id = UUID(str(recorded["run_id"])) if "run_id" in recorded else None
            diagnosis = _output_failure(cause)
            if diagnosis is not None:
                run_id = UUID(str(recorded["run_id"]))
                failed_run = await agent_run_repo.get_run(
                    self.db, run_id, organization_id=ctx.organization_id
                )
                if failed_run is not None:
                    await agent_run_repo.set_error(self.db, run=failed_run, error=diagnosis)
                raise SystemAgentOutputError(
                    message=(
                        f"'{agent.name}' answered in a form that could not be read. Its run "
                        "is in Activity."
                    ),
                    run_id=UUID(str(recorded["run_id"])),
                    answer="",
                ) from failure
            if not isinstance(cause, UsageLimitExceeded):
                raise cause or failure from None
            raise SystemAgentRunError(
                message=(
                    f"'{agent.name}' searched until it ran out of steps and gave no answer. "
                    "Give it more steps, or let it search less."
                ),
                run_id=UUID(str(recorded["run_id"])),
                status=str(recorded["status"]),
            ) from failure
        if run.status != RunStatus.COMPLETED.value:
            raise SystemAgentRunError(
                message=f"'{agent.name}' did not finish: {run.status}",
                run_id=run.id,
                status=run.status,
            )
        try:
            output = read_output(structured[0] if structured else None, output_type)
        except PydanticValidationError as exc:
            await agent_run_repo.set_error(self.db, run=run, error=_unreadable(exc))
            raise SystemAgentOutputError(
                message=(
                    f"'{agent.name}' answered in a form that could not be read. Its run "
                    "is in Activity."
                ),
                run_id=run.id,
                answer=text,
            ) from exc
        return SystemAgentResult(output=output, run=run, found=knowledge.found)

    async def require_runnable(
        self,
        ctx: AuthContext,
        *,
        key: str,
        agent_id: UUID | None = None,
        model_profile_id: UUID | None = None,
        version_id: UUID | None = None,
    ) -> Agent:
        """The system agent `key`, once it is known the caller could run it now.

        Every refusal :meth:`run` makes before the model is called, without the
        run: for a caller that must refuse in the request before handing the
        work to the background.

        Raises:
            NotFoundError: The chosen agent is missing or the caller may not view it.
            SystemAgentUnavailableError: `not_seeded`, `missing`, `unpublished`,
                `archived`, `no_access` for this caller, or `no_model`.
        """
        agent = (
            await self.agents.ensure(organization_id=ctx.organization_id, key=key)
            if agent_id is None
            else await self._picked(ctx, key=key, agent_id=agent_id)
        )
        if agent.status == AgentStatus.ARCHIVED.value:
            raise SystemAgentUnavailableError(
                message=f"'{agent.name}' is archived. Restore it to use it again.",
                key=key,
                reason="archived",
            )
        if version_id is not None:
            version = await agent_repo.get_version(
                self.db, version_id, organization_id=ctx.organization_id
            )
            if version is None or version.agent_id != agent.id:
                raise SystemAgentUnavailableError(
                    message=f"The pinned version of '{agent.name}' no longer exists. Move the guard pin to use another.",
                    key=key,
                    reason="missing",
                )
        if version_id is None and agent.current_version_id is None:
            raise SystemAgentUnavailableError(
                message=f"'{agent.name}' has no published version. Pick a model and publish it.",
                key=key,
                reason="unpublished",
            )
        if not await resolve_access(self.db, ctx, agent, Perm.AGENTS_RUN, resource_type=AGENT):
            raise SystemAgentUnavailableError(
                message=f"You may not run '{agent.name}'. Ask for access to it.",
                key=key,
                reason="no_access",
            )
        selected_version = version_id or agent.current_version_id
        assert selected_version is not None
        await self._require_model(ctx, agent.name, selected_version, key, model_profile_id)
        return agent

    async def _picked(self, ctx: AuthContext, *, key: str, agent_id: UUID) -> Agent:
        definition = system_agent(key)
        agent = await agent_repo.get(self.db, agent_id, organization_id=ctx.organization_id)
        if agent is None or not await resolve_access(
            self.db, ctx, agent, Perm.AGENTS_VIEW, resource_type=AGENT
        ):
            raise NotFoundError(message="Agent not found", details={"agent_id": agent_id})
        if agent.kind != definition.kind.value:
            raise SystemAgentUnavailableError(
                message=f"The {definition.kind.value} picked here no longer exists. Pick another.",
                key=key,
                reason="missing",
            )
        return agent

    async def _require_model(
        self,
        ctx: AuthContext,
        name: str,
        version_id: UUID,
        key: str,
        model_profile_id: UUID | None,
    ) -> None:
        """Refuse before any run when the model the agent would run on cannot be reached.

        A deleted profile, or one whose key is gone, is a fact about the
        organization's configuration rather than a failed run, so it answers the
        way an unpublished agent does.
        """
        version = await agent_repo.get_version(
            self.db, version_id, organization_id=ctx.organization_id
        )
        published = None if version is None else version.spec.get("model_profile_id")
        profile_id = model_profile_id or (None if published is None else UUID(str(published)))
        try:
            await ModelProfileService(self.db).resolve(ctx, profile_id=profile_id)
        except (NotFoundError, BadRequestError) as exc:
            raise SystemAgentUnavailableError(
                message=f"'{name}' cannot reach its model: {exc.message}",
                key=key,
                reason="no_model",
            ) from exc
