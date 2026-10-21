"""Running an agent over the API without holding the connection open (#2219).

`POST /agents/{id}/run` answers when the run does, which a run of minutes - a
browse, a long tool chain - turns into a proxy timeout. Sent with
`Prefer: respond-async`, it answers `202` with a request to poll instead, and a
worker runs the agent through the same runner, the same budget and the same
books as the synchronous call.

What is checked when, deliberately: the conversation and the attachments are
checked in the request, so an unknown conversation is a `404` the caller sees at
once rather than a failure it polls for. The caller's authority is checked
again when the run starts - by the worker, from the key's current state - so a
key revoked while its run waited does not run it.

An `Idempotency-Key` makes a retry safe: the same key and the same request answer
the same run request, in any state; the same key with a different request is a
`409`, never a second run. A key is the asker's own: two people in one
organization sending the same key are two requests, so a colleague who guesses
a key can neither read the run it names nor reserve it.
"""

import hashlib
import json
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, AuthenticationError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent_run import RunSurface
from app.db.models.background_job import BackgroundJob, JobStatus
from app.repositories import background_job as background_job_repo
from app.repositories import member as member_repo
from app.repositories import user as user_repo
from app.schemas.agent import AgentRunRequest, AgentRunResult, RunRequestRead, RunRequestStatus
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService
from app.services.api_key import ApiKeyService
from app.services.attachments import load_attached_files
from app.services.background_jobs import enqueue
from app.services.conversation import ConversationService
from app.worker.jobs import RUN_AGENT, RunAgent

_STATUS: dict[JobStatus, RunRequestStatus] = {
    "queued": "queued",
    "running": "running",
    "succeeded": "completed",
    "dead": "failed",
    "cancelled": "cancelled",
}


def digest(agent_id: UUID, request: AgentRunRequest) -> str:
    """A request's fingerprint, the same for the same agent and body however it is sent."""
    body = {"agent_id": str(agent_id), **request.model_dump(mode="json")}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def scoped_key(ctx: AuthContext, idempotency_key: str) -> str:
    """The stored form of a caller's key: theirs alone, and the length of a digest.

    The unique index is per organization, so the asker goes into the stored key
    rather than beside it - a lookup keyed on the organization alone replayed one
    member's finished run, output included, to another who sent the same key.
    Hashed so that a 255-character header plus the asker still fits the column.
    """
    return hashlib.sha256(f"{ctx.subject_id}:{idempotency_key}".encode()).hexdigest()


class ApiRunService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def queue(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        request: AgentRunRequest,
        *,
        idempotency_key: str | None,
    ) -> RunRequestRead:
        """Check what can be checked now, queue the run, and answer the request to poll.

        Raises:
            AlreadyExistsError: `idempotency_key` was used for a different request.
            NotFoundError: The agent or the conversation is unknown or not the
                caller's to run.
            AuthorizationError: The caller may read the agent but not run it.
            BadRequestError: The agent is archived or unpublished, or the
                conversation was not opened over the API.
        """
        fingerprint = digest(agent_id, request)
        stored_key = None if idempotency_key is None else scoped_key(ctx, idempotency_key)
        if stored_key is not None:
            existing = await background_job_repo.get_by_idempotency_key(
                self.db, organization_id=ctx.organization_id, idempotency_key=stored_key
            )
            if existing is not None:
                return self._replay(existing, fingerprint)
        # The agent before anything is queued: a run of an agent the caller may
        # not run, or that is archived or unpublished, is a refusal now rather than
        # a job that sits in the queue until a worker refuses it.
        await AgentRegistryService(self.db).get_runnable_spec(
            ctx, agent_id, environment_id=request.environment_id
        )
        try:
            # The conversation in the same savepoint as the job: a request that
            # loses the race for its key below rolls back the conversation it
            # opened too, rather than leaving an empty chat in the caller's
            # sidebar (Codex, #2248).
            async with self.db.begin_nested():
                conversation_id, _history = await ConversationService(self.db).for_api_run(
                    ctx, request.conversation_id, prompt=request.prompt
                )
                attached = await load_attached_files(
                    self.db,
                    [str(file_id) for file_id in request.file_ids],
                    user_id=ctx.subject_id,
                )
                payload = RunAgent(
                    agent_id=agent_id,
                    organization_id=ctx.organization_id,
                    user_id=ctx.subject_id,
                    api_key_id=ctx.api_key_id,
                    prompt=request.prompt,
                    conversation_id=conversation_id,
                    environment_id=request.environment_id,
                    file_ids=[file.id for file in attached],
                    digest=fingerprint,
                )
                # One run of a conversation at a time: a follow-up sent before the
                # previous answer was written would read the history without it,
                # and both would write into the same thread and workspace at once.
                job_id = await enqueue(
                    self.db,
                    RUN_AGENT,
                    payload,
                    organization_id=ctx.organization_id,
                    idempotency_key=stored_key,
                    concurrency_key=f"conversation:{conversation_id}",
                )
        except IntegrityError:
            # Another request with the same key won the race between the lookup
            # above and this insert; answer as its replay.
            assert stored_key is not None
            winner = await background_job_repo.get_by_idempotency_key(
                self.db, organization_id=ctx.organization_id, idempotency_key=stored_key
            )
            assert winner is not None
            return self._replay(winner, fingerprint)
        assert job_id is not None, "a run request carries no dedupe key that could drop it"
        job = await background_job_repo.get(self.db, job_id)
        assert job is not None
        await self.db.refresh(job)
        return self._read(job)

    async def get(self, ctx: AuthContext, request_id: UUID) -> RunRequestRead:
        """The caller's own run request, wherever it has got to.

        Somebody else's - another organization's, or another person's in this
        one - answers as missing, so a request id cannot be probed.
        """
        job = await background_job_repo.get(self.db, request_id)
        if job is None or job.kind != RUN_AGENT.kind or job.organization_id != ctx.organization_id:
            raise NotFoundError(message="Run request not found", details={"id": str(request_id)})
        if RUN_AGENT.load(job.payload).user_id != ctx.subject_id:
            raise NotFoundError(message="Run request not found", details={"id": str(request_id)})
        return self._read(job)

    async def run(self, job: RunAgent) -> AgentRunResult:
        """What the worker does with a queued request: the synchronous call, made now."""
        ctx = await self._context(job, ApiKeyService(self.db))
        _conversation_id, history = await ConversationService(self.db).for_api_run(
            ctx, job.conversation_id, prompt=job.prompt
        )
        attachments = await load_attached_files(
            self.db, [str(file_id) for file_id in job.file_ids], user_id=ctx.subject_id
        )
        runner = AgentRunnerService(self.db)
        output, run = await runner.execute(
            ctx,
            job.agent_id,
            job.prompt,
            surface=RunSurface.API,
            conversation_id=job.conversation_id,
            message_history=history,
            environment_id=job.environment_id,
            attachments=attachments,
            reports_failure=True,
        )
        return AgentRunResult(
            run_id=run.id,
            conversation_id=job.conversation_id,
            output=output,
            status=run.status,
            cost_usd=run.cost_usd,
            cost_is_partial=run.cost_is_partial,
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            cache_read_tokens=run.cache_read_tokens,
            cache_write_tokens=run.cache_write_tokens,
            parked=await runner.parked_calls(ctx, run),
        )

    async def _context(self, job: RunAgent, keys: ApiKeyService) -> AuthContext:
        """The asker's authority as it stands now, not as it stood when they asked."""
        if job.api_key_id is not None:
            return await keys.context_for_key(job.api_key_id, organization_id=job.organization_id)
        membership = await member_repo.get_active(
            self.db, organization_id=job.organization_id, user_id=job.user_id
        )
        user = await user_repo.get_by_id(self.db, job.user_id)
        if membership is None or user is None or not user.is_active:
            raise AuthenticationError(
                message="The person who asked for this run can no longer run it"
            )
        return AuthContext(
            user_id=job.user_id,
            organization_id=job.organization_id,
            role=membership.role,
            is_app_admin=user.is_app_admin,
        )

    def _replay(self, job: BackgroundJob, fingerprint: str) -> RunRequestRead:
        if job.kind != RUN_AGENT.kind or RUN_AGENT.load(job.payload).digest != fingerprint:
            raise AlreadyExistsError(
                message="This Idempotency-Key was already used for a different request",
                details={"id": str(job.id)},
            )
        return self._read(job)

    @staticmethod
    def _read(job: BackgroundJob) -> RunRequestRead:
        payload = RUN_AGENT.load(job.payload)
        return RunRequestRead(
            id=job.id,
            status=_STATUS[job.status],
            conversation_id=payload.conversation_id,
            created_at=job.created_at,
            finished_at=job.finished_at,
            error=job.last_error if job.status == "dead" else None,
            result=None if job.result is None else AgentRunResult.model_validate(job.result),
        )
