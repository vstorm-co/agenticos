"""Every row this deployment holds *about one person*, for export and for erasure.

GDPR art. 15 asks what you hold about somebody and art. 17 asks you to remove it,
and both questions are answered from one place on purpose: an inventory that
lists a table for the export and forgets it for the deletion is worse than no
inventory, because it reads as complete (#1421).

What belongs here is the rows whose *subject* is the person. A row they merely
created - an agent, a knowledge base, a secret - belongs to the organization and
is handled by `UserService._release_owned_rows`, which hands it on rather than
removing it: deleting a colleague's account must not delete the agent the team
runs on. `docs/security.md` has the table, with the reason for each.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, func, or_, select, update
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.api_key import ApiKey
from app.db.models.browser_sign_in import BrowserSignIn
from app.db.models.case_generation import CaseProposal
from app.db.models.case_score import CaseScore
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.dashboard_layout import DashboardLayout
from app.db.models.dataset import DatasetCase
from app.db.models.knowledge_gap import KnowledgeSearch
from app.db.models.memory import AgentMemoryFile
from app.db.models.message_rating import MessageRating
from app.db.models.notification import Notification
from app.db.models.notification_preference import NotificationChannelPreference
from app.db.models.oauth import OAuthGrant
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.session import Session
from app.db.models.user_slash_command import UserSlashCommand


async def conversations_of(db: AsyncSession, user_id: UUID) -> list[Conversation]:
    """The threads this person started, and the project chats they typed in, newest first.

    A project's chat is several people's, so whoever started it is not the only
    one with turns there: typing in one makes it part of this person's export
    whether or not they began it.
    """
    typed_in = (
        select(Message.id)
        .where(Message.conversation_id == Conversation.id, Message.author_user_id == user_id)
        .correlate(Conversation)
        .exists()
    )
    result = await db.execute(
        select(Conversation)
        .where(
            or_(
                Conversation.user_id == user_id,
                and_(Conversation.project_id.is_not(None), typed_in),
            )
        )
        .order_by(Conversation.created_at.desc())
    )
    return list(result.scalars().all())


async def messages_in(
    db: AsyncSession, conversation_ids: list[UUID], *, user_id: UUID
) -> list[Message]:
    """This person's turns of those threads, in the order they happened.

    Outside a project, every turn: a thread's answers are part of what the
    person is asking to see, and a transcript with every second turn removed
    answers nothing. In a project's chat the other members' turns are theirs,
    not this person's, so it holds what this person typed and the turns that
    answered it - everything after one of their turns up to somebody else's.
    """
    if not conversation_ids:
        return []
    result = await db.execute(
        select(Message, Conversation.project_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.conversation_id.in_(conversation_ids))
        .order_by(Message.conversation_id, Message.ordinal)
    )
    kept: list[Message] = []
    thread: UUID | None = None
    theirs = False
    for message, project_id in result.all():
        if message.conversation_id != thread:
            thread, theirs = message.conversation_id, False
        if project_id is None:
            kept.append(message)
            continue
        if message.role == "user":
            theirs = message.author_user_id == user_id
        if theirs:
            kept.append(message)
    return kept


async def tool_calls_in(db: AsyncSession, message_ids: list[UUID]) -> list[ToolCall]:
    """What the agent did on their behalf, with the arguments and the answer.

    A tool call holds what was sent out to answer them and what came back - an
    address looked up, a document retrieved, a row read - which is theirs as
    much as the turn that caused it. The transcript without it says an agent did
    something and not what.
    """
    if not message_ids:
        return []
    result = await db.execute(
        select(ToolCall)
        .where(ToolCall.message_id.in_(message_ids))
        .order_by(ToolCall.message_id, ToolCall.started_at)
    )
    return list(result.scalars().all())


async def memberships_of(db: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    """Which organizations they belong to, and as what.

    A row referencing the person directly, and one they cannot see anywhere else
    in an export: `admin_detail` already shows it to an administrator, so
    leaving it out made "everything about you" untrue in the one place a reader
    could check.
    """
    result = await db.execute(
        select(
            OrganizationMember.id,
            Organization.name,
            OrganizationMember.role,
            OrganizationMember.joined_at,
        )
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user_id)
        .order_by(Organization.name)
    )
    return [
        {"id": str(row_id), "organization": name, "role": role, "joined_at": joined_at}
        for row_id, name, role, joined_at in result.all()
    ]


async def ratings_of(db: AsyncSession, user_id: UUID) -> list[MessageRating]:
    """What they marked as good or bad, which is an opinion they expressed."""
    result = await db.execute(
        select(MessageRating)
        .where(MessageRating.user_id == user_id)
        .order_by(MessageRating.created_at.desc())
    )
    return list(result.scalars().all())


async def verdicts_of(db: AsyncSession, user_id: UUID) -> list[CaseScore]:
    """Eval scores they decided, whose verdict and note are an opinion they expressed."""
    result = await db.execute(
        select(CaseScore)
        .where(CaseScore.reviewed_by_user_id == user_id)
        .order_by(CaseScore.reviewed_at.desc())
    )
    return list(result.scalars().all())


def _runs_they_started(user_id: UUID) -> Select[UUID]:
    """Their runs, not a visitor's a surface they published ran in their name."""
    return select(AgentRun.id).where(
        AgentRun.user_id == user_id, AgentRun.initiated_by_publisher_fallback.is_(False)
    )


async def scored_answers_of(db: AsyncSession, user_id: UUID) -> list[CaseScore]:
    """Eval scores of runs they started, each holding a copy of the answer it scored."""
    result = await db.execute(
        select(CaseScore)
        .where(CaseScore.answer.is_not(None), CaseScore.run_id.in_(_runs_they_started(user_id)))
        .order_by(CaseScore.created_at.desc())
    )
    return list(result.scalars().all())


async def sessions_of(db: AsyncSession, user_id: UUID) -> list[Session]:
    """Where and when they signed in. Never the credential - the row holds a hash."""
    result = await db.execute(
        select(Session).where(Session.user_id == user_id).order_by(Session.created_at.desc())
    )
    return list(result.scalars().all())


async def runs_started_by(db: AsyncSession, user_id: UUID) -> list[AgentRun]:
    """Runs they started, for what each cost and which agent answered.

    Not the runs that carry their id only as the publisher standing in for
    somebody else - a widget visitor, an unlinked channel sender: those were
    started by another person, and listing them made the publisher's export
    an account of strangers' activity (#2235). And the runs a chat account of
    theirs started before they linked it: linking is what attributes those
    runs to them, after the fact, whoever they ran as at the time.
    """
    linked = select(ChannelIdentity.id).where(ChannelIdentity.user_id == user_id)
    result = await db.execute(
        select(AgentRun)
        .where(
            or_(
                and_(
                    AgentRun.user_id == user_id,
                    AgentRun.initiated_by_publisher_fallback.is_(False),
                ),
                AgentRun.channel_identity_id.in_(linked),
            )
        )
        .order_by(AgentRun.created_at.desc())
    )
    return list(result.scalars().all())


def _proposals_drafted_from(user_id: UUID) -> ColumnElement[bool]:
    """A proposal drafted from this person: from a question they typed, a thread they
    own or a run they started. A project's chat is continued by its members, so the
    thread's owner alone does not say whose question it was."""
    return or_(
        CaseProposal.source_message_id.in_(
            select(Message.id).where(Message.author_user_id == user_id)
        ),
        CaseProposal.source_conversation_id.in_(
            select(Conversation.id).where(Conversation.user_id == user_id)
        ),
        CaseProposal.source_run_id.in_(select(AgentRun.id).where(AgentRun.user_id == user_id)),
    )


async def case_proposals_from(db: AsyncSession, user_id: UUID) -> list[CaseProposal]:
    """Drafted dataset cases taken from their questions, conversations or runs, still waiting.

    Unscoped by organization on purpose, like every read of an export: it is
    about one person, in every organization they were in.
    """
    result = await db.execute(
        select(CaseProposal)
        .where(_proposals_drafted_from(user_id))
        .order_by(CaseProposal.created_at.desc(), CaseProposal.id)
    )
    return list(result.scalars().all())


def _their_searches(user_id: UUID) -> ColumnElement[bool]:
    """Searches of runs they started.

    By the run, never the conversation: a project chat is continued by other
    members, whose questions are in it too.
    """
    return KnowledgeSearch.run_id.in_(_runs_they_started(user_id))


async def knowledge_searches_of(db: AsyncSession, user_id: UUID) -> list[KnowledgeSearch]:
    """What agents searched their knowledge bases for while answering them.

    Unscoped by organization on purpose, like the rest of an export: it answers
    for one person in every organization they were in.
    """
    result = await db.execute(
        select(KnowledgeSearch)
        .where(_their_searches(user_id))
        .order_by(KnowledgeSearch.created_at.desc())
    )
    return list(result.scalars().all())


async def purge_knowledge_searches_of(db: AsyncSession, user_id: UUID) -> int:
    """Remove the searches made while answering this person, in every organization.

    Unscoped by organization on purpose: an erasure is about one person. A
    search goes with its run or its conversation, and neither goes with the
    account: `agent_runs.user_id` is `SET NULL` because the run is the
    organization's record of what it spent, and a project chat is kept for the
    team.

    Returns:
        How many searches were removed.
    """
    result = await db.execute(sa_delete(KnowledgeSearch).where(_their_searches(user_id)))
    await db.flush()
    # `execute` is typed to return `Result`, which has no `rowcount`; a DML
    # statement actually returns a `CursorResult`, which does (see `resource_grant`).
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]


async def memory_about(db: AsyncSession, owner_key: str) -> list[AgentMemoryFile]:
    """What every agent in every organization has written down about them."""
    result = await db.execute(
        select(AgentMemoryFile)
        .where(AgentMemoryFile.owner_key == owner_key)
        .order_by(AgentMemoryFile.updated_at.desc())
    )
    return list(result.scalars().all())


async def identities_of(db: AsyncSession, user_id: UUID) -> list[ChannelIdentity]:
    """Their Slack, Telegram and Mattermost accounts, as this deployment knows them."""
    result = await db.execute(select(ChannelIdentity).where(ChannelIdentity.user_id == user_id))
    return list(result.scalars().all())


async def slash_commands_of(db: AsyncSession, user_id: UUID) -> list[UserSlashCommand]:
    result = await db.execute(select(UserSlashCommand).where(UserSlashCommand.user_id == user_id))
    return list(result.scalars().all())


async def dashboard_layouts_of(db: AsyncSession, user_id: UUID) -> list[DashboardLayout]:
    result = await db.execute(select(DashboardLayout).where(DashboardLayout.user_id == user_id))
    return list(result.scalars().all())


async def browser_sign_ins_of(db: AsyncSession, user_id: UUID) -> list[BrowserSignIn]:
    """The sites they kept a browser sign-in to, in every organization."""
    result = await db.execute(select(BrowserSignIn).where(BrowserSignIn.user_id == user_id))
    return list(result.scalars().all())


async def api_keys_of(db: AsyncSession, user_id: UUID) -> list[ApiKey]:
    """The keys they issued, revoked ones included.

    Not the platform's own short-lived keys for the in-app assistant, nor the
    access tokens an OAuth client was handed: both are credentials minted per
    run or per refresh, and the grant behind the second is exported on its own.
    """
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.user_id == user_id,
            ApiKey.internal.is_(False),
            ApiKey.oauth_grant_id.is_(None),
        )
    )
    return list(result.scalars().all())


async def oauth_grants_of(db: AsyncSession, user_id: UUID) -> list[OAuthGrant]:
    """Every consent they gave a client, revoked ones included."""
    result = await db.execute(select(OAuthGrant).where(OAuthGrant.user_id == user_id))
    return list(result.scalars().all())


async def notifications_of(db: AsyncSession, user_id: UUID) -> list[Notification]:
    """Every notification addressed to them, whether the inbox still shows it.

    A row hidden by a channel opt-out (`in_app_visible=false`) is still a row
    this deployment holds about them, and an art. 15 answer that returned only
    what the bell happens to render would be a partial answer that does not
    say so.
    """
    result = await db.execute(
        select(Notification)
        .where(Notification.recipient_user_id == user_id)
        .order_by(Notification.created_at.desc())
    )
    return list(result.scalars().all())


async def notification_preferences_of(
    db: AsyncSession, user_id: UUID
) -> list[NotificationChannelPreference]:
    result = await db.execute(
        select(NotificationChannelPreference).where(
            NotificationChannelPreference.user_id == user_id
        )
    )
    return list(result.scalars().all())


async def purge_memory_about(db: AsyncSession, owner_key: str) -> int:
    """Delete what every agent remembers about them, in every organization.

    **Not reached by any cascade, and that is the gap this closes.**
    `agent_memory_files.owner_key` is a string - `person:<user_id>` - with no
    foreign key to `users`, so deleting the row the key names left every note
    behind: personal data about somebody who has asked to be forgotten, keyed
    by an id that no longer resolves to anybody.

    Organization-wide rather than per organization, because the account is
    going: `MemoryService.forget_person` is the scoped version, for a person who
    is still a member somewhere else.

    Returns:
        How many notes were removed, for the audit entry.
    """
    result = await db.execute(
        sa_delete(AgentMemoryFile).where(AgentMemoryFile.owner_key == owner_key)
    )
    await db.flush()
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]


async def purge_identities_of(db: AsyncSession, user_id: UUID) -> int:
    """Delete their platform identities rather than unlinking them.

    The foreign key is `SET NULL`, which leaves the row: a Slack user id, a
    username and a display name, about a person whose account is gone, linked to
    nobody and reachable by nothing. That is personal data retained for no
    purpose, which is the one thing art. 17 is unambiguous about.

    Returns:
        How many identities were removed, for the audit entry.
    """
    result = await db.execute(sa_delete(ChannelIdentity).where(ChannelIdentity.user_id == user_id))
    await db.flush()
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]


_NO_SOURCE: dict[str, None] = {
    "source_run_id": None,
    "source_conversation_id": None,
    "source_message_id": None,
}


async def unlink_dataset_cases_from_conversation(
    db: AsyncSession, conversation_id: UUID, *, organization_id: UUID
) -> int:
    """Cut every dataset case taken from this conversation loose from it, and drop its drafts.

    A case keeps the question and answer it copied, which is the point of
    taking one, but not where they came from: the run outlives a deleted
    conversation, and a link to it would still lead back to who asked. A
    generated draft nobody has accepted yet is not kept at all - nobody chose
    to keep it, and its source is going. Run *before* the conversation goes,
    while `source_conversation_id` still names it.

    Returns:
        How many case revisions were unlinked.
    """
    await db.execute(
        sa_delete(CaseProposal).where(
            CaseProposal.source_conversation_id == conversation_id,
            CaseProposal.organization_id == organization_id,
        )
    )
    result = await db.execute(
        update(DatasetCase)
        .where(
            DatasetCase.source_conversation_id == conversation_id,
            DatasetCase.organization_id == organization_id,
        )
        .values(**_NO_SOURCE)
    )
    await db.flush()
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]


async def unlink_dataset_cases_of(db: AsyncSession, user_id: UUID) -> int:
    """Cut every dataset case taken from this person's conversations or runs loose.

    Unscoped by organization on purpose: an erasure is about one person, in
    every organization they were in. The case text stays - it was copied to
    outlive the transcript - and whatever personal data somebody typed into it
    stays with it; what goes is every link from the case back to the person.

    Returns:
        How many case revisions were unlinked.
    """
    result = await db.execute(
        update(DatasetCase)
        .where(
            or_(
                DatasetCase.source_conversation_id.in_(
                    select(Conversation.id).where(Conversation.user_id == user_id)
                ),
                DatasetCase.source_run_id.in_(
                    select(AgentRun.id).where(AgentRun.user_id == user_id)
                ),
            )
        )
        .values(**_NO_SOURCE)
    )
    await db.flush()
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]


async def delete_case_proposals_of(db: AsyncSession, user_id: UUID) -> int:
    """Delete every proposed case drafted from this person's questions, conversations or runs.

    Unscoped by organization on purpose, like :func:`unlink_dataset_cases_of`:
    an erasure is about one person, in every organization they were in.

    Returns:
        How many proposals were deleted.
    """
    result = await db.execute(sa_delete(CaseProposal).where(_proposals_drafted_from(user_id)))
    await db.flush()
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]


async def purge_scored_answers_of(db: AsyncSession, user_id: UUID) -> int:
    """Clear the answer copied into every eval score of a run this person started.

    Unscoped by organization, as every erasure is. The score stays - what the
    scorers and a reviewer concluded is the organization's - and its run link
    already goes when the run does; the copy of the answer goes now, with every
    result's reason, quotes and what the judge said, which can repeat it.

    Returns:
        How many scores lost their answer.
    """
    result = await db.execute(
        select(CaseScore).where(
            CaseScore.answer.is_not(None), CaseScore.run_id.in_(_runs_they_started(user_id))
        )
    )
    scores = list(result.scalars().all())
    for score in scores:
        score.answer = None
        score.results = [
            {**result, "reason": "", "unverified_quotes": [], "judge_said": None}
            for result in score.results
        ]
    await db.flush()
    return len(scores)


async def attachment_paths_in(db: AsyncSession, conversation_id: UUID) -> list[str]:
    """Where the files attached to one thread's turns are stored.

    Read *before* the conversation goes, because the rows cascade away with it
    and the bytes do not: `chat_files.message_id` is `ON DELETE CASCADE` from
    `messages`, which cascades from `conversations`, so deleting a thread removed
    every row that named a file and left the file itself on disk - personal data
    kept after somebody asked for it to be deleted, and reachable by nothing
    (#1421, FA-015).
    """
    result = await db.execute(
        select(ChatFile.storage_path)
        .join(Message, ChatFile.message_id == Message.id)
        .where(Message.conversation_id == conversation_id, ChatFile.storage_path.is_not(None))
    )
    return [path for path in result.scalars().all() if path]


async def export_size(db: AsyncSession, conversation_ids: list[UUID]) -> int:
    """How many characters of message content one export would carry.

    The export is assembled in memory and serialized in one response, and
    `MessageCreate.content` has no ceiling - so without a preflight the caller
    decides how much memory the worker spends, and five concurrent exports of a
    conversation somebody has been filling take the process with them. Counted
    in the database, where the rows already are.
    """
    if not conversation_ids:
        return 0
    total = await db.scalar(
        select(func.coalesce(func.sum(func.length(Message.content)), 0)).where(
            Message.conversation_id.in_(conversation_ids)
        )
    )
    return int(total or 0)


async def attachment_paths_of(db: AsyncSession, user_id: UUID) -> list[str]:
    """Where every file this person attached to any of their threads is stored.

    The account-deletion counterpart of `attachment_paths_in`. `chat_files`
    cascades from `users`, so the rows go with the account and the bytes stay:
    an erasure that leaves the uploads on disk has not erased them.
    """
    result = await db.execute(
        select(ChatFile.storage_path).where(
            ChatFile.user_id == user_id, ChatFile.storage_path.is_not(None)
        )
    )
    return [path for path in result.scalars().all() if path]


async def workspaces_of(db: AsyncSession, owner_ref: str) -> list[AgentWorkspace]:
    """The workspaces that are this person's own, by the string that names them."""
    result = await db.execute(
        select(AgentWorkspace).where(
            AgentWorkspace.scope == "user", AgentWorkspace.owner_ref == owner_ref
        )
    )
    return list(result.scalars().all())


async def purge_workspaces_of(db: AsyncSession, owner_ref: str) -> int:
    """Delete their user-scoped workspaces, which no cascade reaches.

    `agent_workspaces.owner_ref` is a string, like `agent_memory_files.owner_key`
    and for the same reason - a workspace can belong to a conversation, an agent
    or a person - so there is no foreign key to follow when the person goes. The
    row survives holding a dangling owner reference, and a state-backed
    workspace holds the files themselves (#1421).

    Returns:
        How many workspaces were removed, for the audit entry.
    """
    result = await db.execute(
        sa_delete(AgentWorkspace).where(
            AgentWorkspace.scope == "user", AgentWorkspace.owner_ref == owner_ref
        )
    )
    await db.flush()
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]


def as_rows(items: list[Any], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """The named fields of each row, as JSON-ready values.

    Named rather than "everything on the model", because an export is a document
    handed to a person and a model carries columns that are neither theirs nor
    meaningful to them - a hashed credential, an internal flag, a foreign key to
    a row they cannot see. Adding a column to a table must not silently add it to
    what every person can download.

    `getattr` without a default on purpose: a field named here that the model
    does not have is a mistake in this file, and answering it with `null` made
    every exported conversation say `archived: null` and every dashboard layout
    `widgets: null` - a value that reads as "we hold nothing" for data that is
    right there on the row.
    """
    return [{field: getattr(item, field) for field in fields} for item in items]
