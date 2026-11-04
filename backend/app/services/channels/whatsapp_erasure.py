"""Erasing a WhatsApp customer on request (#2076).

A customer is the business-scoped id Meta gave one organization's bots, and what
this holds of them is spread over several stores: their chat account, its sessions,
the record the 24-hour window keeps, their threads and the files in them, what was
queued to send them, and what the people deciding their agent's calls were shown.
`forget` removes all of it in one transaction. The runs stay, as accounting: they
lose the link to the customer and keep their cost.

A customer who linked a member account is refused; unlink or delete the account
first. A run a worker is executing at the moment of the request is not stopped and
may write again; ask again once it has finished.
"""

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import BadRequestError, ConflictError
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.channel_bot import ChannelBot
from app.db.models.notification import NotificationEventType
from app.repositories import (
    agent_run_repo,
    channel_identity_repo,
    channel_link_request_repo,
    channel_prompt_repo,
    conversation_repo,
    customer_erasure_repo,
    whatsapp_customer_repo,
)
from app.services.channels.whatsapp_payload import platform_user_id_for
from app.services.notifications import approval_occurrence_id
from app.services.sandbox_workspace import SandboxWorkspaceService

NamedBy = Literal["bsuid", "phone"]
Via = Literal["console", "cli"]
_PARKED = frozenset({RunStatus.AWAITING_APPROVAL.value, RunStatus.AWAITING_ANSWER.value})
ERASED = "The customer's data was erased."
LINKED = (
    "This customer is linked to a member account. Unlink the account, or delete it, to erase them."
)


@dataclass(frozen=True)
class CustomerErasure:
    """What one erasure removed, as counts and nothing that names the customer."""

    identities: int = 0
    sessions: int = 0
    customers: int = 0
    conversations: int = 0
    workspaces: int = 0
    link_requests: int = 0
    prompts: int = 0
    runs_ended: int = 0
    approvals_ended: int = 0
    approvals_redacted: int = 0
    manifests: int = 0
    notifications: int = 0
    handback_jobs: int = 0
    handback_jobs_running: int = 0


class WhatsAppErasureService:
    """Erase one WhatsApp customer, in the caller's transaction."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def forget(
        self,
        bot: ChannelBot,
        *,
        bsuid: str,
        named_by: NamedBy,
        actor_user_id: UUID | None,
        via: Via,
    ) -> CustomerErasure:
        """Remove the customer from every store of the organization's WhatsApp bots.

        Args:
            bot: A bot of the organization the customer wrote to.
            bsuid: The customer's business-scoped id.
            named_by: How the person asking found them: `bsuid` or `phone`. Recorded
                as a word, never as the value.
            actor_user_id: Who asked, or `None` from the command line.
            via: `console` or `cli`.

        Raises:
            BadRequestError: If the bot is not a WhatsApp bot.
            ConflictError: If the customer is linked to a member account.
        """
        if bot.platform != "whatsapp":
            raise BadRequestError(
                message="Only a WhatsApp customer can be erased here",
                details={"bot_id": str(bot.id)},
            )
        organization_id = bot.organization_id
        platform_user_id = platform_user_id_for(organization_id, bsuid)
        # Locked, so a link confirmed at this moment waits for the erasure or is refused by it.
        identity = await channel_identity_repo.get_by_platform_user(
            self.db, "whatsapp", platform_user_id, for_update=True
        )
        if identity is not None and identity.user_id is not None:
            raise ConflictError(message=LINKED, details={"bot_id": str(bot.id)})

        bot_ids = await customer_erasure_repo.whatsapp_bot_ids(
            self.db, organization_id=organization_id
        )
        await whatsapp_customer_repo.lock_existing(
            self.db, organization_id=organization_id, bsuid=bsuid
        )
        runs: list[AgentRun] = []
        conversation_ids: list[UUID] = []
        if identity is not None:
            runs = await customer_erasure_repo.stranger_runs_of_identity(
                self.db, organization_id=organization_id, identity_id=identity.id
            )
            conversation_ids = await customer_erasure_repo.conversation_ids(
                self.db, organization_id=organization_id, identity_id=identity.id
            )
        run_ids = [run.id for run in runs]
        occurrences = await self._occurrences(organization_id, run_ids)
        runs_ended = await self._end_parked(organization_id, run_ids)
        approvals_ended = await customer_erasure_repo.end_pending_approvals(
            self.db, organization_id=organization_id, run_ids=run_ids, at=datetime.now(UTC)
        )
        approvals_redacted = await customer_erasure_repo.redact_approvals(
            self.db, organization_id=organization_id, run_ids=run_ids
        )
        manifests = await customer_erasure_repo.delete_manifests(
            self.db, organization_id=organization_id, run_ids=run_ids
        )
        notifications = await customer_erasure_repo.delete_notifications(
            self.db,
            organization_id=organization_id,
            event_type=NotificationEventType.APPROVAL_REQUESTED.value,
            occurrence_ids=occurrences,
        )
        handback_deleted, handback_running = await customer_erasure_repo.delete_handback_jobs(
            self.db,
            organization_id=organization_id,
            concurrency_keys=[f"channel-handback:{bot_id}:{bsuid}" for bot_id in bot_ids],
        )
        prompts = await customer_erasure_repo.delete_prompts(
            self.db, organization_id=organization_id, bot_ids=bot_ids, platform_chat_id=bsuid
        )
        link_requests = await channel_link_request_repo.delete_for_identity(
            self.db, platform="whatsapp", platform_user_id=platform_user_id
        )
        workspaces = await self._forget_conversations(organization_id, conversation_ids)
        customers = await customer_erasure_repo.delete_customers(
            self.db, organization_id=organization_id, bot_ids=bot_ids, bsuid=bsuid
        )
        sessions = 0
        if identity is not None:
            sessions = await customer_erasure_repo.delete_sessions(
                self.db, organization_id=organization_id, identity_id=identity.id
            )
            await self.db.delete(identity)
            await self.db.flush()

        counts = CustomerErasure(
            identities=int(identity is not None),
            sessions=sessions,
            customers=customers,
            conversations=len(conversation_ids),
            workspaces=workspaces,
            link_requests=link_requests,
            prompts=prompts,
            runs_ended=runs_ended,
            approvals_ended=approvals_ended,
            approvals_redacted=approvals_redacted,
            manifests=manifests,
            notifications=notifications,
            handback_jobs=handback_deleted,
            handback_jobs_running=handback_running,
        )
        await record_audit(
            self.db,
            actor_user_id=actor_user_id,
            organization_id=organization_id,
            action="channel.customer.forgotten",
            target_type="channel_bot",
            target_id=str(bot.id),
            details={"named_by": named_by, "via": via, **asdict(counts)},
        )
        return counts

    async def _occurrences(self, organization_id: UUID, run_ids: list[UUID]) -> list[str]:
        """The keys of the notifications that asked for these runs' approvals.

        A pause writes its approvals in one transaction, so they share a creation
        time; a run that parks again later has a second set, with its own key.
        """
        groups: dict[tuple[UUID, datetime], list[UUID]] = defaultdict(list)
        for approval in await customer_erasure_repo.approvals_of_runs(
            self.db, organization_id=organization_id, run_ids=run_ids
        ):
            groups[(approval.run_id, approval.created_at)].append(approval.id)
        return [approval_occurrence_id(ids) for ids in groups.values()]

    async def _end_parked(self, organization_id: UUID, run_ids: list[UUID]) -> int:
        """Cancel the parked runs, so none can be resumed or answered once the customer is gone."""
        ended = 0
        for run_id in run_ids:
            run = await agent_run_repo.claim_parked_run(
                self.db, run_id, organization_id=organization_id
            )
            if run is None or run.status not in _PARKED:
                continue
            await channel_prompt_repo.settle_open(self.db, run_id=run.id, by="erased")
            await agent_run_repo.finish_run(
                self.db,
                run=run,
                status=RunStatus.CANCELLED.value,
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
                cost_usd=run.cost_usd,
                cost_is_partial=run.cost_is_partial,
                ended_at=datetime.now(UTC),
                error=ERASED,
                paused_state=None,
            )
            ended += 1
        return ended

    async def _forget_conversations(self, organization_id: UUID, ids: list[UUID]) -> int:
        """Delete the threads and what they keep outside the database; returns the workspaces purged."""
        if not ids:
            return 0
        # Imported here: `services.conversation` reaches the channel bot service back.
        from app.services.conversation import ConversationService

        await ConversationService(self.db).forget_stored_files(organization_id, ids)
        sandboxes = SandboxWorkspaceService(self.db)
        ctx = AuthContext.anonymous(organization_id)
        workspaces = 0
        for conversation_id in ids:
            workspaces += await sandboxes.purge_for_conversation(
                ctx, conversation_id=conversation_id
            )
        for conversation in await customer_erasure_repo.conversations(
            self.db, organization_id=organization_id, ids=ids
        ):
            await conversation_repo.delete_conversation(self.db, db_conversation=conversation)
        return workspaces
