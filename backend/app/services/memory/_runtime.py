"""The claims ledger as a run uses it: one short session per operation (#2090).

Same reason as `_native`: a run must not read or write memory on the session it
runs on. Each function opens its own session, does one thing and commits, so a
claim written in a run that later fails still persists - which is what a memory is
for.

Authorization is decided here and not in the tool: the tool says what the model
asked for, this module says whether the run's person may have it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import ConflictError
from app.core.memory_keys import (
    ORGANIZATION_PREFIX,
    PROJECT_PREFIX,
    organization_owner_key,
    project_owner_key,
)
from app.core.permissions import Perm, Scope
from app.db.models.conversation import Conversation
from app.db.models.memory_claim import MemoryClaim
from app.db.models.project import Project
from app.db.session import get_db_context
from app.repositories import memory_claim as claim_repo
from app.repositories.memory_claim import ClaimScope
from app.schemas.decision_episode import DecisionEpisode
from app.services.access import PROJECT, acting_member, resolve_access
from app.services.memory import _claims
from app.services.memory._native import person_still_exists


@dataclass(frozen=True)
class ClaimView:
    """A claim as the model sees it: enough to quote, correct or share it."""

    id: UUID
    statement: str
    subject: str | None
    kind: str
    origin: str
    status: str
    scope: str
    effective_from: datetime | None
    observed_at: datetime
    episode: DecisionEpisode | None = None


def _view(claim: MemoryClaim) -> ClaimView:
    scope = claim.scope_key.split(":", 1)[0]
    if scope == "person":
        scope = "profile" if claim.agent_id is None else "this agent"
    return ClaimView(
        id=claim.id,
        statement=claim.statement,
        subject=claim.subject,
        kind=claim.kind,
        origin=claim.origin,
        status=claim.status,
        scope=scope,
        effective_from=claim.effective_from,
        observed_at=claim.observed_at,
        episode=DecisionEpisode.model_validate(claim.episode)
        if claim.episode is not None
        else None,
    )


async def project_of(conversation_id: UUID | None) -> UUID | None:
    """The project a conversation belongs to, or `None`."""
    if conversation_id is None:
        return None
    async with get_db_context() as db:
        return await db.scalar(
            select(Conversation.project_id).where(Conversation.id == conversation_id)
        )


async def remember(
    *,
    organization_id: UUID,
    scope: ClaimScope,
    statement: str,
    subject: str | None,
    kind: str,
    author_user_id: UUID | None,
    conversation_id: UUID | None,
    run_id: UUID | None,
    effective_from: datetime | None,
    episode: DecisionEpisode | None = None,
) -> tuple[ClaimView, bool, bool] | None:
    """Record a claim. `None` when its person is gone; else (claim, created, disputed)."""
    async with get_db_context() as db:
        if not await person_still_exists(db, scope.scope_key):
            return None
        result = await _claims.remember(
            db,
            organization_id=organization_id,
            scope=scope,
            statement=statement,
            subject=subject,
            kind=kind,
            origin="agent",
            author_user_id=author_user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            effective_from=effective_from,
            episode=episode,
        )
        return _view(result.claim), result.created, result.disputed


async def recall(
    *, organization_id: UUID, scopes: Sequence[ClaimScope], query: str
) -> list[ClaimView]:
    async with get_db_context() as db:
        rows = await _claims.recall(db, organization_id=organization_id, scopes=scopes, query=query)
        return [_view(row) for row in rows]


async def profile_block(*, organization_id: UUID, scopes: Sequence[ClaimScope]) -> str:
    """The bounded standing profile for a private run, or an empty string."""
    async with get_db_context() as db:
        rows = await _claims.profile(db, organization_id=organization_id, scopes=scopes)
        return _claims.profile_text(rows)


class ShareRefused(Exception):
    """The run's person may not write to that wider scope."""


async def _may_write_wide(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_person: UUID | None,
    scope_key: str,
) -> None:
    """Refuse unless the run's person may change what the whole project or organization reads.

    A claim in the person's own scope is theirs to write; one in a project or in the
    organization is read by everybody there, so changing it needs the same authority as
    sharing into it: `projects:edit` on the project, `context:edit` for the organization.
    Reading it is no such authority - a viewer can recall an organization claim and may not
    rewrite it.

    Raises:
        ShareRefused: Nobody is behind the run, or the person lacks the permission.
    """
    if not scope_key.startswith((PROJECT_PREFIX, ORGANIZATION_PREFIX)):
        return
    member = await acting_member(db, organization_id, str(run_person) if run_person else None)
    if member is None:
        raise ShareRefused("Nobody who may change this is behind the run.")
    if scope_key.startswith(ORGANIZATION_PREFIX):
        if member.scope_for(Perm.CONTEXT_EDIT) != Scope.ALL:
            raise ShareRefused("Changing what the whole organization reads needs context:edit.")
        return
    project = await db.get(Project, UUID(scope_key.removeprefix(PROJECT_PREFIX)))
    if project is None or project.organization_id != organization_id:
        raise ShareRefused("This conversation is not in a project.")
    if not await resolve_access(db, member, project, Perm.PROJECTS_EDIT, resource_type=PROJECT):
        raise ShareRefused("You may not edit this project.")


async def correct(
    *,
    organization_id: UUID,
    claim_id: UUID,
    scopes: Sequence[ClaimScope],
    statement: str,
    author_user_id: UUID,
    effective_from: datetime | None,
    run_id: UUID | None,
    conversation_id: UUID | None,
    agent_id: UUID | None,
) -> ClaimView | None:
    """An agent's record of a person's correction, in a scope they may read; `None` if none.

    Stored as an `agent` claim naming the run and conversation it came from, and
    audited, because the run may have acted on text it read rather than on the
    person's word.

    Raises:
        ShareRefused: The claim is one the whole project or organization reads and the
            person may not change it.
    """
    async with get_db_context() as db:
        claim = await claim_repo.get(db, organization_id=organization_id, claim_id=claim_id)
        allowed = {(scope.scope_key, scope.agent_id) for scope in scopes}
        if (
            claim is None
            or (claim.scope_key, claim.agent_id) not in allowed
            or not _claims.mutable(claim)
        ):
            # An id from an earlier `recall` can name a claim since corrected, merged or
            # retracted; correcting it would supersede the current one beside it.
            return None
        await _may_write_wide(
            db,
            organization_id=organization_id,
            run_person=author_user_id,
            scope_key=claim.scope_key,
        )
        try:
            fixed = await _claims.correct(
                db,
                claim=claim,
                statement=statement,
                author_user_id=author_user_id,
                effective_from=effective_from,
                origin="agent",
                run_id=run_id,
                conversation_id=conversation_id,
            )
        except ConflictError as exc:
            raise ShareRefused(exc.message) from exc
        await record_audit(
            db,
            actor_user_id=author_user_id,
            organization_id=organization_id,
            action="memory.claim.corrected",
            target_type="memory_claim",
            target_id=str(claim_id),
            # Never the statements: an entry holding what it corrected keeps it.
            details={
                "replacement": str(fixed.id),
                "scope": claim.scope_key.split(":", 1)[0],
                "run_id": None if run_id is None else str(run_id),
                "agent_id": None if agent_id is None else str(agent_id),
            },
        )
        return _view(fixed)


async def share(
    *,
    organization_id: UUID,
    claim_id: UUID,
    scopes: Sequence[ClaimScope],
    to: str,
    run_person: UUID | None,
    conversation_id: UUID | None,
) -> ClaimView | None:
    """Copy a claim into the project or the organization, on an authorized person's say-so.

    Raises:
        ShareRefused: there is no person behind the run, they lack the permission
            for that audience, or the conversation is not in a project.
    """
    async with get_db_context() as db:
        claim = await claim_repo.get(db, organization_id=organization_id, claim_id=claim_id)
        allowed = {(scope.scope_key, scope.agent_id) for scope in scopes}
        if (
            claim is None
            or (claim.scope_key, claim.agent_id) not in allowed
            or not _claims.mutable(claim)
        ):
            return None
        if run_person is None:
            raise ShareRefused("Nobody who may share this is behind the run.")
        if to == "organization":
            target = ClaimScope(organization_owner_key(organization_id), None)
        else:
            project_id = await db.scalar(
                select(Conversation.project_id).where(Conversation.id == conversation_id)
            )
            if project_id is None:
                raise ShareRefused("This conversation is not in a project.")
            target = ClaimScope(project_owner_key(project_id), None)
        if (claim.scope_key, claim.agent_id) == (target.scope_key, target.agent_id):
            raise ShareRefused("The claim is already in that scope.")
        await _may_write_wide(
            db, organization_id=organization_id, run_person=run_person, scope_key=target.scope_key
        )
        try:
            shared = await _claims.share(
                db,
                claim=claim,
                to=target,
                author_user_id=run_person,
                conversation_id=conversation_id,
            )
        except ConflictError as exc:
            raise ShareRefused(exc.message) from exc
        return _view(shared)


async def claim_for_approval(
    *, organization_id: UUID, claim_id: UUID, scopes: Sequence[ClaimScope]
) -> ClaimView | None:
    """The live claim a parked call names, if it is in a scope the run reads; else `None`.

    Read for the person deciding the call, so it answers only what `correct` and
    `share` would act on: a claim since corrected, merged or retracted is `None`.
    """
    async with get_db_context() as db:
        claim = await claim_repo.get(db, organization_id=organization_id, claim_id=claim_id)
        allowed = {(scope.scope_key, scope.agent_id) for scope in scopes}
        if (
            claim is None
            or (claim.scope_key, claim.agent_id) not in allowed
            or not _claims.mutable(claim)
        ):
            return None
        return _view(claim)
