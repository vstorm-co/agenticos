"""Poll thread metadata on the existing durable timer; never run a model while waiting."""

from datetime import UTC, datetime, timedelta
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ExternalServiceError, NotFoundError
from app.core.permissions import AuthContext
from app.db.locks import LockScope, hold_subject
from app.db.models.workflow_run import WorkflowRunStatus
from app.db.session import get_worker_db_context
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.reply_expectation import ReplyExpectation, ReplyExpectationInput
from app.services.mcp_connection import McpConnectionService
from app.services.portals.reply_metadata import MailProvider, MailReplyMetadataClient
from app.services.reply_expectation import match_reply, store_expectation
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed, NodeResult, Waiting, WorkflowError

MAX_WAIT = timedelta(days=30)


class AwaitReplyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: MailProvider = Field(title="Mailbox provider")
    connection_id: UUID = Field(title="Connected organization mailbox")
    mailbox: EmailStr | None = Field(default=None, title="Shared Outlook mailbox")
    poll_seconds: int = Field(default=300, ge=60, le=3600, title="Check every (seconds)")

    @model_validator(mode="after")
    def shared_outlook_only(self) -> Self:
        if self.provider == "google" and self.mailbox is not None:
            raise ValueError("Only Outlook supports a shared mailbox")
        return self


class AwaitReplyInput(BaseModel):
    """Text fields from a workflow form, parsed into canonical mail criteria.

    Workflow text fields do not advertise email/date-time JSON Schema formats.
    This boundary accepts their strings and validates the complete criteria
    with the same model the private expectation API uses.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    thread_id: str = Field(min_length=1, max_length=2048)
    expected_sender: str = Field(min_length=1, max_length=320)
    not_before: str = Field(min_length=1, max_length=80)
    deadline: str = Field(min_length=1, max_length=80)
    anchor_message_id: str | None = Field(default=None, max_length=998)

    def criteria(self) -> ReplyExpectationInput:
        return ReplyExpectationInput.model_validate(self.model_dump())

    @model_validator(mode="after")
    def valid_criteria(self) -> Self:
        self.criteria()
        return self


async def resource_check(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    if not isinstance(config, AwaitReplyConfig):
        return []
    service = McpConnectionService(db)
    grant = await service.get_org_portal_grant(
        ctx, "google" if config.provider == "google" else "microsoft"
    )
    if grant is None or grant.id != config.connection_id or not grant.is_enabled:
        return [("connection_id", "Select the connected organization mailbox for this provider")]
    try:
        await service.get_org_portal_connection(ctx, grant.id)
    except NotFoundError:
        return [("connection_id", "This mailbox is not available to the workflow author")]
    return []


def routes(output: dict[str, object] | None) -> frozenset[str]:
    branch = (output or {}).get("branch")
    return (
        frozenset({branch})
        if isinstance(branch, str) and branch in ("reply", "deadline")
        else frozenset()
    )


def _failed(code: str, message: str) -> Failed:
    return Failed(error=WorkflowError(code=code, message=message))


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, AwaitReplyConfig) or not isinstance(node_input, AwaitReplyInput):
        return _failed("REPLY_NOT_CONFIGURED", "Choose a mailbox, thread, sender and deadline")
    current = context.current()
    criteria = node_input.criteria()
    now = datetime.now(UTC)
    async with get_worker_db_context() as db:
        await hold_subject(db, LockScope.WORKFLOW_FILE_BYTES, current.organization_id)
        await hold_subject(db, LockScope.WORKFLOW_INLINE_RESULTS_PER_ORG, current.organization_id)
        run = await workflow_run_repo.get_run_for_update(
            db, current.workflow_run_id, organization_id=current.organization_id
        )
        step = await workflow_run_repo.get_node_run_by_id_for_update(db, current.node_run_id)
        if (
            run is None
            or step is None
            or step.workflow_run_id != run.id
            or WorkflowRunStatus(run.status).is_terminal
        ):
            return _failed("REPLY_RUN_ENDED", "The workflow run has ended")
        try:
            expectation = (
                ReplyExpectation.model_validate(step.resume_payload)
                if step.resume_payload is not None
                else None
            )
        except ValidationError:
            return _failed("REPLY_STATE_INVALID", "The saved expectation needs review")
        if expectation is not None and expectation.paused:
            if now >= expectation.deadline:
                return _failed(
                    "REPLY_PAUSED_DEADLINE_REACHED",
                    "The deadline passed while checks were paused; no reply verdict was recorded",
                )
            return Waiting(
                reason="timer",
                resume_token=str(step.id),
                resume_at=min(expectation.deadline, now + timedelta(hours=1)),
            )
        if (
            expectation.deadline if expectation else criteria.deadline
        ) > step.created_at + MAX_WAIT:
            return _failed(
                "REPLY_DEADLINE_TOO_LONG", "A reply expectation lasts at most thirty days"
            )
        try:
            access = await McpConnectionService(db).reply_mailbox_token(
                current.auth,
                portal_key="google"
                if (expectation.provider if expectation else config.provider) == "google"
                else "microsoft",
                connection_id=expectation.connection_id if expectation else config.connection_id,
                authorization_generation=expectation.authorization_generation
                if expectation
                else None,
            )
        except NotFoundError:
            access = None
        if access is None:
            return _failed(
                "REPLY_MAILBOX_UNAVAILABLE",
                "The selected mailbox is unavailable or its consent changed; review it before retrying",
            )
        generation, token = access
        if expectation is None:
            expectation = ReplyExpectation(
                **criteria.model_dump(),
                provider=config.provider,
                connection_id=config.connection_id,
                authorization_generation=generation,
                mailbox=config.mailbox,
            )
            await store_expectation(db, run=run, step=step, expectation=expectation)
    reader = MailReplyMetadataClient()
    try:
        messages = await reader.read(
            provider=expectation.provider,
            access_token=token,
            thread_id=expectation.thread_id,
            not_before=expectation.not_before,
            mailbox=str(expectation.mailbox) if expectation.mailbox is not None else None,
        )
    except ExternalServiceError:
        return _failed(
            "REPLY_CHECK_FAILED", "The mailbox could not be checked; no reply verdict was recorded"
        )
    finally:
        await reader.aclose()
    answer = match_reply(expectation, messages, now=datetime.now(UTC))
    if answer is not None:
        return Completed(output=answer)
    return Waiting(
        reason="timer",
        resume_token=str(current.node_run_id),
        resume_at=min(
            expectation.deadline, datetime.now(UTC) + timedelta(seconds=config.poll_seconds)
        ),
    )
