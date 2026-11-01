"""The claims ledger against Postgres (#2090).

What a mocked session cannot answer: that a correction keeps what it corrects, that
a person's word outranks an inference through a second consolidation, that
consolidation is idempotent through a unique index, and that ancestry is filtered
by what the asker may read.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory_keys import organization_owner_key, person_owner_key
from app.db.models.agent import Agent
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import memory_claim as claim_repo
from app.repositories.memory_claim import ClaimScope
from app.services.memory import claims

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _tenant(db: AsyncSession) -> tuple[Organization, User, Agent, Agent]:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Ada")
    db.add(user)
    await db.flush()
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id
    )
    db.add(organization)
    await db.flush()
    agents = []
    for name in ("Finance", "Support"):
        agent = Agent(
            organization_id=organization.id,
            name=name,
            created_by_user_id=user.id,
            slug=f"a-{uuid.uuid4().hex[:8]}",
        )
        db.add(agent)
        agents.append(agent)
    await db.flush()
    return organization, user, agents[0], agents[1]


async def _say(db, org, scope, statement, *, subject="invoice_owner", origin="agent", user=None):
    return await claims.remember(
        db,
        organization_id=org.id,
        scope=scope,
        statement=statement,
        subject=subject,
        origin=origin,
        author_user_id=user.id if user else None,
    )


async def test_the_same_claim_twice_is_one_claim(db: AsyncSession) -> None:
    org, user, finance, _ = await _tenant(db)
    scope = ClaimScope(person_owner_key(user.id), None)

    first = await _say(db, org, scope, "Anna handles invoices")
    again = await _say(db, org, scope, "  anna   handles invoices ")

    assert first.created and not again.created
    assert again.claim.id == first.claim.id


async def test_a_correction_keeps_what_it_corrects_and_closes_it(db: AsyncSession) -> None:
    org, user, finance, _ = await _tenant(db)
    scope = ClaimScope(person_owner_key(user.id), finance.id)
    old = (await _say(db, org, scope, "Anna handles invoices")).claim

    monday = datetime.now(UTC) - timedelta(days=1)
    new = await claims.correct(
        db,
        claim=old,
        statement="Piotr takes over invoices",
        author_user_id=user.id,
        effective_from=monday,
    )

    await db.refresh(old)
    assert old.status == "superseded" and old.statement == "Anna handles invoices"
    assert old.effective_to == monday
    assert new.status == "current" and new.origin == "person" and new.supersedes_id == old.id
    assert new.effective_from == monday


async def test_an_inference_that_contradicts_a_person_is_kept_aside(db: AsyncSession) -> None:
    org, user, finance, _ = await _tenant(db)
    scope = ClaimScope(person_owner_key(user.id), finance.id)
    await _say(db, org, scope, "Piotr handles invoices", origin="person", user=user)

    inferred = await _say(db, org, scope, "Anna handles invoices")

    assert inferred.disputed and inferred.claim.status == "disputed"
    live = await claim_repo.list_in_scopes(db, organization_id=org.id, scopes=[scope])
    assert [claim.statement for claim in live] == ["Piotr handles invoices"]


async def test_two_agents_disagreeing_is_a_dispute_not_a_winner(db: AsyncSession) -> None:
    org, user, finance, _ = await _tenant(db)
    scope = ClaimScope(person_owner_key(user.id), finance.id)

    await _say(db, org, scope, "Prefers email")
    await _say(db, org, scope, "Prefers phone")

    live = await claim_repo.list_in_scopes(db, organization_id=org.id, scopes=[scope])
    assert live == []
    disputed = await claim_repo.list_in_scopes(
        db, organization_id=org.id, scopes=[scope], statuses=("disputed",)
    )
    assert {claim.statement for claim in disputed} == {"Prefers email", "Prefers phone"}


async def test_consolidation_folds_agreement_once_and_is_idempotent(db: AsyncSession) -> None:
    """Two agreeing sources, a conflicting one, a person's correction, a second pass."""
    org, user, finance, support = await _tenant(db)
    key = person_owner_key(user.id)
    scope = ClaimScope(key, None)
    a = (await _say(db, org, scope, "Prefers X", subject="channel")).claim
    # A second source: same statement but a different subject spelling is the same topic.
    b = await claim_repo.create(
        db,
        organization_id=org.id,
        scope_key=key,
        agent_id=None,
        subject="channel",
        statement="prefers x",
        kind="fact",
        origin="agent",
        status="current",
        observed_at=datetime.now(UTC),
    )
    await claim_repo.bump_revision(db, organization_id=org.id, scope_key=key)

    first = await claims.consolidate(db, organization_id=org.id, scope_key=key)
    second = await claims.consolidate(db, organization_id=org.id, scope_key=key)

    assert first.ran and first.merged == 2
    assert not second.ran
    live = await claim_repo.list_in_scopes(db, organization_id=org.id, scopes=[scope])
    derived = [claim for claim in live if claim.origin == "consolidation"]
    assert len(derived) == 1 and set(derived[0].derived_from) == {str(a.id), str(b.id)}
    await db.refresh(a)
    assert a.status == "merged" and a.statement == "Prefers X"

    # A conflicting source arrives, then the person corrects: the correction survives
    # a further pass and no source is lost.
    await _say(db, org, scope, "Prefers Y", subject="channel")
    fixed = await claims.correct(
        db, claim=derived[0], statement="Prefers Z", author_user_id=user.id
    )
    await claims.consolidate(db, organization_id=org.id, scope_key=key)
    await claims.consolidate(db, organization_id=org.id, scope_key=key)
    live = await claim_repo.list_in_scopes(db, organization_id=org.id, scopes=[scope])
    assert [claim.statement for claim in live] == ["Prefers Z"]
    assert live[0].id == fixed.id
    everything = await claim_repo.list_in_scopes(
        db,
        organization_id=org.id,
        scopes=[scope],
        statuses=("current", "disputed", "superseded", "merged", "retracted"),
    )
    assert {claim.statement for claim in everything} >= {"Prefers X", "prefers x", "Prefers Y"}


async def test_retracting_a_conclusion_returns_its_sources_and_is_not_redrawn(
    db: AsyncSession,
) -> None:
    org, user, *_ = await _tenant(db)
    key = person_owner_key(user.id)
    scope = ClaimScope(key, None)
    await _say(db, org, scope, "Works Tuesdays", subject="schedule")
    other = await claim_repo.create(
        db,
        organization_id=org.id,
        scope_key=key,
        agent_id=None,
        subject="schedule",
        statement="works tuesdays",
        kind="fact",
        origin="agent",
        status="current",
        observed_at=datetime.now(UTC),
    )
    await claim_repo.bump_revision(db, organization_id=org.id, scope_key=key)
    await claims.consolidate(db, organization_id=org.id, scope_key=key)
    derived = next(
        c
        for c in await claim_repo.list_in_scopes(db, organization_id=org.id, scopes=[scope])
        if c.origin == "consolidation"
    )

    await claims.retract(db, claim=derived)
    again = await claims.consolidate(db, organization_id=org.id, scope_key=key)

    await db.refresh(other)
    assert other.status == "current"
    assert again.ran and again.merged == 0
    live = await claim_repo.list_in_scopes(db, organization_id=org.id, scopes=[scope])
    assert all(claim.origin != "consolidation" for claim in live) and len(live) == 2


async def test_ancestry_is_filtered_by_what_the_asker_may_read(db: AsyncSession) -> None:
    org, user, finance, _ = await _tenant(db)
    private = ClaimScope(person_owner_key(user.id), finance.id)
    source = (await _say(db, org, private, "Is renegotiating the Acme contract")).claim
    shared = await claims.share(
        db,
        claim=source,
        to=ClaimScope(organization_owner_key(org.id), None),
        author_user_id=user.id,
    )

    colleague = await claims.provenance(
        db, claim=shared, readable=[ClaimScope(organization_owner_key(org.id), None)]
    )
    owner = await claims.provenance(db, claim=shared, readable=[private])

    assert colleague.sources == [] and colleague.withheld == 1
    assert [claim.id for claim in owner.sources] == [source.id] and owner.withheld == 0


async def test_recall_finds_by_words_inside_the_given_scopes_only(db: AsyncSession) -> None:
    org, user, finance, support = await _tenant(db)
    mine = ClaimScope(person_owner_key(user.id), finance.id)
    other_agent = ClaimScope(person_owner_key(user.id), support.id)
    await _say(db, org, mine, "The Acme renewal is due in March", subject="acme")
    await _say(db, org, other_agent, "Acme prefers invoices by post", subject="acme_post")

    found = await claims.recall(db, organization_id=org.id, scopes=[mine], query="when is acme due")

    assert [claim.statement for claim in found] == ["The Acme renewal is due in March"]


async def test_erasing_a_scope_nobody_wrote_removes_nothing(db: AsyncSession) -> None:
    org, user, *_ = await _tenant(db)

    removed = await claim_repo.delete_for_scope(
        db, organization_id=org.id, scope_key=person_owner_key(user.id)
    )

    assert removed == 0


async def test_erasing_a_scope_removes_its_claims_and_counters(db: AsyncSession) -> None:
    org, user, finance, _ = await _tenant(db)
    key = person_owner_key(user.id)
    await _say(db, org, ClaimScope(key, None), "Likes short answers", subject="style")

    removed = await claim_repo.delete_for_scope(db, organization_id=org.id, scope_key=key)

    assert removed == 1
    assert await claim_repo.locked_state(db, organization_id=org.id, scope_key=key) is None


async def test_erasing_a_person_removes_what_was_shared_out_of_their_claims(
    db: AsyncSession,
) -> None:
    org, user, finance, _ = await _tenant(db)
    key = person_owner_key(user.id)
    source = (await _say(db, org, ClaimScope(key, finance.id), "Is changing jobs")).claim
    await claims.share(
        db,
        claim=source,
        to=ClaimScope(organization_owner_key(org.id), None),
        author_user_id=user.id,
    )
    unrelated = await _say(
        db,
        org,
        ClaimScope(organization_owner_key(org.id), None),
        "Office closes at six",
        subject="office_hours",
    )

    removed = await claim_repo.delete_for_scope(db, organization_id=org.id, scope_key=key)

    assert removed == 2
    left = await claim_repo.list_in_scopes(
        db, organization_id=org.id, scopes=[ClaimScope(organization_owner_key(org.id), None)]
    )
    assert [claim.id for claim in left] == [unrelated.claim.id]


async def _raw(
    db, org, scope_key, statement, *, subject, origin="agent", agent_id=None, status="current"
):
    return await claim_repo.create(
        db,
        organization_id=org.id,
        scope_key=scope_key,
        agent_id=agent_id,
        subject=subject,
        statement=statement,
        kind="fact",
        origin=origin,
        status=status,
        observed_at=datetime.now(UTC),
    )


def test_a_subject_is_a_slug_or_nothing() -> None:
    assert claims.normalise_subject(None) is None
    assert claims.normalise_subject("  !!! ") is None
    assert claims.normalise_subject("Invoice Owner") == "invoice_owner"


async def test_correcting_a_claim_with_no_subject_gives_it_one_and_closes_it(
    db: AsyncSession,
) -> None:
    org, user, finance, _ = await _tenant(db)
    scope = ClaimScope(person_owner_key(user.id), None)
    loose = (await _say(db, org, scope, "Likes tea", subject=None)).claim

    fixed = await claims.correct(db, claim=loose, statement="Likes coffee", author_user_id=user.id)

    await db.refresh(loose)
    assert loose.status == "superseded" and loose.subject == fixed.subject
    assert fixed.status == "current" and fixed.statement == "Likes coffee"


async def test_retracting_a_plain_claim_touches_nothing_else(db: AsyncSession) -> None:
    org, user, *_ = await _tenant(db)
    scope = ClaimScope(person_owner_key(user.id), None)
    claim = (await _say(db, org, scope, "Likes tea", subject="drink")).claim

    await claims.retract(db, claim=claim)

    assert claim.status == "retracted" and claim.effective_to is not None


async def test_retracting_a_conclusion_leaves_sources_that_were_already_settled(
    db: AsyncSession,
) -> None:
    org, user, *_ = await _tenant(db)
    key = person_owner_key(user.id)
    settled = await _raw(db, org, key, "x", subject="t", status="superseded")
    derived = await claim_repo.create(
        db,
        organization_id=org.id,
        scope_key=key,
        agent_id=None,
        subject="t",
        statement="x",
        kind="fact",
        origin="consolidation",
        status="current",
        observed_at=datetime.now(UTC),
        derived_from=[str(settled.id)],
        consolidation_key="k" * 64,
    )

    await claims.retract(db, claim=derived)

    await db.refresh(settled)
    assert settled.status == "superseded"


async def test_the_corrected_claim_is_shown_to_whoever_may_read_it(db: AsyncSession) -> None:
    org, user, finance, _ = await _tenant(db)
    scope = ClaimScope(person_owner_key(user.id), finance.id)
    old = (await _say(db, org, scope, "Anna handles invoices")).claim
    new = await claims.correct(
        db, claim=old, statement="Piotr handles invoices", author_user_id=user.id
    )

    seen = await claims.provenance(db, claim=new, readable=[scope])
    hidden = await claims.provenance(
        db, claim=new, readable=[ClaimScope(organization_owner_key(org.id), None)]
    )

    assert seen.superseded is not None and seen.superseded.id == old.id
    assert hidden.superseded is None


async def test_a_profile_stops_at_its_character_budget(db: AsyncSession) -> None:
    org, user, *_ = await _tenant(db)
    key = person_owner_key(user.id)
    rows = [await _raw(db, org, key, f"{'word ' * 120}{n}", subject=f"s{n}") for n in range(6)]

    text = claims.profile_text(rows)

    assert len(text) <= claims.PROFILE_CHARS and 0 < text.count("\n") + 1 < len(rows)


async def test_consolidation_disputes_what_disagrees_with_a_person_and_with_each_other(
    db: AsyncSession,
) -> None:
    org, user, finance, support = await _tenant(db)
    key = person_owner_key(user.id)
    person = await _raw(db, org, key, "Piotr", subject="owner", origin="person")
    agrees = await _raw(db, org, key, "piotr", subject="owner")
    differs = await _raw(db, org, key, "Anna", subject="owner")
    first = await _raw(db, org, key, "Email", subject="channel", agent_id=finance.id)
    second = await _raw(db, org, key, "Phone", subject="channel", agent_id=finance.id)
    already = await _raw(
        db, org, key, "Post", subject="channel", agent_id=finance.id, status="disputed"
    )
    await _raw(db, org, key, "No subject", subject=None)
    await _raw(db, org, key, "Alone", subject="solo")
    await claim_repo.bump_revision(db, organization_id=org.id, scope_key=key)

    result = await claims.consolidate(db, organization_id=org.id, scope_key=key)
    again = await claims.consolidate(db, organization_id=org.id, scope_key=key)

    assert result.ran and result.disputed == 3 and not again.ran
    for claim in (agrees, first, second, already):
        await db.refresh(claim)
    await db.refresh(differs)
    await db.refresh(person)
    assert person.status == "current" and agrees.status == "current"
    assert differs.status == "disputed"
    assert {first.status, second.status, already.status} == {"disputed"}


async def test_a_scope_nobody_wrote_has_nothing_to_consolidate(db: AsyncSession) -> None:
    org, user, *_ = await _tenant(db)

    result = await claims.consolidate(
        db, organization_id=org.id, scope_key=person_owner_key(user.id)
    )

    assert not result.ran


async def test_sharing_the_same_claim_twice_makes_one_copy(db: AsyncSession) -> None:
    org, user, finance, _ = await _tenant(db)
    source = (
        await _say(db, org, ClaimScope(person_owner_key(user.id), finance.id), "Launch is March")
    ).claim
    target = ClaimScope(organization_owner_key(org.id), None)

    first = await claims.share(db, claim=source, to=target, author_user_id=user.id)
    second = await claims.share(db, claim=source, to=target, author_user_id=user.id)

    assert first.id == second.id


async def test_the_repository_answers_empty_when_asked_about_nothing(db: AsyncSession) -> None:
    org, user, *_ = await _tenant(db)

    assert await claim_repo.many(db, organization_id=org.id, claim_ids=[]) == []
    assert await claim_repo.list_in_scopes(db, organization_id=org.id, scopes=[]) == []
    assert (
        await claim_repo.search(db, organization_id=org.id, scopes=[], terms=["x"], limit=3) == []
    )
    scope = ClaimScope(person_owner_key(user.id), None)
    assert (
        await claim_repo.search(db, organization_id=org.id, scopes=[scope], terms=[], limit=3) == []
    )


async def test_changed_scopes_are_listed_until_they_are_consolidated(db: AsyncSession) -> None:
    org, user, *_ = await _tenant(db)
    key = person_owner_key(user.id)
    await _say(db, org, ClaimScope(key, None), "Likes short answers", subject="style")

    pending = await claim_repo.scopes_with_changes(db, limit=10)
    assert (org.id, key) in {(state.organization_id, state.scope_key) for state in pending}

    await claims.consolidate(db, organization_id=org.id, scope_key=key)
    after = await claim_repo.scopes_with_changes(db, limit=10)
    assert (org.id, key) not in {(state.organization_id, state.scope_key) for state in after}


async def test_clearing_an_agent_removes_the_claims_bound_to_it_only(db: AsyncSession) -> None:
    org, user, finance, support = await _tenant(db)
    key = person_owner_key(user.id)
    await _say(db, org, ClaimScope(key, finance.id), "Acme is due", subject="acme")
    kept = await _say(db, org, ClaimScope(key, support.id), "Prefers email", subject="channel")
    shared = await _say(db, org, ClaimScope(key, None), "Likes tea", subject="drink")

    removed = await claim_repo.delete_for_agent(db, organization_id=org.id, agent_id=finance.id)

    assert removed == 1
    left = await claim_repo.list_in_scopes(
        db,
        organization_id=org.id,
        scopes=[ClaimScope(key, support.id), ClaimScope(key, None)],
    )
    assert {claim.id for claim in left} == {kept.claim.id, shared.claim.id}


async def test_deleting_an_account_removes_claims_in_every_organization_and_their_copies(
    db: AsyncSession,
) -> None:
    org, user, finance, _ = await _tenant(db)
    key = person_owner_key(user.id)
    source = (await _say(db, org, ClaimScope(key, finance.id), "Is moving", subject="home")).claim
    await claims.share(
        db,
        claim=source,
        to=ClaimScope(organization_owner_key(org.id), None),
        author_user_id=user.id,
    )
    bystander = await _say(
        db, org, ClaimScope(organization_owner_key(org.id), None), "Office is open", subject="hours"
    )

    removed = await claim_repo.delete_everywhere_about(db, scope_key=key)
    assert removed == 2
    assert await claim_repo.delete_everywhere_about(db, scope_key=key) == 0
    left = await claim_repo.list_in_scopes(
        db, organization_id=org.id, scopes=[ClaimScope(organization_owner_key(org.id), None)]
    )
    assert [claim.id for claim in left] == [bystander.claim.id]


async def test_erasing_a_person_removes_a_copy_of_a_copy(db: AsyncSession) -> None:
    """Personal claim to the project, then the project's copy to the organization."""
    org, user, finance, _ = await _tenant(db)
    key = person_owner_key(user.id)
    source = (await _say(db, org, ClaimScope(key, finance.id), "Is moving", subject="home")).claim
    first = await claims.share(
        db, claim=source, to=ClaimScope("project:p1", None), author_user_id=user.id
    )
    second = await claims.share(
        db,
        claim=first,
        to=ClaimScope(organization_owner_key(org.id), None),
        author_user_id=user.id,
    )
    assert second.derived_from == [str(first.id)], "the organization copy names only its parent"

    removed = await claim_repo.delete_for_scope(db, organization_id=org.id, scope_key=key)

    assert removed == 3
    everywhere = await claim_repo.list_in_scopes(
        db,
        organization_id=org.id,
        scopes=[ClaimScope("project:p1", None), ClaimScope(organization_owner_key(org.id), None)],
        statuses=("current", "disputed", "superseded", "merged", "retracted"),
    )
    assert everywhere == []
    assert await claim_repo.delete_everywhere_about(db, scope_key=key) == 0


async def test_clearing_an_agent_removes_its_shared_copies_too(db: AsyncSession) -> None:
    org, user, finance, support = await _tenant(db)
    key = person_owner_key(user.id)
    source = (await _say(db, org, ClaimScope(key, finance.id), "Acme is due", subject="acme")).claim
    await claims.share(
        db,
        claim=source,
        to=ClaimScope(organization_owner_key(org.id), None),
        author_user_id=user.id,
    )
    other = await _say(db, org, ClaimScope(key, support.id), "Prefers email", subject="channel")

    removed = await claim_repo.delete_for_agent(db, organization_id=org.id, agent_id=finance.id)

    assert removed == 2
    left = await claim_repo.list_in_scopes(
        db,
        organization_id=org.id,
        scopes=[ClaimScope(key, support.id), ClaimScope(organization_owner_key(org.id), None)],
    )
    assert [claim.id for claim in left] == [other.claim.id]


async def test_erasing_one_sharer_keeps_a_copy_another_person_also_shared(
    db: AsyncSession,
) -> None:
    org, ada, finance, support = await _tenant(db)
    bo = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Bo")
    db.add(bo)
    await db.flush()
    sentence = "Launch is March"
    ada_source = (
        await _say(db, org, ClaimScope(person_owner_key(ada.id), finance.id), sentence)
    ).claim
    bo_source = (
        await _say(db, org, ClaimScope(person_owner_key(bo.id), support.id), sentence)
    ).claim
    target = ClaimScope(organization_owner_key(org.id), None)
    copy = await claims.share(db, claim=ada_source, to=target, author_user_id=ada.id)
    again = await claims.share(db, claim=bo_source, to=target, author_user_id=bo.id)
    assert again.id == copy.id
    assert sorted(copy.derived_from) == sorted([str(ada_source.id), str(bo_source.id)])

    await claim_repo.delete_for_scope(
        db, organization_id=org.id, scope_key=person_owner_key(ada.id)
    )

    survivor = await claim_repo.get(db, organization_id=org.id, claim_id=copy.id)
    assert survivor is not None and survivor.derived_from == [str(bo_source.id)]
    await claim_repo.delete_for_scope(db, organization_id=org.id, scope_key=person_owner_key(bo.id))
    assert await claim_repo.get(db, organization_id=org.id, claim_id=copy.id) is None


async def test_a_correction_dated_for_later_leaves_the_old_claim_true_until_then(
    db: AsyncSession,
) -> None:
    org, user, finance, _ = await _tenant(db)
    scope = ClaimScope(person_owner_key(user.id), finance.id)
    old = (await _say(db, org, scope, "Anna handles invoices", user=user, origin="person")).claim
    monday = datetime.now(UTC) + timedelta(days=3)

    new = (
        await claims.remember(
            db,
            organization_id=org.id,
            scope=scope,
            statement="Piotr handles invoices",
            subject="invoice_owner",
            origin="person",
            author_user_id=user.id,
            effective_from=monday,
        )
    ).claim

    assert old.status == "current" and old.effective_to == monday
    profile = await claims.profile(db, organization_id=org.id, scopes=[scope])
    assert [claim.id for claim in profile] == [old.id], "the new claim waits for its date"
    found = await claim_repo.search(
        db, organization_id=org.id, scopes=[scope], terms=["invoices"], limit=10
    )
    assert [claim.id for claim in found] == [old.id]
    assert new.effective_from == monday
