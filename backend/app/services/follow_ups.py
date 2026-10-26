"""Optional next-step buttons, generated after the answer's transaction commits.

Each call owns its session, governed run and settlement. Suggestions may be lost
on API shutdown; they are an enhancement, never a reason to delay an answer.
"""

import asyncio
import logging
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.guardrails.detectors import TextDetector
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import BudgetExceeded, BudgetScope, guarded_by, metered_by
from app.agents.capabilities.follow_ups import FollowUpsConfig, kept_steps
from app.agents.capabilities.follow_ups._capability import _INSTRUCTIONS, _SHOWN_CHARS, _Steps
from app.agents.capabilities.guardrails import (
    GuardrailBlocked,
    GuardrailsConfig,
    input_screen,
    output_screen,
    tool_args_screen,
)
from app.agents.deps import AgentDeps
from app.agents.failures import run_failure_summary
from app.agents.observability import inherited_instrumentation
from app.agents.spec import AgentSpec
from app.core.background import spawn_after_commit
from app.core.exceptions import AppException
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_run import RunStatus, RunSurface
from app.db.session import get_db_context
from app.repositories import agent_repo, agent_run_repo, conversation_repo, member_repo, user_repo
from app.services import chat_room
from app.services.agent_runner import AgentRunnerService, PreparedRun
from app.services.conversation import ConversationService
from app.services.run_heartbeat import run_heartbeat

logger = logging.getLogger(__name__)

# Optional buttons must not consume every API connection when a provider stalls.
suggestion_slots = asyncio.Semaphore(4)
_TIMEOUT_SECONDS = 15.0


def model_profile(spec: AgentSpec) -> UUID | None:
    """Only an explicitly selected profile enables suggestions; never the main model."""
    for binding in spec.capabilities:
        if binding.id == "follow_ups" and binding.enabled:
            return FollowUpsConfig.model_validate(binding.config).model_profile_id
    return None


def queue_next_steps(db: AsyncSession, message_id: UUID, organization_id: UUID) -> None:
    """Both transcript writers defer the same ID-only handoff until commit."""
    spawn_after_commit(
        db, write_next_steps(message_id, organization_id), name=f"next-steps:{message_id}"
    )


async def write_next_steps(message_id: UUID, organization_id: UUID) -> None:
    """Best-effort, bounded post-commit work carrying identifiers only."""
    if suggestion_slots.locked():
        logger.info("next_steps_skipped_at_capacity")
        return
    async with suggestion_slots, get_db_context() as db:
        await FollowUpService(db).write(message_id, organization_id)


def _helper(prepared: PreparedRun) -> Agent[AgentDeps, _Steps]:
    model = prepared.built.agent.model
    if not isinstance(model, Model):
        raise TypeError("Next steps require a request-response model")
    helper = Agent[AgentDeps, _Steps](
        model,
        instructions=_INSTRUCTIONS,
        output_type=_Steps,
        capabilities=[prepared.built.budget],
        model_settings=prepared.built.agent.model_settings,
    )
    helper.instrument = inherited_instrumentation(prepared.built.agent)
    return helper


def _guardrails(spec: AgentSpec) -> GuardrailsConfig:
    for binding in spec.capabilities:
        if binding.id == "guardrails" and binding.enabled:
            return GuardrailsConfig.model_validate(binding.config)
    return GuardrailsConfig()


def _screen(text: str, detector: TextDetector | None) -> str:
    if detector is None:
        return text
    verdict = detector(text)
    # Owned edge detectors allow, replace text, or raise GuardrailBlocked.
    return str(verdict.replacement) if verdict.action == "replace" else text


class FollowUpService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def write(
        self, message_id: UUID, organization_id: UUID, *, channel: bool = False
    ) -> list[str]:
        message = await conversation_repo.get_message_by_id(self.db, message_id)
        if message is None or message.role != "assistant" or message.run_id is None:
            return []
        parent = await agent_run_repo.get_run(
            self.db, message.run_id, organization_id=organization_id
        )
        if (
            parent is None
            or parent.status != RunStatus.COMPLETED.value
            or parent.user_id is None
            or parent.conversation_id != message.conversation_id
        ):
            return []
        if (
            parent.surface
            in {RunSurface.SLACK, RunSurface.TELEGRAM, RunSurface.MATTERMOST, RunSurface.TEAMS}
            and not channel
        ):
            # The channel router starts its copy only after posting the answer.
            return []
        conversation = await conversation_repo.get_conversation_by_id(
            self.db, message.conversation_id
        )
        if (
            conversation is None
            or conversation.organization_id != organization_id
            or conversation.is_archived
        ):
            return []
        stored = parent.test_spec
        if stored is None and parent.agent_version_id is not None:
            version = await agent_repo.get_version(
                self.db, parent.agent_version_id, organization_id=organization_id
            )
            stored = None if version is None else version.spec
        if stored is None or (profile := model_profile(AgentSpec.model_validate(stored))) is None:
            return []
        membership = await member_repo.get_active(
            self.db, organization_id=organization_id, user_id=parent.user_id
        )
        user = await user_repo.get_by_id(self.db, parent.user_id)
        if membership is None or user is None or not user.is_active:
            return []
        ctx = AuthContext(
            user_id=user.id,
            organization_id=organization_id,
            role=membership.role,
            is_app_admin=user.is_app_admin,
            subject_is_publisher_fallback=parent.initiated_by_publisher_fallback,
            key_scopes=None
            if parent.key_scopes is None
            else frozenset(Perm(scope) for scope in parent.key_scopes if scope in Perm),
        )
        try:
            await ConversationService(self.db).get_conversation(
                message.conversation_id,
                organization_id=organization_id,
                user_id=ctx.user_id,
                ctx=ctx,
                include_favourite=False,
            )
        except AppException:
            logger.info("next_steps_no_conversation_access", extra={"run_id": str(parent.id)})
            return []
        prompt = await conversation_repo.prompt_for_answer(self.db, message)
        runner = AgentRunnerService(self.db)
        try:
            # No conversation: this auxiliary run must not become the conversation's
            # running turn, compact its history or overwrite its reminder cadence.
            prepared = await runner.prepare(
                ctx,
                parent.agent_id,
                surface=RunSurface.FOLLOW_UPS,
                model_profile_id=profile,
                aside=True,
                draft=parent.agent_version_id is None,
                environment_id=parent.environment_id,
                test=parent.is_test,
                source_run=parent,
            )
        except AppException:
            logger.info("next_steps_model_unavailable", exc_info=True)
            await self.db.rollback()
            return []
        await agent_run_repo.associate_auxiliary_conversation(
            self.db, prepared.run, message.conversation_id
        )
        await self.db.commit()
        steps = await self._generate(runner, prepared, prompt, message.content)
        if not steps:
            await chat_room.next_steps(str(message.conversation_id), str(message_id), [])
            return []
        if await conversation_repo.store_next_steps(
            self.db, message_id=message_id, organization_id=organization_id, steps=steps
        ):
            await self.db.commit()
            await chat_room.next_steps(str(message.conversation_id), str(message_id), steps)
            return steps
        return []

    async def _generate(
        self, runner: AgentRunnerService, prepared: PreparedRun, prompt: str, answer: str
    ) -> list[str]:
        status = RunStatus.FAILED
        error: str | None = None
        budget_scope: BudgetScope | None = None
        try:
            config = _guardrails(prepared.spec)
            incoming = input_screen(config)
            # Screen before truncating: cutting through a secret can defeat its detector.
            prompt = _screen(prompt, incoming)
            answer = _screen(answer, incoming)
            helper = _helper(prepared)
            with guarded_by(prepared.built.budget), metered_by(prepared.built.ledger):
                async with run_heartbeat(prepared.run.id), asyncio.timeout(_TIMEOUT_SECONDS):
                    result = await helper.run(
                        f"The request:\n{prompt[:_SHOWN_CHARS]}\n\nThe agent's answer:\n{answer[:_SHOWN_CHARS]}",
                        deps=prepared.built.deps,
                        model_settings={"max_tokens": 512},
                        usage_limits=UsageLimits(
                            request_limit=min(2, prepared.built.usage_limits.request_limit or 2)
                        ),
                    )
            outgoing = output_screen(config)
            arguments = tool_args_screen(config)
            # Text-only output guardrails skip structured/native responses. Screen
            # every actual button before it can be stored or sent to a surface.
            steps = [
                _screen(_screen(step, None if outgoing is None else outgoing.screen), arguments)
                for step in result.output.steps
            ]
            status = RunStatus.COMPLETED
            return kept_steps(steps)
        except GuardrailBlocked as exc:
            status = RunStatus.GUARDRAIL_BLOCKED
            error = str(exc)
            return []
        except BudgetExceeded as exc:
            status = RunStatus.BUDGET_EXCEEDED
            budget_scope = exc.scope
            error = str(exc)
            logger.info("next_steps_skipped_at_budget_cap", extra={"run_id": str(prepared.run.id)})
            return []
        except asyncio.CancelledError:
            status = RunStatus.CANCELLED
            raise
        except Exception as exc:
            error = run_failure_summary(exc)
            logger.exception("next_steps_generation_failed", extra={"run_id": str(prepared.run.id)})
            return []
        finally:
            # Drain settlement even through repeated shutdown cancellation, as
            # the proactive runner does: failures still consumed a paid request.
            settlement = asyncio.create_task(
                self._finish(runner, prepared, status, error, budget_scope)
            )
            cancelled = False
            while not settlement.done():
                try:
                    await asyncio.wait({settlement})
                except asyncio.CancelledError:
                    cancelled = True
            settlement.result()
            if cancelled:
                raise asyncio.CancelledError

    async def _finish(
        self,
        runner: AgentRunnerService,
        prepared: PreparedRun,
        status: RunStatus,
        error: str | None,
        budget_scope: BudgetScope | None,
    ) -> None:
        await runner.finish(prepared, status=status, error=error, budget_scope=budget_scope)
        await self.db.commit()
