"""The claims ledger's rules: capture, correction, retraction and consolidation (#2090).

Everything here takes the session it is to run on, so the request-scoped service
and a run's own short-lived sessions (see `_native`) share one set of rules.

The rules that matter, in the order a reviewer will look for them:

- **A source claim is never rewritten.** A correction is a new claim that supersedes
  the old one; the old keeps its text, its source and its validity. A correction made
  in the console is a `person` claim; one an agent's tool recorded is an `agent`
  claim naming its run, because the agent may have been told by text it read.
- **A person's word outranks an inference.** An agent's claim that contradicts a
  current person claim is stored `disputed` - kept, visible, and never put in front
  of the model as established.
- **Two agents' contradiction is a dispute, not a coin toss.** Both stay visible
  until a person settles it.
- **Consolidation only folds agreement.** Identical statements about one subject
  become one derived claim naming its sources; differing statements are marked
  disputed. It is idempotent: the derived claim's key is a hash of its sources, so
  a second pass finds it and does nothing, and a derived claim a person retracted
  is not recreated.
- **Ancestry is access-filtered.** `provenance` returns only sources in scopes the
  asker may read, and says how many it withheld.
"""

import hashlib
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError
from app.core.memory_keys import PERSON_PREFIX, is_person_key
from app.db.locks import LockScope, hold_subject
from app.db.models.memory_claim import MemoryClaim
from app.repositories import memory_claim as claim_repo
from app.repositories.memory_claim import ClaimScope
from app.schemas.decision_episode import DecisionEpisode

MAX_STATEMENT = 600
PROFILE_CLAIMS = 20
PROFILE_CHARS = 1800
"""The profile spliced into a private run: bounded, so one noisy person cannot fill the prompt."""

_SUBJECT = re.compile(r"[^a-z0-9]+")


def normalise_subject(subject: str | None) -> str | None:
    """A topic as a stable slug, so `Invoice owner` and `invoice_owner` are one subject."""
    if subject is None:
        return None
    slug = _SUBJECT.sub("_", subject.casefold()).strip("_")[:120]
    return slug or None


def _same(left: str, right: str) -> bool:
    return " ".join(left.casefold().split()) == " ".join(right.casefold().split())


@dataclass(frozen=True)
class Remembered:
    """What a write did: the claim it left, and whether it collided with another."""

    claim: MemoryClaim
    created: bool
    disputed: bool = False


@dataclass(frozen=True)
class Provenance:
    """A claim's ancestry as one asker may see it."""

    sources: list[MemoryClaim]
    withheld: int
    superseded: MemoryClaim | None


def mutable(claim: MemoryClaim) -> bool:
    """Whether a claim still participates in the present or a scheduled correction.

    An expired predecessor may retain `current` status after a dated correction;
    status alone must not let a stale id rewrite its successor or republish the past.
    """
    return claim.status in ("current", "disputed") and (
        claim.effective_to is None or claim.effective_to > datetime.now(UTC)
    )


async def _hold_person(db: AsyncSession, scope_key: str) -> None:
    if is_person_key(scope_key):
        try:
            person_id = UUID(scope_key.removeprefix(PERSON_PREFIX))
        except ValueError:
            person_id = None
        if person_id is not None:
            await hold_subject(db, LockScope.PERSONAL_DATA_PER_USER, person_id)


async def _hold_scope(db: AsyncSession, *, organization_id: UUID, scope_key: str) -> None:
    await _hold_person(db, scope_key)
    # Serialize all agent bindings too: consolidation traverses an owner's scopes together.
    await hold_subject(db, LockScope.MEMORY_CLAIMS_PER_SCOPE, uuid5(organization_id, scope_key))


async def _live_for_mutation(db: AsyncSession, claim: MemoryClaim) -> MemoryClaim:
    await _hold_scope(db, organization_id=claim.organization_id, scope_key=claim.scope_key)
    current = await claim_repo.get(db, organization_id=claim.organization_id, claim_id=claim.id)
    if current is None or not mutable(current):
        raise ConflictError(
            message="That claim is no longer current", details={"claim_id": claim.id}
        )
    return current


async def remember(
    db: AsyncSession,
    *,
    organization_id: UUID,
    scope: ClaimScope,
    statement: str,
    subject: str | None = None,
    kind: str = "fact",
    origin: str = "agent",
    author_user_id: UUID | None = None,
    conversation_id: UUID | None = None,
    run_id: UUID | None = None,
    effective_from: datetime | None = None,
    episode: DecisionEpisode | None = None,
    corrects: bool = False,
) -> Remembered:
    """Record one claim in `scope`, applying the precedence rules above.

    Writing the same statement again is a no-op that returns the existing claim, so
    a retried run or a repeated mention never multiplies a fact. A `person` claim and
    a correction (`corrects`) supersede what is live about the subject; any other
    claim that disagrees with it is a dispute.
    """
    if episode is not None and kind != "decision":
        raise BadRequestError(message="Structured episodes belong to decision claims")
    await _hold_scope(db, organization_id=organization_id, scope_key=scope.scope_key)
    episode_data = None if episode is None else episode.model_dump(mode="json")
    statement = statement.strip()[:MAX_STATEMENT]
    topic = normalise_subject(subject)
    live = (
        await claim_repo.about_subject(
            db, organization_id=organization_id, scope=scope, subject=topic
        )
        if topic is not None
        else await claim_repo.without_subject(db, organization_id=organization_id, scope=scope)
    )
    for existing in live:
        if _same(existing.statement, statement) and existing.episode == episode_data:
            return Remembered(existing, created=False, disputed=existing.status == "disputed")

    now = datetime.now(UTC)
    supersedes_live = corrects or origin == "person"
    if supersedes_live and any(
        (item.origin == "person" or item.supersedes_id is not None)
        and item.effective_from is not None
        and item.effective_from > now
        for item in live
    ):
        raise ConflictError(
            message="A future correction is already scheduled for this subject; retract it before replacing it",
            details={"subject": topic},
        )
    status = "current"
    supersedes: MemoryClaim | None = None
    disputed = False
    if topic is not None and live:
        people = [claim for claim in live if claim.origin == "person" and claim.status == "current"]
        if supersedes_live:
            for old in live:
                if effective_from is not None and effective_from > now:
                    # Dated for later: the old claim stays true until then, so it is closed
                    # at that date and keeps its status; the new one waits for its date.
                    old.effective_to = effective_from
                    db.add(old)
                else:
                    await claim_repo.set_status(
                        db, old, "superseded", effective_to=effective_from or now
                    )
            supersedes = live[-1]
        elif people:
            status, disputed = "disputed", True
        else:
            for old in live:
                await claim_repo.set_status(db, old, "disputed")
            status, disputed = "disputed", True

    claim = await claim_repo.create(
        db,
        organization_id=organization_id,
        scope_key=scope.scope_key,
        agent_id=scope.agent_id,
        subject=topic,
        statement=statement,
        kind=kind,
        origin=origin,
        status=status,
        author_user_id=author_user_id,
        source_conversation_id=conversation_id,
        source_run_id=run_id,
        observed_at=now,
        effective_from=effective_from,
        supersedes_id=supersedes.id if supersedes else None,
        episode=episode_data,
    )
    await claim_repo.bump_revision(db, organization_id=organization_id, scope_key=scope.scope_key)
    return Remembered(claim, created=True, disputed=disputed)


async def correct(
    db: AsyncSession,
    *,
    claim: MemoryClaim,
    statement: str,
    author_user_id: UUID,
    effective_from: datetime | None = None,
    episode: DecisionEpisode | None = None,
    origin: str = "person",
    run_id: UUID | None = None,
    conversation_id: UUID | None = None,
) -> MemoryClaim:
    """A correction of one claim: a new claim that supersedes it.

    The corrected claim keeps its text, source and validity; it is closed at the
    correction's effective date so "Anna handled invoices until Monday" stays true
    of the past. A claim with no subject gets one derived from its own id, so the
    correction has something to supersede.
    """
    claim = await _live_for_mutation(db, claim)
    subject = claim.subject or f"claim_{claim.id.hex[:12]}"
    if claim.subject is None:
        claim.subject = subject
        db.add(claim)
        await db.flush()
    result = await remember(
        db,
        organization_id=claim.organization_id,
        scope=ClaimScope(claim.scope_key, claim.agent_id),
        statement=statement,
        subject=subject,
        kind=claim.kind,
        origin=origin,
        corrects=True,
        author_user_id=author_user_id,
        conversation_id=conversation_id,
        run_id=run_id,
        effective_from=effective_from,
        episode=episode
        or (
            DecisionEpisode.model_validate(claim.episode).model_copy(
                update={"correction": statement}
            )
            if claim.episode is not None
            else None
        ),
    )
    return result.claim


async def retract(db: AsyncSession, *, claim: MemoryClaim) -> None:
    """Take a claim out of use without deleting it or anything it came from.

    Retracting a derived claim returns its sources to `current`: the conclusion is
    undone, the evidence is not. Its consolidation key stays, so the next pass does
    not draw the same conclusion again.
    """
    claim = await _live_for_mutation(db, claim)
    await claim_repo.set_status(db, claim, "retracted", effective_to=datetime.now(UTC))
    if claim.derived_from:
        sources = await claim_repo.many(
            db,
            organization_id=claim.organization_id,
            claim_ids=[UUID(str(item)) for item in claim.derived_from],
        )
        for source in sources:
            if source.status == "merged":
                await claim_repo.set_status(db, source, "current")
    await claim_repo.bump_revision(
        db, organization_id=claim.organization_id, scope_key=claim.scope_key
    )


async def share(
    db: AsyncSession,
    *,
    claim: MemoryClaim,
    to: ClaimScope,
    author_user_id: UUID,
    conversation_id: UUID | None = None,
) -> MemoryClaim:
    """Copy a claim into a wider scope, naming the claim it came from.

    A copy, not a move: the original keeps its narrow audience, and the wider claim
    records `derived_from` the original so the origin is explainable to the people
    who may see it - and only to them (`provenance` filters the ancestry).
    """
    if (claim.scope_key, claim.agent_id) == (to.scope_key, to.agent_id):
        raise ConflictError(
            message="The claim is already in that scope", details={"claim_id": claim.id}
        )
    # Acquire person locks before scope locks, then scopes in a stable order:
    # simultaneous cross-scope shares must not deadlock each other or erasure.
    ancestry = await claim_repo.ancestry_scope_keys(
        db, organization_id=claim.organization_id, claim_id=claim.id
    )
    keys = sorted({claim.scope_key, to.scope_key})
    for key in sorted(ancestry | set(keys)):
        await _hold_person(db, key)
    for key in keys:
        await _hold_scope(db, organization_id=claim.organization_id, scope_key=key)
    current = await claim_repo.get(db, organization_id=claim.organization_id, claim_id=claim.id)
    if current is None or not mutable(current):
        raise ConflictError(
            message="That claim is no longer current", details={"claim_id": claim.id}
        )
    refreshed_ancestry = await claim_repo.ancestry_scope_keys(
        db, organization_id=claim.organization_id, claim_id=claim.id
    )
    if {key for key in refreshed_ancestry - ancestry if is_person_key(key)}:
        raise ConflictError(message="The claim ancestry changed; retry sharing")
    claim = current
    result = await remember(
        db,
        organization_id=claim.organization_id,
        scope=to,
        statement=claim.statement,
        episode=DecisionEpisode.model_validate(claim.episode)
        if claim.episode is not None
        else None,
        subject=claim.subject,
        kind=claim.kind,
        origin="person",
        author_user_id=author_user_id,
        conversation_id=conversation_id,
    )
    # A second person sharing the same sentence is deduplicated into the first copy, which
    # then keeps both sources: erasing one person must not take the other's authorized
    # share with it (`delete_descendants` removes a copy only when no source is left).
    sources = [] if result.created else [str(item) for item in result.claim.derived_from]
    if str(claim.id) not in sources:
        result.claim.derived_from = [*sources, str(claim.id)]
        db.add(result.claim)
        await db.flush()
    return result.claim


async def provenance(
    db: AsyncSession,
    *,
    claim: MemoryClaim,
    readable: Sequence[ClaimScope] = (),
    readable_keys: Collection[str] = (),
) -> Provenance:
    """The claim's sources, minus any the asker may not read.

    `readable` names exact scopes; `readable_keys` names whole owners, for a person
    reading their own claims under every agent.
    """
    ids = [UUID(str(item)) for item in claim.derived_from]
    found = await claim_repo.many(db, organization_id=claim.organization_id, claim_ids=ids)
    allowed = {(scope.scope_key, scope.agent_id) for scope in readable}

    def may_read(candidate: MemoryClaim) -> bool:
        return (
            candidate.scope_key in readable_keys
            or (candidate.scope_key, candidate.agent_id) in allowed
        )

    visible = [source for source in found if may_read(source)]
    previous = None
    if claim.supersedes_id is not None:
        candidate = await claim_repo.get(
            db, organization_id=claim.organization_id, claim_id=claim.supersedes_id
        )
        if candidate is not None and may_read(candidate):
            previous = candidate
    return Provenance(sources=visible, withheld=len(ids) - len(visible), superseded=previous)


def profile_text(claims: Sequence[MemoryClaim]) -> str:
    """The profile block: bounded, newest first, with when each began to hold."""
    lines: list[str] = []
    used = 0
    for claim in claims[:PROFILE_CLAIMS]:
        since = f" (since {claim.effective_from:%Y-%m-%d})" if claim.effective_from else ""
        line = f"- {claim.statement}{since}"
        if used + len(line) > PROFILE_CHARS:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)


async def profile(
    db: AsyncSession, *, organization_id: UUID, scopes: Sequence[ClaimScope]
) -> list[MemoryClaim]:
    return await claim_repo.list_in_scopes(
        db,
        organization_id=organization_id,
        scopes=scopes,
        statuses=("current",),
        limit=40,
        in_effect=True,
    )


async def recall(
    db: AsyncSession,
    *,
    organization_id: UUID,
    scopes: Sequence[ClaimScope],
    query: str,
    limit: int = 8,
) -> list[MemoryClaim]:
    """The live claims that best match `query`, by how many of its words they contain.

    Plain substring matching on purpose: recall must not need a model call on every
    lookup, and the claims are short, curated sentences.
    """
    terms = [term for term in re.findall(r"\w+", query.casefold()) if len(term) >= 3][:8]
    rows = await claim_repo.search(
        db, organization_id=organization_id, scopes=scopes, terms=terms, limit=limit
    )

    def score(claim: MemoryClaim) -> tuple[int, int]:
        text = f"{claim.subject or ''} {claim.statement}".casefold()
        return (sum(term in text for term in terms), 1 if claim.status == "current" else 0)

    return sorted(rows, key=score, reverse=True)[:limit]


@dataclass(frozen=True)
class Consolidation:
    """What one pass over one scope changed."""

    ran: bool
    merged: int = 0
    disputed: int = 0


def _key(scope_key: str, agent_id: UUID | None, subject: str, ids: Sequence[UUID]) -> str:
    material = "|".join([scope_key, str(agent_id), subject, *sorted(str(i) for i in ids)])
    return hashlib.sha256(material.encode()).hexdigest()


async def consolidate(db: AsyncSession, *, organization_id: UUID, scope_key: str) -> Consolidation:
    """Fold agreement and flag disagreement in one scope, if it changed since last time.

    Deterministic, with no model: the cost of an unchanged scope is one row lock.
    Returns `ran=False` when nothing changed.
    """
    await _hold_scope(db, organization_id=organization_id, scope_key=scope_key)
    state = await claim_repo.locked_state(db, organization_id=organization_id, scope_key=scope_key)
    if state is None or state.revision <= state.consolidated_revision:
        return Consolidation(ran=False)
    revision = state.revision
    merged = disputed = 0
    agents = await claim_repo.agents_in_scope(
        db, organization_id=organization_id, scope_key=scope_key
    )
    candidates: list[MemoryClaim] = []
    for agent_id in agents:
        candidates += await claim_repo.list_in_scopes(
            db,
            organization_id=organization_id,
            scopes=[ClaimScope(scope_key, agent_id)],
            statuses=("current", "disputed"),
            limit=500,
        )
    groups: dict[tuple[UUID | None, str], list[MemoryClaim]] = {}
    for claim in candidates:
        if claim.subject is not None and claim.origin != "consolidation" and claim.episode is None:
            groups.setdefault((claim.agent_id, claim.subject), []).append(claim)
    for (agent_id, subject), claims in groups.items():
        people = [claim for claim in claims if claim.origin == "person"]
        inferred = [claim for claim in claims if claim.origin == "agent"]
        if people:
            for claim in inferred:
                if claim.status != "disputed" and not _same(claim.statement, people[-1].statement):
                    await claim_repo.set_status(db, claim, "disputed")
                    disputed += 1
            continue
        distinct = {" ".join(claim.statement.casefold().split()) for claim in inferred}
        if len(distinct) > 1:
            for claim in inferred:
                if claim.status != "disputed":
                    await claim_repo.set_status(db, claim, "disputed")
                    disputed += 1
        elif len(inferred) >= 2:
            key = _key(scope_key, agent_id, subject, [claim.id for claim in inferred])
            known = await claim_repo.derived_by_key(
                db, organization_id=organization_id, scope_key=scope_key, consolidation_key=key
            )
            if known is None:
                await claim_repo.create(
                    db,
                    organization_id=organization_id,
                    scope_key=scope_key,
                    agent_id=agent_id,
                    subject=subject,
                    statement=inferred[-1].statement,
                    kind=inferred[-1].kind,
                    origin="consolidation",
                    status="current",
                    observed_at=datetime.now(UTC),
                    derived_from=[str(claim.id) for claim in inferred],
                    consolidation_key=key,
                )
                for claim in inferred:
                    await claim_repo.set_status(db, claim, "merged")
                merged += len(inferred)
    await claim_repo.mark_consolidated(db, state, revision)
    return Consolidation(ran=True, merged=merged, disputed=disputed)
