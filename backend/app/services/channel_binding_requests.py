"""Requests to bind an agent to a bot that answers people with no account (#2076).

A bot on a public line answers customers who never linked an account, so who puts an
agent behind it is for a holder of `channels:manage` to decide. A member who may publish
the agent but not manage channels asks instead (see
:mod:`app.db.models.channel_binding_request`), and this is where the asking is filed,
listed, decided and voided.

Deciding a request locks the agent, then the bot, then the binding (for a change of one),
then the request. Every path that changes a binding takes the agent first, so taking it
first here rules out a deadlock with a direct bind, an environment delete or an unbind.
Filing locks only the bot: its insert takes no more than a key-share lock on the agent. So
two people filing at once leave one pending request each, a request is applied once however
many holders approve it together, and a request filed for a bot another agent has taken
since is never applied.

Approving applies the change through :class:`~app.services.agent_exposure.AgentExposureService`
as the approver, with its own checks - the spending limit a public line needs among them.
Declining applies nothing. Both tell the one who asked.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
    RateLimitError,
)
from app.core.permissions import ROLE_PERMS, AuthContext, Perm
from app.db.models.channel_binding_request import (
    BindingRequestKind,
    BindingRequestStatus,
    BindingVoidReason,
    ChannelBindingRequest,
)
from app.db.models.channel_bot import ChannelBot
from app.repositories import (
    agent_environment_repo,
    agent_exposure_repo,
    agent_repo,
    channel_binding_request_repo,
    channel_bot_repo,
    member_repo,
    user_repo,
)
from app.schemas.channel_binding_request import ChannelBindingRequestRead
from app.schemas.agent_exposure import ExposureCreate, ExposureUpdate
from app.services import rate_limit
from app.services.agent_registry import AgentRegistryService
from app.services.notifications import NotificationService

CHANNELS_MANAGE_ROLES: tuple[str, ...] = tuple(
    role for role, perms in ROLE_PERMS.items() if perms.get(Perm.CHANNELS_MANAGE) is not None
)
"""The roles that manage channels: who decides a request, and is told of it."""


async def deciders(db: AsyncSession, organization_id: UUID) -> list[UUID]:
    """Who decides the organization's binding requests, and is told of them."""
    return await member_repo.list_member_ids_by_role(
        db, organization_id=organization_id, roles=list(CHANNELS_MANAGE_ROLES)
    )


async def _name_of(db: AsyncSession, user_id: UUID) -> str:
    user = await user_repo.get_by_id(db, user_id)
    assert user is not None  # a request keeps its requester: their row cascades it away
    return user.full_name or user.email


async def _admit(ctx: AuthContext) -> None:
    """One request against the member's hourly allowance of requests."""
    decision = await rate_limit.consume_with_local_floor(
        surface="channel_binding_request",
        caller=f"org:{ctx.organization_id}:user:{ctx.user_id}",
        limit=rate_limit.artifact_share_request_limit(),
    )
    if not decision.allowed:
        raise RateLimitError(
            message="Too many requests in the last hour. Wait and try again.",
            details={"retry_after_seconds": decision.retry_after_seconds},
        )


async def waiting_for(db: AsyncSession, organization_id: UUID) -> str | None:
    """Who decides a request, by name, when it is one person; `None` when several may."""
    everyone = await deciders(db, organization_id)
    return await _name_of(db, everyone[0]) if len(everyone) == 1 else None


def _gone(request_id: UUID) -> ConcurrentChangeError:
    """What a locked re-read finds when an unbind or a delete removed a row meanwhile."""
    return ConcurrentChangeError(
        message="This request no longer applies.", details={"request_id": request_id}
    )


def _not_found(what: str, **details: object) -> NotFoundError:
    return NotFoundError(message=f"{what} not found", details=details)


async def file_request(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    bot_id: UUID,
    agent_id: UUID,
    kind: BindingRequestKind,
    exposure_id: UUID | None = None,
    environment_id: UUID | None = None,
    note: str | None = None,
    session_scope: str | None = None,
) -> ChannelBindingRequest:
    """Replace the caller's pending request for the bot, if any, with a new one and tell
    whoever decides it.

    The bot is locked first, as every change to its binding locks it, so two filings at
    once cannot both find nothing to replace.

    Raises:
        RateLimitError: Too many requests in the last hour.
        NotFoundError: The bot, the agent, the binding or the environment is not in the
            caller's organization, or the binding is not this agent's on this bot, or the
            environment is not this agent's.
    """
    assert ctx.user_id is not None  # a request is a person's
    if (kind is BindingRequestKind.BIND) != (exposure_id is None) or (
        kind is BindingRequestKind.RESUME and environment_id is not None
    ):
        raise BadRequestError(
            message=(
                "A new binding names no existing one; changing or resuming a binding names "
                "it, and resuming it takes no environment."
            ),
            details={"kind": kind.value},
        )
    await _admit(ctx)
    bot = await channel_bot_repo.get_for_org(
        db, bot_id, organization_id=ctx.organization_id, for_update=True
    )
    if bot is None:
        raise _not_found("Channel bot", channel_bot_id=str(bot_id))
    agent = await agent_repo.get(db, agent_id, organization_id=ctx.organization_id)
    if agent is None:
        raise _not_found("Agent", agent_id=str(agent_id))
    if exposure_id is not None:
        exposure = await agent_exposure_repo.get(
            db, exposure_id, organization_id=ctx.organization_id
        )
        if exposure is None or exposure.channel_bot_id != bot.id or exposure.agent_id != agent.id:
            raise _not_found("Exposure", exposure_id=str(exposure_id))
    if environment_id is not None:
        environment = await agent_environment_repo.get(
            db, environment_id, organization_id=ctx.organization_id
        )
        if environment is None or environment.agent_id != agent.id:
            raise _not_found("Environment", environment_id=str(environment_id))
    earlier = await channel_binding_request_repo.pending_for(
        db,
        organization_id=ctx.organization_id,
        channel_bot_id=bot.id,
        requester_user_id=ctx.user_id,
    )
    if earlier is not None:
        await channel_binding_request_repo.settle(
            db,
            earlier,
            status=BindingRequestStatus.VOIDED,
            void_reason=BindingVoidReason.REPLACED,
        )
    membership = await member_repo.get_active(
        db, organization_id=ctx.organization_id, user_id=ctx.user_id
    )
    request = await channel_binding_request_repo.create(
        db,
        organization_id=ctx.organization_id,
        channel_bot_id=bot.id,
        agent_id=agent.id,
        exposure_id=exposure_id,
        environment_id=environment_id,
        kind=kind.value,
        requester_user_id=ctx.user_id,
        requester_membership_id=membership.id if membership is not None else None,
        note=note,
        session_scope=session_scope,
    )
    await record_audit(
        db,
        actor_user_id=ctx.subject_id,
        organization_id=ctx.organization_id,
        action="channel.binding_requested",
        target_type="channel_bot",
        target_id=str(bot.id),
        details={
            "request_id": str(request.id),
            "kind": request.kind,
            "agent_id": str(agent.id),
            "channel_bot_id": str(bot.id),
        },
    )
    recipients = [
        user_id for user_id in await deciders(db, ctx.organization_id) if user_id != ctx.user_id
    ]
    if recipients:
        await NotificationService(db).channel_binding_requested(
            organization_id=ctx.organization_id,
            request_id=request.id,
            kind=request.kind,
            agent_name=agent.name,
            bot_name=bot.name,
            requester_name=await _name_of(db, ctx.user_id),
            recipients=recipients,
        )
    return request


async def void_for_closed_line(
    db: AsyncSession, *, organization_id: UUID, channel_bot_id: UUID
) -> int:
    """Void what waits on a bot that stopped answering people with no account: nothing
    needs the approval any more. Called with the bot locked. Returns how many."""
    return await channel_binding_request_repo.void_pending_for_bot(
        db,
        organization_id=organization_id,
        channel_bot_id=channel_bot_id,
        reason=BindingVoidReason.LINE_CLOSED,
    )


async def void_for_taken_bot(
    db: AsyncSession, *, organization_id: UUID, channel_bot_id: UUID
) -> int:
    """Void what waits on a bot another agent now serves: what was asked is not what
    would apply. Called with the bot locked. Returns how many."""
    return await channel_binding_request_repo.void_pending_for_bot(
        db,
        organization_id=organization_id,
        channel_bot_id=channel_bot_id,
        reason=BindingVoidReason.BOT_TAKEN,
    )


class ChannelBindingRequestService:
    """List and decide the binding requests of one organization."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _require_manager(ctx: AuthContext) -> None:
        if not ctx.has(Perm.CHANNELS_MANAGE):
            raise AuthorizationError(
                message="Only someone who manages channels can decide this request.",
                details={"permission": Perm.CHANNELS_MANAGE.value},
            )

    async def _reads(
        self, requests: list[ChannelBindingRequest]
    ) -> list[ChannelBindingRequestRead]:
        """The requests with the names a decider reads, loaded together."""
        names = await channel_binding_request_repo.labels(self.db, requests)
        own = ChannelBindingRequestRead.model_fields.keys() - {
            "agent_name",
            "channel_bot_name",
            "requester_email",
        }
        reads: list[ChannelBindingRequestRead] = []
        for request in requests:
            agent_name, bot_name, email = names[request.id]
            reads.append(
                ChannelBindingRequestRead(
                    **{field: getattr(request, field) for field in own},
                    agent_name=agent_name,
                    channel_bot_name=bot_name,
                    requester_email=email,
                )
            )
        return reads

    async def _reads_one(self, request: ChannelBindingRequest) -> ChannelBindingRequestRead:
        return (await self._reads([request]))[0]

    async def list_pending(
        self, ctx: AuthContext, skip: int, limit: int
    ) -> tuple[list[ChannelBindingRequestRead], int]:
        """The organization's pending requests, newest first, with the total.

        Raises:
            AuthorizationError: The caller does not hold `channels:manage`.
        """
        self._require_manager(ctx)
        pending, total = await channel_binding_request_repo.list_pending(
            self.db, organization_id=ctx.organization_id, skip=skip, limit=limit
        )
        return await self._reads(pending), total

    async def list_for_agent(
        self, ctx: AuthContext, agent_id: UUID
    ) -> list[ChannelBindingRequestRead]:
        """The pending requests that name an agent the caller may see: all of them for a
        holder of `channels:manage`, the caller's own for anyone else.

        Raises:
            NotFoundError: The agent is not the caller's to see.
        """
        agent = await AgentRegistryService(self.db).get(ctx, agent_id)
        pending = await channel_binding_request_repo.list_for_agent(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            requester_user_id=None if ctx.has(Perm.CHANNELS_MANAGE) else ctx.user_id,
        )
        return await self._reads(pending)

    async def approve(self, ctx: AuthContext, request_id: UUID) -> ChannelBindingRequestRead:
        """Apply what a pending request asks, as the approver, and tell the requester.

        Raises:
            AuthorizationError: The caller does not hold `channels:manage`.
            NotFoundError: No such request in the caller's organization.
            ConcurrentChangeError: It was decided, voided or replaced in the meantime; or
                its requester is not the member who made it (they were removed and
                invited again since); or another agent is bound to the bot now.
            BadRequestError: The change would leave a bot that answers people with no
                account with no spending limit.
        """
        bot, request = await self._pending(ctx, request_id)
        await self._requester_stands(request)
        await self._bot_not_taken(bot, request)
        await self._apply(ctx, request)
        # Binding the agent voided every pending request on the bot, this one among them;
        # the request is locked and was checked pending, so settling it ends it approved.
        return await self._reads_one(
            await self._decide(ctx, bot, request, approved=True)
        )

    async def decline(self, ctx: AuthContext, request_id: UUID) -> ChannelBindingRequestRead:
        """Decline a pending request. Nothing is applied.

        Raises:
            AuthorizationError: The caller does not hold `channels:manage`.
            NotFoundError: No such request in the caller's organization.
            ConcurrentChangeError: It was decided, voided or replaced in the meantime.
        """
        bot, request = await self._pending(ctx, request_id)
        return await self._reads_one(
            await self._decide(ctx, bot, request, approved=False)
        )

    async def _pending(
        self, ctx: AuthContext, request_id: UUID
    ) -> tuple[ChannelBot, ChannelBindingRequest]:
        """The bot and one of its requests, still pending, for a caller who may decide it.

        Locks the agent, the bot, the binding a change of one is about and the request, in
        that order (see the module docstring).
        """
        self._require_manager(ctx)
        found = await channel_binding_request_repo.get(
            self.db, request_id, organization_id=ctx.organization_id
        )
        if found is None:
            raise _not_found("Request", request_id=str(request_id))
        agent = await agent_repo.get(
            self.db, found.agent_id, organization_id=ctx.organization_id, for_update=True
        )
        if agent is None:
            raise _gone(request_id)
        bot = await channel_bot_repo.get_for_org(
            self.db, found.channel_bot_id, organization_id=ctx.organization_id, for_update=True
        )
        if bot is None:
            raise _gone(request_id)
        if found.exposure_id is not None:
            exposure = await agent_exposure_repo.get(
                self.db, found.exposure_id, organization_id=ctx.organization_id, for_update=True
            )
            if exposure is None:
                raise _gone(request_id)
        request = await channel_binding_request_repo.lock(
            self.db, request_id, organization_id=ctx.organization_id
        )
        if request is None:
            raise _gone(request_id)
        if request.status != BindingRequestStatus.PENDING.value:
            raise ConcurrentChangeError(
                message="This request was already decided, or no longer applies.",
                details={"request_id": request.id, "status": request.status},
            )
        return bot, request

    async def _requester_stands(self, request: ChannelBindingRequest) -> None:
        """Refuse a request made under a membership the requester no longer holds.

        Re-inviting a member makes a new membership, and a request is the member's, not
        the person's. Declining stays open, so a manager can clear such a request.
        """
        membership = await member_repo.get_active(
            self.db,
            organization_id=request.organization_id,
            user_id=request.requester_user_id,
        )
        if membership is None or membership.id != request.requester_membership_id:
            raise ConcurrentChangeError(
                message="This request was made under a membership that has ended.",
                details={"request_id": request.id},
            )

    async def _bot_not_taken(self, bot: ChannelBot, request: ChannelBindingRequest) -> None:
        """Refuse a request whose bot another agent serves now. Nothing is written: the
        refusal rolls the transaction back, so the request stays pending until somebody
        declines it."""
        binding = await agent_exposure_repo.bound_to_bot(self.db, channel_bot_id=bot.id)
        if binding is None or binding.agent_id == request.agent_id:
            return
        raise ConcurrentChangeError(
            message="Another agent is bound to this bot now, so this request no longer applies.",
            details={"request_id": request.id},
        )

    async def _apply(self, ctx: AuthContext, request: ChannelBindingRequest) -> None:
        """Do what the request asks, as the approver, through the service that owns
        bindings and its checks."""
        # Imported here: the exposure service files requests through this module.
        from app.services.agent_exposure import AgentExposureService

        exposures = AgentExposureService(self.db)
        if request.kind == BindingRequestKind.BIND.value:
            await exposures.create(
                ctx,
                request.agent_id,
                ExposureCreate.model_validate(
                    {
                        "channel_bot_id": request.channel_bot_id,
                        "environment_id": request.environment_id,
                        "session_scope": request.session_scope,
                    }
                ),
            )
            return
        assert request.exposure_id is not None  # only a new binding has none yet
        changes = (
            ExposureUpdate(environment_id=request.environment_id)
            if request.kind == BindingRequestKind.ENVIRONMENT.value
            else ExposureUpdate(is_active=True)
        )
        await exposures.update(ctx, request.agent_id, request.exposure_id, changes)

    async def _decide(
        self,
        ctx: AuthContext,
        bot: ChannelBot,
        request: ChannelBindingRequest,
        *,
        approved: bool,
    ) -> ChannelBindingRequest:
        """Settle the request, audit the decision and tell the one who asked."""
        status = BindingRequestStatus.APPROVED if approved else BindingRequestStatus.DECLINED
        settled = await channel_binding_request_repo.settle(
            self.db, request, status=status, decided_by_user_id=ctx.user_id
        )
        agent = await agent_repo.get(self.db, settled.agent_id, organization_id=ctx.organization_id)
        assert agent is not None  # a request goes with its agent
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=f"channel.binding_request_{status.value}",
            target_type="channel_bot",
            target_id=str(bot.id),
            details={
                "request_id": str(settled.id),
                "kind": settled.kind,
                "requester": str(settled.requester_user_id),
                "agent_id": str(agent.id),
                "channel_bot_id": str(bot.id),
            },
        )
        await NotificationService(self.db).channel_binding_decided(
            organization_id=ctx.organization_id,
            request_id=settled.id,
            kind=settled.kind,
            approved=approved,
            agent_id=agent.id,
            agent_name=agent.name,
            bot_name=bot.name,
            requester_id=settled.requester_user_id,
        )
        return settled
