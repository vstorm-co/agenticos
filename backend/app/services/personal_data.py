"""What this deployment holds about one person: handing it over, and removing it.

GDPR art. 15 (access) and art. 17 (erasure) are the two requests a client's data
protection officer forwards on day one of any deployment with EU staff or
customers, and both are answered from one inventory (#1421). The inventory itself
is prose, in `docs/security.md`: every table with a reference to a person, and
whether it cascades, is anonymised, or is retained with the reason.

**The line this service draws.** What is *about* a person goes: their threads,
their ratings, their sessions, what agents wrote down about them, the platform
accounts they linked. What they merely *created* belongs to the organization -
an agent the team runs on, a knowledge base, a stored credential - and is handed
on rather than removed, which `UserService._release_owned_rows` has done since
#9. Deleting a colleague's account must not delete the agent the team depends on.

**What an export is not.** It is a document a person reads, not a dump of every
column a row happens to carry. Each table names its fields, so adding a column
never silently adds it to what everybody can download - and the audit trail is
deliberately absent: an entry naming a deleted actor is worse than one naming
nobody, so those are retained rather than exported or removed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.memory_keys import person_owner_key
from app.db.locks import LockScope, hold_subject
from app.repositories import personal_data_repo, user_repo
from app.schemas.personal_data import PersonalDataExport, PersonalDataPurge

logger = logging.getLogger(__name__)

_CONVERSATION_FIELDS = ("id", "title", "created_at", "updated_at", "is_archived")
_MESSAGE_FIELDS = ("id", "conversation_id", "role", "content", "ordinal", "created_at")
_TOOL_CALL_FIELDS = ("id", "message_id", "tool_name", "args", "result", "status", "started_at")
_RATING_FIELDS = ("id", "message_id", "rating", "comment", "created_at")
_SESSION_FIELDS = ("id", "device_name", "device_type", "ip_address", "created_at", "last_used_at")
_RUN_FIELDS = ("id", "agent_id", "status", "surface", "cost_usd", "created_at")
_MEMORY_FIELDS = ("id", "agent_id", "name", "content", "updated_at")
_IDENTITY_FIELDS = ("id", "platform", "platform_user_id", "platform_username")
_COMMAND_FIELDS = ("id", "name", "prompt", "created_at")
_LAYOUT_FIELDS = ("id", "organization_id", "entries", "updated_at")
_NOTIFICATION_FIELDS = (
    "id",
    "event_type",
    "summary",
    "context_url",
    "organization_id",
    "in_app_visible",
    "read_at",
    "created_at",
)
_NOTIFICATION_PREFERENCE_FIELDS = ("event_type", "channel", "enabled", "updated_at")

#: The account's own values, as an export hands them over.
#:
#: Named here for the same reason every other list is: a column added to `users`
#: must not arrive in everybody's download by itself. What is absent is absent on
#: purpose - the password hash, the credential version, the app-admin flag and
#: every internal id, none of which is the person's data to take away.
_PROFILE_FIELDS = (
    "id",
    "email",
    "full_name",
    "is_active",
    "created_at",
    "avatar_url",
    "avatar_color",
    "onboarding_completed_at",
    "oauth_provider",
    "notify_budget_alerts",
    "notify_approval_requests",
    "notify_usage_reports",
)


class PersonalDataService:
    """One person's data, read out or removed."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def export(
        self, user_id: UUID, *, actor_user_id: UUID, reason: str | None = None
    ) -> PersonalDataExport:
        """Everything this deployment holds about `user_id`, as one document.

        **Audited, including a person exporting themselves.** An export is a copy
        of everything about somebody leaving the deployment in one file, which is
        exactly the shape of a data breach when the person asking is not who they
        claim to be. The entry records who asked, about whom, and - for an
        administrator - why.

        Args:
            user_id: Whose data.
            actor_user_id: Who is asking. The same person, or an app admin.
            reason: Why, recorded when an administrator exports somebody else's.
        """
        user = await user_repo.get_by_id(self.db, user_id)
        if user is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(message="User not found", details={"user_id": user_id})

        conversations = await personal_data_repo.conversations_of(self.db, user_id)
        conversation_ids = [conversation.id for conversation in conversations]
        await self._refuse_if_too_large(conversation_ids)
        messages = await personal_data_repo.messages_in(self.db, conversation_ids)
        profile = personal_data_repo.as_rows([user], _PROFILE_FIELDS)[0]
        profile["id"] = str(user.id)
        export = PersonalDataExport(
            exported_at=datetime.now(UTC),
            profile=profile,
            conversations=personal_data_repo.as_rows(conversations, _CONVERSATION_FIELDS),
            messages=personal_data_repo.as_rows(messages, _MESSAGE_FIELDS),
            tool_calls=personal_data_repo.as_rows(
                await personal_data_repo.tool_calls_in(
                    self.db, [message.id for message in messages]
                ),
                _TOOL_CALL_FIELDS,
            ),
            memberships=await personal_data_repo.memberships_of(self.db, user_id),
            ratings=personal_data_repo.as_rows(
                await personal_data_repo.ratings_of(self.db, user_id), _RATING_FIELDS
            ),
            sessions=personal_data_repo.as_rows(
                await personal_data_repo.sessions_of(self.db, user_id), _SESSION_FIELDS
            ),
            runs=personal_data_repo.as_rows(
                await personal_data_repo.runs_started_by(self.db, user_id), _RUN_FIELDS
            ),
            memory=personal_data_repo.as_rows(
                await personal_data_repo.memory_about(self.db, person_owner_key(user_id)),
                _MEMORY_FIELDS,
            ),
            channel_identities=personal_data_repo.as_rows(
                await personal_data_repo.identities_of(self.db, user_id), _IDENTITY_FIELDS
            ),
            slash_commands=personal_data_repo.as_rows(
                await personal_data_repo.slash_commands_of(self.db, user_id), _COMMAND_FIELDS
            ),
            dashboard_layouts=personal_data_repo.as_rows(
                await personal_data_repo.dashboard_layouts_of(self.db, user_id), _LAYOUT_FIELDS
            ),
            notifications=personal_data_repo.as_rows(
                await personal_data_repo.notifications_of(self.db, user_id), _NOTIFICATION_FIELDS
            ),
            notification_preferences=personal_data_repo.as_rows(
                await personal_data_repo.notification_preferences_of(self.db, user_id),
                _NOTIFICATION_PREFERENCE_FIELDS,
            ),
        )

        details: dict[str, Any] = {
            "conversations": len(export.conversations),
            "messages": len(export.messages),
            "own_request": actor_user_id == user_id,
        }
        if reason is not None:
            details["reason"] = reason
        await record_audit(
            self.db,
            actor_user_id=actor_user_id,
            action="personal_data.exported",
            target_type="user",
            target_id=str(user_id),
            details=details,
        )
        return export

    async def _refuse_if_too_large(self, conversation_ids: list[UUID]) -> None:
        """Refuse an export this process would have to hold in memory whole.

        The document is assembled and serialized in one response and
        `MessageCreate.content` has no ceiling, so without this the caller
        decides how much memory a worker spends: a member can append to their
        own thread until an export of it exhausts the container, and the hourly
        limit bounds how often that happens rather than how large one is.

        A refusal rather than a truncation, because a partial answer to an
        art. 15 request that does not say it is partial is worse than no answer,
        and `agenticos cmd data-protection-report` plus a direct query is the
        operator's path for the rare person this catches. `docs/security.md`
        says so beside the inventory.

        Raises:
            BadRequestError: The person's messages are larger than
                `PERSONAL_DATA_EXPORT_MAX_CHARS`, naming both numbers so an
                operator can act on it.
        """
        size = await personal_data_repo.export_size(self.db, conversation_ids)
        ceiling = settings.PERSONAL_DATA_EXPORT_MAX_CHARS
        if size > ceiling:
            raise BadRequestError(
                message=(
                    "This account holds more conversation text than one export can carry. "
                    "An administrator can produce it from the database instead."
                ),
                details={"characters": size, "limit": ceiling},
            )

    async def purge(self, user_id: UUID) -> PersonalDataPurge:
        """Remove what no cascade reaches, before the user row goes.

        Three tables hold data *about* a person with no foreign key that would
        take it with them:

        - `agent_memory_files`, keyed by the string `person:<user_id>` - notes
          every agent wrote about them, in every organization, which a deleted
          account left behind entirely;
        - `channel_identities`, whose key is `SET NULL` - so the row survives
          holding a Slack user id, a username and a display name about somebody
          whose account is gone, linked to nobody;
        - `agent_workspaces` with `scope='user'`, whose `owner_ref` is a string
          for the same reason `owner_key` is - a workspace can belong to a
          conversation, an agent or a person - so no cascade follows it, and a
          state-backed one holds the person's files themselves.

        Called from `UserService.delete`, inside the same transaction, so a
        deletion that fails afterwards takes this with it.

        **Serialized against a concurrent memory write.** `owner_key` is a
        string with no foreign key, so nothing in the database stops a run
        writing a note about this person while the purge is reading the table -
        and a write that commits afterwards recreates exactly what was removed.
        Both sides take `PERSONAL_DATA_PER_USER`, so they queue, and the write
        that gets the lock second finds no account to write about.
        """
        # Held before the reads below, and released by this transaction's own
        # commit. A memory write for the same person takes it too, so the two
        # cannot interleave into a note that survives the account it is about.
        await hold_subject(self.db, LockScope.PERSONAL_DATA_PER_USER, user_id)
        notes = await personal_data_repo.purge_memory_about(self.db, person_owner_key(user_id))
        identities = await personal_data_repo.purge_identities_of(self.db, user_id)
        workspaces = await personal_data_repo.purge_workspaces_of(
            self.db, person_owner_key(user_id)
        )
        if notes or identities or workspaces:
            logger.info(
                "personal_data_purged",
                extra={
                    "user_id": str(user_id),
                    "notes": notes,
                    "identities": identities,
                    "workspaces": workspaces,
                },
            )
        return PersonalDataPurge(
            memory_notes=notes, channel_identities=identities, workspaces=workspaces
        )
