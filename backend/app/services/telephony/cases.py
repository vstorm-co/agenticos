"""Important-case contact remains a delivery of the owner's existing open outcome."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, Perm
from app.db.models.telephony import PhoneContact
from app.repositories import agent_run_repo
from app.repositories import telephony as repo
from app.services.agent_registry import AgentRegistryService
from app.services.conversation import ConversationService


async def eligible_case(
    db: AsyncSession,
    ctx: AuthContext,
    contact: PhoneContact,
    *,
    outcome_id: UUID,
    agent_id: UUID,
    conversation_id: UUID | None,
) -> datetime:
    if not contact.allow_important or str(agent_id) not in contact.agent_ids:
        raise AuthorizationError(message="This agent has no important-case phone consent")
    outcome = await repo.own_case(
        db, organization_id=ctx.organization_id, user_id=ctx.subject_id, outcome_id=outcome_id
    )
    if (
        outcome is None
        or outcome.status != "open"
        or outcome.source_run_id is None
        or outcome.source_conversation_id != conversation_id
    ):
        raise AuthorizationError(
            message="This case is settled, unavailable or belongs to another conversation"
        )
    source = await agent_run_repo.get_run(
        db, outcome.source_run_id, organization_id=ctx.organization_id
    )
    if source is None or source.agent_id != agent_id or source.user_id != ctx.subject_id:
        raise AuthorizationError(message="The shared case does not belong to this agent and member")
    await AgentRegistryService(db).get(ctx, agent_id, perm=Perm.AGENTS_RUN)
    if conversation_id is not None:
        await ConversationService(db).get_conversation(
            conversation_id,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            for_write=False,
            include_favourite=False,
        )
    if contact.escalation_delay_seconds:
        notified = await repo.case_notification_time(
            db, organization_id=ctx.organization_id, user_id=ctx.subject_id, outcome_id=outcome_id
        )
        if notified is None:
            raise AuthorizationError(
                message="Delayed telephone escalation needs an unacknowledged notification of this case"
            )
        return notified + timedelta(seconds=contact.escalation_delay_seconds)
    return datetime.now(UTC)


async def cancel_pending_case_calls(db: AsyncSession, outcome_id: UUID, *, at: datetime) -> None:
    from app.services.background_jobs import enqueue
    from app.worker.jobs import END_PHONE, DialPhone

    for identifier, organization_id in await repo.cancel_case_calls(db, outcome_id, at=at):
        await enqueue(
            db,
            END_PHONE,
            DialPhone(call_id=identifier),
            organization_id=organization_id,
            dedupe_key=f"phone-end:{identifier}",
        )
