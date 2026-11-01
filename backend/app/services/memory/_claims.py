"""The claims ledger's rules: capture, correction, retraction and consolidation (#2090).

Everything here takes the session it is to run on, so the request-scoped service
and a run's own short-lived sessions (see `_native`) share one set of rules.

The rules that matter, in the order a reviewer will look for them:

- **A source claim is never rewritten.** A correction is a new `person` claim that
  supersedes the old one; the old keeps its text, its source and its validity.
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
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.memory_claim import MemoryClaim
from app.repositories import memory_claim as claim_repo
from app.repositories.memory_claim import ClaimScope

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
) -> Remembered:
    """Record one claim in `scope`, applying the precedence rules above.

    Writing the same statement again is a no-op that returns the existing claim, so
    a retried run or a repeated mention never multiplies a fact.
    """
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
        if _same(existing.statement, statement):
            return Remembered(existing, created=False, disputed=existing.status == "disputed")

    now = datetime.now(UTC)
    status = "current"
    supersedes: MemoryClaim | None = None
    disputed = False
    if topic is not None and live:
        people = [claim for claim in live if claim.origin == "person" and claim.status == "current"]
        if origin == "person":
            for old in live:
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
) -> MemoryClaim:
    """A person's correction of one claim: a new claim that supersedes it.

    The corrected claim keeps its text, source and validity; it is closed at the
    correction's effective date so "Anna handled invoices until Monday" stays true
    of the past. A claim with no subject gets one derived from its own id, so the
    correction has something to supersede.
    """
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
        origin="person",
        author_user_id=author_user_id,
        effective_from=effective_from,
    )
    return result.claim


async def retract(db: AsyncSession, *, claim: MemoryClaim) -> None:
    """Take a claim out of use without deleting it or anything it came from.

    Retracting a derived claim returns its sources to `current`: the conclusion is
    undone, the evidence is not. Its consolidation key stays, so the next pass does
    not draw the same conclusion again.
    """
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
    result = await remember(
        db,
        organization_id=claim.organization_id,
        scope=to,
        statement=claim.statement,
        subject=claim.subject,
        kind=claim.kind,
        origin="person",
        author_user_id=author_user_id,
        conversation_id=conversation_id,
    )
    if result.created:
        result.claim.derived_from = [str(claim.id)]
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
        db, organization_id=organization_id, scopes=scopes, statuses=("current",), limit=40
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
        if claim.subject is not None and claim.origin != "consolidation":
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
