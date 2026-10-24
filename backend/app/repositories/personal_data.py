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

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Select,
    Text,
    and_,
    cast,
    exists,
    func,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy import case as sa_case
from sqlalchemy import delete as sa_delete
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.db.locks import LockScope, try_hold_subject
from app.db.models.agent_run import AgentRun, ToolApproval
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.api_key import ApiKey
from app.db.models.authoring import AuthoringRequest, SpecProposalHunk
from app.db.models.browser_sign_in import BrowserSignIn
from app.db.models.case_generation import CaseProposal
from app.db.models.case_score import CaseScore
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.chat_file import ChatFile
from app.db.models.context_proposal import ContextProposal
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.dashboard_layout import DashboardLayout
from app.db.models.dataset import DatasetCase
from app.db.models.eval_run import EvalRun, EvalRunCase
from app.db.models.intercepted_tool_call import InterceptedToolCall
from app.db.models.knowledge_gap import (
    DraftAuthor,
    KnowledgeGapClassification,
    KnowledgeGapMember,
    KnowledgeGapTopic,
    KnowledgeSearch,
)
from app.db.models.memory import AgentMemoryFile
from app.db.models.message_rating import MessageRating
from app.db.models.notification import Notification
from app.db.models.notification_preference import NotificationChannelPreference
from app.db.models.oauth import OAuthGrant
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.run_manifest import RunManifest
from app.db.models.session import Session
from app.db.models.skill_proposal import SkillProposal
from app.db.models.suggestion import Suggestion
from app.db.models.user import User
from app.db.models.user_slash_command import UserSlashCommand
from app.db.models.watch import Watch


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
            OrganizationMember.personal_starters,
            OrganizationMember.personal_starters_at,
        )
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user_id)
        .order_by(Organization.name)
    )
    # The first messages written for them there (#2301) are part of it: their
    # own requests, read back to them, and kept per organization.
    return [
        {
            "id": str(row_id),
            "organization": name,
            "role": role,
            "joined_at": joined_at,
            "personal_starters": starters,
            "personal_starters_at": starters_at,
        }
        for row_id, name, role, joined_at, starters, starters_at in result.all()
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


async def scored_answers_of(db: AsyncSession, user_id: UUID) -> list[CaseScore]:
    """Eval scores of runs they started, each holding a copy of the answer it scored."""
    result = await db.execute(
        select(CaseScore)
        .where(CaseScore.answer.is_not(None), CaseScore.run_id.in_(_runs_they_asked(user_id)))
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
    """A proposal drafted from this person: from a question they typed, a thread of
    their own outside any project, or a run they started.

    A project's chat is continued by its members, so its starter does not own the
    turns in it: a proposal drafted from a teammate's question there is the
    teammate's, and reaches the starter's export only through what they typed or
    ran themselves - never after their access to the project is gone.
    """
    return or_(
        CaseProposal.source_message_id.in_(
            select(Message.id).where(Message.author_user_id == user_id)
        ),
        CaseProposal.source_conversation_id.in_(
            select(Conversation.id).where(
                Conversation.user_id == user_id, Conversation.project_id.is_(None)
            )
        ),
        CaseProposal.source_run_id.in_(_runs_they_asked(user_id)),
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
    """Searches of runs that answered them, a chat account of theirs included.

    By the run, never the conversation: a project chat is continued by other
    members, whose questions are in it too.
    """
    return KnowledgeSearch.run_id.in_(_runs_they_asked(user_id))


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


async def clear_gap_reasons_of(db: AsyncSession, user_id: UUID) -> int:
    """Clear the knowledge gap classifier's reasons on the answers given to this person.

    A reason is a model's sentence about somebody's question and the answer it
    got. Unscoped by organization, as an erasure is: the verdict stays, so the
    answer is not paid for twice, and its words about them go. The answer
    itself survives the account in a project chat kept for the team.

    Returns:
        How many reasons were cleared.
    """
    answered = select(Message.id).where(Message.run_id.in_(_runs_they_asked(user_id)))
    result = await db.execute(
        update(KnowledgeGapClassification)
        .where(
            KnowledgeGapClassification.message_id.in_(answered),
            KnowledgeGapClassification.reason.is_not(None),
        )
        .values(reason=None)
    )
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


async def suggestions_for(db: AsyncSession, user_id: UUID) -> list[Suggestion]:
    """Every proposal the platform made them, dismissed ones included (#2301).

    Drawn from their own requests and kept after a "Not now" so the same one is
    not made twice - held about them either way.
    """
    result = await db.execute(select(Suggestion).where(Suggestion.user_id == user_id))
    return list(result.scalars().all())


async def watches_of(db: AsyncSession, user_id: UUID) -> list[Watch]:
    """What they asked the platform to watch in their connections, in their own words (#2301)."""
    result = await db.execute(select(Watch).where(Watch.user_id == user_id))
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
            CaseScore.answer.is_not(None), CaseScore.run_id.in_(_runs_they_asked(user_id))
        )
    )
    scores = list(result.scalars().all())
    for score in scores:
        forget_answer(score)
    await db.flush()
    return len(scores)


def forget_answer(score: CaseScore) -> None:
    """Drop the answer a score copied, and every part of its results that can repeat it."""
    score.answer = None
    score.results = [
        {**result, "reason": "", "unverified_quotes": [], "judge_said": None}
        for result in score.results
    ]


def _their_own_threads(user_id: UUID) -> Select[UUID]:
    """Their console and API conversations outside any project, whose turns are theirs alone.

    Not a channel thread, which belongs to whoever spoke first and holds
    everyone else who spoke in it: a turn there carries the speaker's identity.
    """
    spoken_in_a_channel = (
        select(Message.id)
        .where(Message.conversation_id == Conversation.id, Message.channel_identity_id.is_not(None))
        .exists()
    )
    return select(Conversation.id).where(
        Conversation.user_id == user_id,
        Conversation.project_id.is_(None),
        ~spoken_in_a_channel,
    )


def _runs_they_asked(user_id: UUID) -> Select[UUID]:
    """Runs answering a question of theirs: started by them, or by a chat account of theirs.

    Read before :func:`purge_identities_of` unlinks those accounts, as
    :func:`runs_started_by` reads them for the export.
    """
    linked = select(ChannelIdentity.id).where(ChannelIdentity.user_id == user_id)
    return select(AgentRun.id).where(
        or_(
            and_(
                AgentRun.user_id == user_id,
                AgentRun.initiated_by_publisher_fallback.is_(False),
            ),
            AgentRun.channel_identity_id.in_(linked),
        )
    )


def _their_turns(user_id: UUID) -> ColumnElement[bool]:
    linked = select(ChannelIdentity.id).where(ChannelIdentity.user_id == user_id)
    return or_(Message.author_user_id == user_id, Message.channel_identity_id.in_(linked))


async def anonymise_dataset_cases_of(
    db: AsyncSession, user_id: UUID, *, placeholder: str, at: datetime
) -> list[UUID]:
    """Replace the text of every case revision taken from this person, in every version.

    A case whose question they asked holds it, the turns before it and the
    answer they got, so all of it goes:
    the input becomes `placeholder`, and the history, both answers and the note -
    the comment a down-rating left - are emptied. The case keeps its id, its
    place, its expected tool calls and its checks, which are the curator's, and
    is marked anonymised, so its curator can rewrite it or remove it.

    Revisions are immutable everywhere else; an erasure is the exception, and
    reaches the revisions only earlier versions still hold. Unscoped by
    organization, as every erasure is. Found by `asked_by_user_id`, which the
    case keeps after its conversation and run are gone; a case with no asker
    recorded is found by the links :func:`unlink_dataset_cases_of` clears, so
    this runs first. A revision already anonymised is skipped.

    Returns:
        The revisions anonymised, whose copies in eval results go next.
    """
    result = await db.execute(
        update(DatasetCase)
        .where(
            or_(
                DatasetCase.asked_by_user_id == user_id,
                and_(
                    DatasetCase.asked_by_user_id.is_(None),
                    or_(
                        DatasetCase.source_conversation_id.in_(_their_own_threads(user_id)),
                        DatasetCase.source_run_id.in_(_runs_they_asked(user_id)),
                    ),
                ),
            ),
            DatasetCase.anonymised_at.is_(None),
        )
        .values(
            input=placeholder,
            history=[],
            reference_answer=None,
            counter_example=None,
            note=None,
            history_author_ids=[],
            noted_by_user_id=None,
            anonymised_at=at,
        )
        .returning(DatasetCase.id)
    )
    revisions = list(result.scalars().all())
    await db.flush()
    return revisions


async def purge_case_copies(db: AsyncSession, revision_ids: list[UUID]) -> int:
    """Clear what eval runs recorded while answering these case revisions.

    An agent asked an anonymised question answers about it, and its calls carry
    the question's details as arguments, so the answer and calls of every
    attempt go, and every score's copy of the answer with the parts of its
    results that can repeat it - and, through :func:`forget_runs`, what the
    agent's and the judge's runs kept of the question. The outcome stays:
    whether the case passed is the organization's.

    Returns:
        How many attempts and scores were cleared.
    """
    if not revision_ids:
        return 0
    answered = await db.execute(
        select(EvalRunCase.agent_run_id).where(
            EvalRunCase.case_revision_id.in_(revision_ids), EvalRunCase.agent_run_id.is_not(None)
        )
    )
    runs = {run_id for run_id in answered.scalars() if run_id is not None}
    attempts = await db.execute(
        update(EvalRunCase)
        .where(EvalRunCase.case_revision_id.in_(revision_ids))
        .values(answer=None, calls=[])
    )
    result = await db.execute(select(CaseScore).where(CaseScore.case_revision_id.in_(revision_ids)))
    scores = list(result.scalars().all())
    for score in scores:
        runs |= judge_runs_of(score)
        forget_answer(score)
    await forget_runs(db, runs)
    await db.flush()
    return (attempts.rowcount or 0) + len(scores)  # ty: ignore[unresolved-attribute]


_LOCK_NOT_AVAILABLE = "55P03"

_SPEC_PARTS = frozenset({"instructions", "system_prompts", "tools", "settings", "requests"})
"""What a manifest keeps after an erasure: what the spec decided and what each request
cost, never the messages, reviews or code that carried what was asked."""


def judge_runs_of(score: CaseScore) -> set[UUID]:
    """The runs a judge made to grade one score."""
    return {
        UUID(str(result["judge_run_id"])) for result in score.results if result.get("judge_run_id")
    }


async def forget_runs(db: AsyncSession, run_ids: Iterable[UUID]) -> None:
    """Drop what these runs kept of what they were asked, keeping the runs.

    A run's manifest is the request its model was handed - for an eval attempt,
    the case's question and history; for a judge, the answer too - and the
    calls an isolated run held back, or one that waited for approval, keep their
    arguments. The manifest keeps what the spec decided and what each request
    cost, and is marked trimmed; the messages go. The run row stays: what it
    cost is the organization's record.
    """
    wanted = list(set(run_ids))
    if not wanted:
        return
    manifests = await db.execute(select(RunManifest).where(RunManifest.run_id.in_(wanted)))
    for manifest in manifests.scalars():
        manifest.payload = {
            key: value for key, value in manifest.payload.items() if key in _SPEC_PARTS
        }
        manifest.truncated = True
    await db.execute(
        update(InterceptedToolCall).where(InterceptedToolCall.run_id.in_(wanted)).values(args={})
    )
    await db.execute(
        update(ToolApproval).where(ToolApproval.run_id.in_(wanted)).values(tool_args={})
    )
    await db.flush()


async def scrub_history_turns_of(
    db: AsyncSession, user_id: UUID, *, placeholder: str
) -> list[UUID]:
    """Replace their turns in the history of cases asked by somebody else.

    A case taken from a shared thread - a project chat, a channel - keeps the
    turns before its question, whoever wrote them. Their turn goes, and so do
    the agent's turns answering it, up to the next person's: an answer repeats
    what it was asked. Found by the author the case recorded for each turn; a
    turn with none recorded is matched against what they wrote in the thread the
    case came from, as long as that thread is there.

    Returns:
        The revisions that lost a turn, whose copies in eval results go next.
    """
    written = await db.execute(
        select(Message.conversation_id, Message.content).where(
            Message.role == "user", _their_turns(user_id)
        )
    )
    said: defaultdict[UUID, set[str]] = defaultdict(set)
    for conversation_id, content in written.tuples():
        said[conversation_id].add(_normal(content))
    result = await db.execute(
        select(DatasetCase).where(
            DatasetCase.anonymised_at.is_(None),
            or_(
                DatasetCase.history_author_ids.contains([user_id]),
                DatasetCase.source_conversation_id.in_(list(said)),
            ),
        )
    )
    scrubbed: list[UUID] = []
    for case in result.scalars().all():
        theirs = said.get(case.source_conversation_id) if case.source_conversation_id else None
        history: list[dict[str, Any]] = []
        authors: list[UUID | None] = []
        answering = False
        for turn, author in zip(case.history, case.history_author_ids, strict=True):
            if turn.get("role") == "user":
                answering = author == user_id or (
                    author is None
                    and theirs is not None
                    and _normal(str(turn.get("content", ""))) in theirs
                )
            if answering:
                history.append({**turn, "content": placeholder})
                authors.append(None)
            else:
                history.append(turn)
                authors.append(author)
        if history != case.history:
            case.history = history
            case.history_author_ids = authors
            scrubbed.append(case.id)
    await db.flush()
    return scrubbed


async def comments_of(db: AsyncSession, user_id: UUID) -> dict[UUID, list[str]]:
    """What this person wrote when rating answers, by the run that gave the answer.

    Their words reach other people's runs this way: a case keeps a rated-down
    answer's comment as its note, and the authoring assistant quotes the
    comments of the runs it reads as evidence.
    """
    result = await db.execute(
        select(Message.run_id, MessageRating.comment)
        .join(MessageRating, MessageRating.message_id == Message.id)
        .where(
            MessageRating.user_id == user_id,
            Message.run_id.is_not(None),
            MessageRating.comment.is_not(None),
            MessageRating.comment != "",
        )
    )
    comments: defaultdict[UUID, list[str]] = defaultdict(list)
    for run_id, comment in result.tuples():
        assert run_id is not None and comment is not None
        comments[run_id].append(comment)
    reviewed = await db.execute(
        select(CaseScore.run_id, CaseScore.human_note).where(
            CaseScore.reviewed_by_user_id == user_id,
            CaseScore.run_id.is_not(None),
            CaseScore.human_note.is_not(None),
            CaseScore.human_note != "",
        )
    )
    for run_id, note in reviewed.tuples():
        assert run_id is not None and note is not None
        comments[run_id].append(note)
    return dict(comments)


async def clear_case_notes_of(
    db: AsyncSession, user_id: UUID, *, comments: dict[UUID, list[str]]
) -> int:
    """Clear the note of every case, or drafted case, that holds their comment.

    A case keeps a rated-down answer's comment as its note, and a draft from the
    case generator does too. The note goes whole when it holds the comment's
    words anywhere - a curator may have written around it - and the rest of the case
    stays: a question somebody else asked, and the answer they got, are not the
    commenter's to erase. Found by `noted_by_user_id`, which a case keeps after
    the rating is gone, and otherwise by the comments they still have:
    `comments` carries each as written and as credential redaction stored it.

    Returns:
        How many cases and drafts lost their note.
    """
    noted = await db.execute(
        update(DatasetCase)
        .where(DatasetCase.noted_by_user_id == user_id)
        .values(note=None, noted_by_user_id=None)
    )
    cleared = noted.rowcount or 0  # ty: ignore[unresolved-attribute]
    if not comments:
        await db.flush()
        return cleared
    for model in (DatasetCase, CaseProposal):
        result = await db.execute(
            select(model).where(model.source_run_id.in_(list(comments)), model.note.is_not(None))
        )
        for row in result.scalars().all():
            assert row.source_run_id is not None and row.note is not None
            note = _words(row.note)
            if any(_within(_words(comment), note) for comment in comments[row.source_run_id]):
                row.note = None
                cleared += 1
    await db.flush()
    return cleared


def _normal(text: str) -> str:
    return " ".join(text.split())


_EDGE_WORDS = 3
"""How many of a comment's words a quote must carry across its edge to repeat it."""


def _words(text: str) -> list[str]:
    """The words of a text, without the punctuation and case a curator may have changed."""
    return re.findall(r"\w+", text.casefold())


def _within(inner: list[str], outer: list[str]) -> bool:
    return bool(inner) and any(
        outer[start : start + len(inner)] == inner for start in range(len(outer))
    )


def _repeats(quote: str, comment: str) -> bool:
    """Whether a quote repeats a comment, in whole words.

    An assistant quote is whitespace-normalized and taken word for word from a
    run's text, in which a comment is followed by the next comment or the
    question, so a quote can sit inside the comment, hold it, or run across its
    edge. Across an edge, a few words shared by chance are not the comment:
    the quote must carry at least `_EDGE_WORDS` of them, or all of a shorter one.
    """
    quoted, said = _normal(quote).split(), _normal(comment).split()
    if not quoted or not said:
        return False
    if _within(quoted, said) or _within(said, quoted):
        return True
    least = min(_EDGE_WORDS, len(said))
    return any(
        quoted[:size] == said[-size:] or quoted[-size:] == said[:size]
        for size in range(least, min(len(quoted), len(said)) + 1)
    )


def _cites(
    document: InstrumentedAttribute[list[dict[str, Any]]]
    | InstrumentedAttribute[dict[str, Any] | None],
    path: str,
    runs: ColumnElement[bool],
) -> ColumnElement[bool]:
    """Whether a JSONB document holds, at `path`, the id of a run matching `runs`."""
    cited = func.jsonb_path_query(document, cast(path, JSONPATH)).column_valued("run_id")
    named = select(func.to_jsonb(cast(AgentRun.id, Text))).where(runs)
    return exists(select(literal(1)).where(cited.in_(named)))


def _without_theirs(
    items: list[dict[str, Any]], theirs: set[str], comments: dict[str, list[str]]
) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if item.get("run_id") not in theirs
        and not any(
            _repeats(str(item.get("quote") or ""), comment)
            for comment in comments.get(str(item.get("run_id")), [])
        )
    ]


async def purge_evidence_of(
    db: AsyncSession, user_id: UUID, *, comments: dict[UUID, list[str]]
) -> int:
    """Remove the authoring assistant's quotes of this person, wherever it kept one.

    An evidence item is `{"run_id", "quote"}`, quoted word for word from a run
    the assistant read: its question, its answer, its calls and the comments of
    its ratings. An item about a run that answered them goes whole, since anything it
    quotes is from their conversation. From a run they only rated, only what
    repeats their comment goes - the rest is somebody else's question.

    Kept on change proposals' hunks, skill and context proposals, and the
    findings of a verify request's report. Unscoped by organization, as every
    erasure is.

    Returns:
        How many quotes were removed.
    """
    reached = or_(AgentRun.id.in_(_runs_they_asked(user_id)), AgentRun.id.in_(list(comments)))
    theirs = {str(run_id) for run_id in (await db.execute(_runs_they_asked(user_id))).scalars()}
    said = {str(run_id): text for run_id, text in comments.items()}
    removed = 0
    for model in (SpecProposalHunk, SkillProposal, ContextProposal):
        rows = await db.execute(select(model).where(_cites(model.evidence, "$[*].run_id", reached)))
        for row in rows.scalars().all():
            kept = _without_theirs(row.evidence, theirs, said)
            removed += len(row.evidence) - len(kept)
            row.evidence = kept
    requests = await db.execute(
        select(AuthoringRequest).where(
            _cites(AuthoringRequest.report, "$.findings[*].evidence[*].run_id", reached)
        )
    )
    for request in requests.scalars().all():
        assert request.report is not None
        findings = []
        for finding in request.report.get("findings", []):
            kept = _without_theirs(finding.get("evidence", []), theirs, said)
            removed += len(finding.get("evidence", [])) - len(kept)
            findings.append({**finding, "evidence": kept})
        request.report = {**request.report, "findings": findings}
    await db.flush()
    return removed


async def clear_gap_drafts_of(db: AsyncSession, user_id: UUID) -> int:
    """Discard the draft of every knowledge-gap topic that holds one of their searches.

    The drafter reads a topic's newest questions, what each found and the
    answer each got, and cites only some of them, so a draft can repeat their
    question without naming it: every draft of a topic they asked into goes,
    whoever else asked into it too. The topic stays, without a draft, and
    reads as one somebody can draft again. Runs before
    :func:`purge_knowledge_searches_of`, which takes the memberships with the
    searches.

    Returns:
        How many drafts were discarded.
    """
    from app.repositories import eval_run_repo

    topic_ids = list(
        await db.scalars(
            select(KnowledgeGapMember.topic_id)
            .join(KnowledgeSearch, KnowledgeSearch.id == KnowledgeGapMember.search_id)
            .where(_their_searches(user_id))
            .distinct()
        )
    )
    source_run = func.unnest(KnowledgeGapTopic.draft_evidence_run_ids).column_valued(
        "source_run_id"
    )
    tracked_topics = await db.scalars(
        select(KnowledgeGapTopic.id).where(
            exists(select(literal(1)).where(source_run.in_(_runs_they_asked(user_id))))
        )
    )
    topic_ids = list(set(topic_ids) | set(tracked_topics))
    # A conversation may already be deleted, taking topic memberships with it.
    # The check's frozen source run identities still identify derived content.
    cited_topics = await db.scalars(
        select(EvalRun.proposal_check["knowledge"]["topic_id"].astext).where(
            EvalRun.proposal_check["knowledge"]["topic_id"].astext.is_not(None),
            _cites(
                EvalRun.proposal_check,
                "$.evidence_run_ids[*]",
                AgentRun.id.in_(_runs_they_asked(user_id)),
            ),
        )
    )
    topic_ids = list(set(topic_ids) | {UUID(key) for key in cited_topics if key is not None})
    checked = await eval_run_repo.invalidate_knowledge_topics(db, topic_ids)
    if checked:
        attempts = list(
            await db.scalars(select(EvalRunCase).where(EvalRunCase.eval_run_id.in_(checked)))
        )
        runs = {attempt.agent_run_id for attempt in attempts if attempt.agent_run_id is not None}
        for attempt in attempts:
            attempt.answer, attempt.calls, attempt.error = None, [], None
        scores = await db.scalars(select(CaseScore).where(CaseScore.eval_run_id.in_(checked)))
        for score in scores:
            runs |= judge_runs_of(score)
            forget_answer(score)
        await forget_knowledge_runs(db, runs)
    result = await db.execute(
        update(KnowledgeGapTopic)
        .where(
            KnowledgeGapTopic.id.in_(topic_ids),
            KnowledgeGapTopic.draft_author == DraftAuthor.MODEL.value,
            or_(
                KnowledgeGapTopic.draft_content.is_not(None),
                KnowledgeGapTopic.draft_title.is_not(None),
            ),
        )
        .values(
            draft_author=None,
            draft_already_covered=False,
            draft_title=None,
            draft_content=None,
            draft_evidence_run_ids=None,
            draft_evidence_input_hashes=None,
            draft_sources=[],
            draft_unverified=0,
            draft_run_id=None,
            drafted_by_user_id=None,
            drafted_at=None,
        )
    )
    await db.flush()
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]


async def forget_knowledge_runs(db: AsyncSession, run_ids: Iterable[UUID]) -> None:
    """Injected drafts may occur in system instructions too; retain only the paid run row."""
    wanted = list(set(run_ids))
    await forget_runs(db, wanted)
    await db.execute(
        update(RunManifest).where(RunManifest.run_id.in_(wanted)).values(payload={}, truncated=True)
    )
    await db.flush()


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


async def present_among(db: AsyncSession, people: Iterable[UUID]) -> set[UUID]:
    """Which of these people may still be quoted, held against an erasure until this transaction ends.

    For a writer that read somebody's words before a slow step and writes them
    down after it. An erasure takes `PERSONAL_DATA_PER_USER` before it purges,
    so a person whose lock is free here, and whose account is still there, is
    not being erased; held, the lock lasts to this transaction's commit and the
    erasure that follows finds what was written. Taken without waiting, as
    :meth:`AgentRunnerService._may_record_about` does: a writer may hold rows
    the erasure is about to update. The lock is also taken by a note being
    written about the person, so a busy one is checked against the account's
    row, which only a deletion holds.
    """
    present: set[UUID] = set()
    for person in sorted(set(people)):
        held = await try_hold_subject(db, LockScope.PERSONAL_DATA_PER_USER, person)
        if (held or await _not_being_deleted(db, person)) and await db.scalar(
            select(User.id).where(User.id == person)
        ) is not None:
            present.add(person)
    return present


async def _not_being_deleted(db: AsyncSession, person: UUID) -> bool:
    """Whether a busy lock is somebody writing about the person rather than erasing them.

    Deleting an account locks its row before it purges, and a note being
    written about them does not, so a share of the row taken without waiting
    means no deletion is under way - and, held to this transaction's commit,
    makes one that starts later wait for this write and then remove it.
    """
    try:
        async with db.begin_nested():
            await db.execute(
                select(User.id)
                .where(User.id == person)
                .with_for_update(key_share=True, nowait=True)
            )
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) != _LOCK_NOT_AVAILABLE:
            raise
        return False
    return True


async def askers_of(db: AsyncSession, run_ids: Iterable[UUID]) -> set[UUID]:
    """Who these runs answered, for :func:`present_among`: the account that started each,
    or the one its chat identity is linked to."""
    result = await db.execute(
        select(
            sa_case(
                (AgentRun.initiated_by_publisher_fallback.is_(False), AgentRun.user_id),
                else_=None,
            ),
            ChannelIdentity.user_id,
        )
        .outerjoin(ChannelIdentity, ChannelIdentity.id == AgentRun.channel_identity_id)
        .where(AgentRun.id.in_(list(run_ids)))
    )
    return {person for row in result.tuples() for person in row if person is not None}


async def linked_people(db: AsyncSession, identity_ids: Iterable[UUID]) -> dict[UUID, UUID]:
    """The account each of these chat identities is linked to, for those that are."""
    wanted = list(set(identity_ids))
    if not wanted:
        return {}
    result = await db.execute(
        select(ChannelIdentity.id, ChannelIdentity.user_id).where(
            ChannelIdentity.id.in_(wanted), ChannelIdentity.user_id.is_not(None)
        )
    )
    return {identity: user for identity, user in result.tuples() if user is not None}


async def asker_of(db: AsyncSession, run_id: UUID, *, organization_id: UUID) -> UUID | None:
    """Who one run answered: the account that started it, else the one its chat identity is linked to."""
    result = await db.execute(
        select(
            sa_case(
                (AgentRun.initiated_by_publisher_fallback.is_(False), AgentRun.user_id),
                else_=None,
            ),
            ChannelIdentity.user_id,
        )
        .outerjoin(ChannelIdentity, ChannelIdentity.id == AgentRun.channel_identity_id)
        .where(AgentRun.id == run_id, AgentRun.organization_id == organization_id)
    )
    row = result.tuples().first()
    return None if row is None else row[0] or row[1]
