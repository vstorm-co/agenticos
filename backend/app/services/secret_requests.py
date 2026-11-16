"""Fulfilling and declining a secret request (#13).

The card posts here, never to the chat: the value arrives as a `SecretStr`
on the fulfil body, is sealed straight into the vault by
`OrganizationSecretService.create`, and is dropped the moment the seal
returns. What is kept - on the request row and in the run's parked state -
is the created secret's id, name and hint, and the safe acknowledgement
string the model reads on resume. Nothing in this module logs, audits or
returns the value, and no code path after the seal holds it.

A fulfil resumes the run only when every secret it parked on is in and no
question is still unanswered; until then the run stays parked and the card
stays up for the remaining requests. A decline ends the run failed, with
the refusal as its error, rather than resuming a model that would ask
again.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.secret_request import SECRET_DECLINED_RESULT, secret_request_result
from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import parse_storable_secret
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, RunSurface
from app.db.models.secret_request import SecretRequest, SecretRequestStatus
from app.repositories import agent_run_repo, secret_request_repo
from app.schemas.agent import SecretRequestRead
from app.services.agent_runner import AgentRunnerService, PausedRunState, RunSegment
from app.services.organization_secret import OrganizationSecretService
from app.services.transcript import TranscriptService

MAX_SECRET_VALUE_CHARS = 8192


def _read(request: SecretRequest, run_id: UUID) -> SecretRequestRead:
    """A request row as the card draws it. Never carries the value."""
    return SecretRequestRead(
        id=request.id,
        run_id=run_id,
        tool_call_id=request.tool_call_id,
        secret_name=request.secret_name,
        kind=request.kind,
        what_for=request.what_for,
        status=request.status,
        fulfilled_secret_id=request.fulfilled_secret_id,
        fulfilled_hint=request.fulfilled_hint,
        created_at=request.created_at,
        decided_at=request.decided_at,
    )


class SecretRequestService:
    """The route-facing orchestration around a parked run's secret requests."""

    def __init__(self, db: AsyncSession, *, runner: AgentRunnerService) -> None:
        self.db = db
        self.runner = runner

    async def list_for_run(self, ctx: AuthContext, run_id: UUID) -> list[SecretRequestRead]:
        """A run's secret requests, oldest first, for the person it asked.

        Empty for anybody else: a run waiting on somebody's secret has
        nothing to offer them, and the names alone say what the agent needs.
        """
        run = await self.runner.get_run(ctx, run_id)
        if run.user_id != ctx.user_id:
            return []
        rows = await secret_request_repo.list_for_run(
            self.db, run_id=run.id, organization_id=ctx.organization_id
        )
        return [_read(row, run.id) for row in rows]

    async def fulfil(
        self,
        ctx: AuthContext,
        run_id: UUID,
        request_id: UUID,
        *,
        value: SecretStr,
        on_segment: Callable[[RunSegment], Awaitable[None]] | None = None,
    ) -> RunSegment | None:
        """Seal the value into the vault and, when nothing else is outstanding, resume the run.

        Returns the continuation when the run resumed, or `None` while it
        stays parked on another secret. The value is sealed and dropped
        before anything else happens: a resume that then refuses leaves a
        stored secret behind, never a value in a run record.

        Raises:
            NotFoundError: If the run or the request is not in this organization.
            AuthorizationError: If the caller is not the person the run asked,
                or is their organization key without `agents:run`.
            BadRequestError: If the run is not waiting for a secret, the
                request is already decided, a question is still unanswered,
                or the secret name is already taken.
        """
        if not ctx.has(Perm.SECRETS_EDIT):
            raise AuthorizationError(
                message="This caller may not create organization secrets",
                details={"scope": Perm.SECRETS_EDIT.value},
            )
        run = await agent_run_repo.claim_parked_run(
            self.db, run_id, organization_id=ctx.organization_id
        )
        if run is None:
            raise NotFoundError(message="Run not found", details={"run_id": str(run_id)})
        request = await self._claimed_pending_request(ctx, run, request_id)
        await self._refuse_unanswerable(ctx, run)
        state = PausedRunState.model_validate(run.paused_state)
        if request.tool_call_id not in state.secret_requests:
            raise BadRequestError(
                message="This run is not waiting on that secret request",
                details={"run_id": str(run_id), "request_id": str(request_id)},
            )
        unanswered = [
            question for question in state.questions if question not in state.question_results
        ]
        if unanswered:
            raise BadRequestError(
                message="Answer the run's questions before providing its secret",
                details={"run_id": str(run_id)},
            )
        raw = value.get_secret_value().strip()
        if not raw or len(raw) > MAX_SECRET_VALUE_CHARS:
            raise BadRequestError(
                message="Provide a secret value",
                details={"run_id": str(run_id)},
            )
        secret = await OrganizationSecretService(self.db).create(
            ctx,
            name=request.secret_name,
            value=parse_storable_secret(request.kind, raw),
            description=request.what_for,
            purpose="custom",
        )
        await secret_request_repo.mark_decided(
            self.db,
            request=request,
            status=SecretRequestStatus.FULFILLED,
            decided_by_user_id=ctx.user_id,
            fulfilled_secret_id=secret.id,
            fulfilled_hint=secret.hint,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="secret_request.fulfilled",
            target_type="secret_request",
            target_id=str(request.id),
            # The value never reaches the audit log; the hint is what identifies it.
            details={
                "secret_name": request.secret_name,
                "secret_id": str(secret.id),
                "hint": secret.hint,
            },
        )
        state.secret_results[request.tool_call_id] = secret_request_result(
            request.secret_name, secret.hint
        )
        run = await agent_run_repo.keep_paused_state(
            self.db, run=run, paused_state=state.model_dump(mode="json")
        )
        if any(tool_call_id not in state.secret_results for tool_call_id in state.secret_requests):
            return None
        return await self.runner.resume(ctx, run.id, on_segment=on_segment)

    async def decline(self, ctx: AuthContext, run_id: UUID, request_id: UUID) -> SecretRequestRead:
        """End a run failed because its person declined to provide the secret.

        The refusal is the run's error, so the conversation reads why it
        stopped rather than a question still open. Sibling requests on the
        same park are declined with it: the run is over, and a card for a
        secret nobody can now provide is a dead end.

        Raises:
            NotFoundError: If the run or the request is not in this organization.
            AuthorizationError: If the caller is not the person the run asked.
            BadRequestError: If the run is not waiting for a secret, or the
                request is already decided.
        """
        run = await agent_run_repo.claim_parked_run(
            self.db, run_id, organization_id=ctx.organization_id
        )
        if run is None:
            raise NotFoundError(message="Run not found", details={"run_id": str(run_id)})
        request = await self._claimed_pending_request(ctx, run, request_id)
        await self._refuse_unanswerable(ctx, run)
        state = (
            PausedRunState.model_validate(run.paused_state)
            if run.paused_state is not None
            else None
        )
        error = (
            f"User declined to provide secret '{request.secret_name}' - "
            "the run cannot continue without it"
        )
        now = datetime.now(UTC)
        settled = dict.fromkeys(
            state.secret_requests if state is not None else [], SECRET_DECLINED_RESULT
        )
        await TranscriptService(self.db).record(run, prompt=None, answer="", settled=settled)
        await agent_run_repo.finish_run(
            self.db,
            run=run,
            status=RunStatus.FAILED.value,
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            cost_usd=run.cost_usd,
            cost_is_partial=run.cost_is_partial,
            ended_at=now,
            error=error,
            paused_state=None,
        )
        siblings = await secret_request_repo.list_for_run(
            self.db, run_id=run.id, organization_id=ctx.organization_id
        )
        await secret_request_repo.mark_decided(
            self.db,
            request=request,
            status=SecretRequestStatus.DECLINED,
            decided_by_user_id=ctx.user_id,
        )
        for sibling in siblings:
            if sibling.id != request.id and sibling.status == SecretRequestStatus.PENDING:
                await secret_request_repo.mark_decided(
                    self.db,
                    request=sibling,
                    status=SecretRequestStatus.DECLINED,
                    decided_by_user_id=ctx.user_id,
                )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="secret_request.declined",
            target_type="secret_request",
            target_id=str(request.id),
            details={"secret_name": request.secret_name},
        )
        return _read(request, run.id)

    async def _claimed_pending_request(
        self, ctx: AuthContext, run: AgentRun, request_id: UUID
    ) -> SecretRequest:
        """The request a fulfil or decline names, held, checked and pending."""
        request = await secret_request_repo.claim(
            self.db, request_id=request_id, organization_id=ctx.organization_id
        )
        if request is None or request.run_id != run.id:
            raise NotFoundError(
                message="Secret request not found",
                details={"request_id": str(request_id)},
            )
        if request.status != SecretRequestStatus.PENDING:
            raise BadRequestError(
                message="This secret request was already decided",
                details={"request_id": str(request_id), "status": request.status},
            )
        if run.user_id != ctx.user_id:
            raise AuthorizationError(
                message="Only the person it asked can answer this secret request"
            )
        return request

    async def _refuse_unanswerable(self, ctx: AuthContext, run: AgentRun) -> None:
        """Refuse a secret decision on a run that cannot be continued from here.

        A run parked on an approval beside its secret is answerable once the
        approvals are decided: refusing it outright would strand the run,
        because the approval path resumes with the secret still outstanding
        and the fulfil path would then refuse a run no longer waiting on an
        answer. So an approval-parked run is refused only while an approval
        is still pending.
        """
        if run.status not in (
            RunStatus.AWAITING_ANSWER.value,
            RunStatus.AWAITING_APPROVAL.value,
        ):
            raise BadRequestError(
                message="This run is not waiting for a secret",
                details={"run_id": str(run.id), "status": run.status},
            )
        if run.paused_state is None:
            raise BadRequestError(
                message="This run was parked without the state needed to continue it",
                details={"run_id": str(run.id)},
            )
        if run.status == RunStatus.AWAITING_APPROVAL.value:
            approvals = await agent_run_repo.list_approvals_for_run(
                self.db, run_id=run.id, organization_id=run.organization_id
            )
            if any(a.status == ApprovalStatus.PENDING.value for a in approvals):
                raise BadRequestError(
                    message="Decide the run's approvals before providing its secret",
                    details={"run_id": str(run.id)},
                )
        if run.surface == RunSurface.WORKFLOW.value:
            raise BadRequestError(
                message="Answer this run through its workflow",
                details={"run_id": str(run.id)},
            )
        if ctx.api_key_id is not None and run.user_id is not None:
            raise AuthorizationError(
                message="A run a person started is answered from a session, not with an API key",
                details={"run_id": str(run.id)},
            )
        if ctx.api_key_id is not None and not ctx.has(Perm.AGENTS_RUN):
            raise AuthorizationError(
                message="Providing a secret continues the run, and this key may not run agents",
                details={"scope": Perm.AGENTS_RUN.value},
            )
