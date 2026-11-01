"""The ledger as a run reaches it, against Postgres (#2090).

`_runtime` opens its own session per call; here that session is the test's, so what
is checked is the authorization and the queries rather than the plumbing.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory_keys import organization_owner_key, person_owner_key, project_owner_key
from app.db.models.agent import Agent
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.project import Project
from app.db.models.user import User
from app.repositories import memory_claim as claim_repo
from app.repositories.memory_claim import ClaimScope
from app.services.memory import _runtime as runtime

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _world(db: AsyncSession, *, role: str = "owner"):
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Ada")
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role))
    agent = Agent(
        organization_id=org.id,
        name="Finance",
        created_by_user_id=user.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    project = Project(organization_id=org.id, owner_user_id=user.id, name="Launch")
    db.add_all([agent, project])
    await db.flush()
    conversation = Conversation(
        organization_id=org.id, user_id=user.id, project_id=project.id, title="x"
    )
    db.add(conversation)
    await db.flush()
    return user, org, agent, project, conversation


@pytest.fixture(autouse=True)
def _own_session(monkeypatch: pytest.MonkeyPatch, db: AsyncSession) -> None:
    @asynccontextmanager
    async def reuse():
        yield db

    monkeypatch.setattr(runtime, "get_db_context", reuse)
    monkeypatch.setattr(runtime, "person_still_exists", _yes)


async def _yes(*_args, **_kwargs) -> bool:
    return True


async def _remember(org, scope, statement, user, conversation=None, subject="topic"):
    return await runtime.remember(
        organization_id=org.id,
        scope=scope,
        statement=statement,
        subject=subject,
        kind="fact",
        author_user_id=user.id,
        conversation_id=conversation.id if conversation else None,
        run_id=None,
        effective_from=None,
    )


async def test_a_conversation_knows_its_project(db: AsyncSession) -> None:
    user, org, agent, project, conversation = await _world(db)

    assert await runtime.project_of(conversation.id) == project.id
    assert await runtime.project_of(None) is None


async def test_a_person_gone_means_nothing_is_written(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, org, agent, *_ = await _world(db)
    monkeypatch.setattr(runtime, "person_still_exists", _no)

    saved = await _remember(org, ClaimScope(person_owner_key(user.id), None), "x", user)

    assert saved is None


async def _no(*_args, **_kwargs) -> bool:
    return False


async def test_a_profile_is_bounded_text_and_a_scope_with_nothing_is_empty(
    db: AsyncSession,
) -> None:
    user, org, agent, *_ = await _world(db)
    key = person_owner_key(user.id)
    scopes = [ClaimScope(key, None), ClaimScope(key, agent.id)]
    assert await runtime.profile_block(organization_id=org.id, scopes=scopes) == ""

    await runtime.remember(
        organization_id=org.id,
        scope=ClaimScope(key, None),
        statement="Prefers short answers",
        subject="style",
        kind="preference",
        author_user_id=user.id,
        conversation_id=None,
        run_id=None,
        effective_from=datetime(2026, 11, 1, tzinfo=UTC),
    )

    text = await runtime.profile_block(organization_id=org.id, scopes=scopes)
    assert text == "- Prefers short answers (since 2026-11-01)"


async def test_recall_and_correct_stay_inside_the_scopes_given(db: AsyncSession) -> None:
    user, org, agent, *_ = await _world(db)
    mine = ClaimScope(person_owner_key(user.id), agent.id)
    theirs = ClaimScope(person_owner_key(uuid.uuid4()), agent.id)
    saved = await _remember(org, mine, "The Acme renewal is due in March", user, subject="acme")
    foreign = await _remember(org, theirs, "Acme is leaving", user, subject="acme")
    assert saved is not None and foreign is not None

    found = await runtime.recall(organization_id=org.id, scopes=[mine], query="acme due")
    assert [claim.statement for claim in found] == ["The Acme renewal is due in March"]

    refused = await runtime.correct(
        organization_id=org.id,
        claim_id=foreign[0].id,
        scopes=[mine],
        statement="Acme stays",
        author_user_id=user.id,
        effective_from=None,
    )
    fixed = await runtime.correct(
        organization_id=org.id,
        claim_id=saved[0].id,
        scopes=[mine],
        statement="The Acme renewal is due in April",
        author_user_id=user.id,
        effective_from=None,
    )
    assert refused is None
    assert fixed is not None and fixed.origin == "person"


async def test_an_owner_shares_to_the_project_and_the_organization(db: AsyncSession) -> None:
    user, org, agent, project, conversation = await _world(db)
    mine = ClaimScope(person_owner_key(user.id), agent.id)
    saved = await _remember(org, mine, "Launch is 3 March", user, conversation, subject="launch")
    assert saved is not None

    to_project = await runtime.share(
        organization_id=org.id,
        claim_id=saved[0].id,
        scopes=[mine],
        to="project",
        run_person=user.id,
        conversation_id=conversation.id,
    )
    to_org = await runtime.share(
        organization_id=org.id,
        claim_id=saved[0].id,
        scopes=[mine],
        to="organization",
        run_person=user.id,
        conversation_id=conversation.id,
    )

    assert to_project is not None and to_project.scope == "project"
    assert to_org is not None and to_org.scope == "org"
    shared = await claim_repo.list_in_scopes(
        db,
        organization_id=org.id,
        scopes=[
            ClaimScope(project_owner_key(project.id), None),
            ClaimScope(organization_owner_key(org.id), None),
        ],
    )
    assert len(shared) == 2 and all(c.derived_from == [str(saved[0].id)] for c in shared)


async def test_nobody_behind_the_run_means_nothing_is_shared(db: AsyncSession) -> None:
    user, org, agent, project, conversation = await _world(db)
    mine = ClaimScope(person_owner_key(user.id), agent.id)
    saved = await _remember(org, mine, "Launch is 3 March", user, conversation, subject="launch")
    assert saved is not None

    with pytest.raises(runtime.ShareRefused, match="Nobody"):
        await runtime.share(
            organization_id=org.id,
            claim_id=saved[0].id,
            scopes=[mine],
            to="organization",
            run_person=None,
            conversation_id=conversation.id,
        )


async def test_a_viewer_may_not_widen_anything_to_the_organization(db: AsyncSession) -> None:
    user, org, agent, project, conversation = await _world(db, role="viewer")
    mine = ClaimScope(person_owner_key(user.id), agent.id)
    saved = await _remember(org, mine, "Launch is 3 March", user, conversation, subject="launch")
    assert saved is not None

    with pytest.raises(runtime.ShareRefused, match="context:edit"):
        await runtime.share(
            organization_id=org.id,
            claim_id=saved[0].id,
            scopes=[mine],
            to="organization",
            run_person=user.id,
            conversation_id=conversation.id,
        )


async def test_a_conversation_outside_a_project_cannot_share_to_one(db: AsyncSession) -> None:
    user, org, agent, project, conversation = await _world(db)
    conversation.project_id = None
    await db.flush()
    mine = ClaimScope(person_owner_key(user.id), agent.id)
    saved = await _remember(org, mine, "Launch is 3 March", user, conversation, subject="launch")
    assert saved is not None

    with pytest.raises(runtime.ShareRefused, match="not in a project"):
        await runtime.share(
            organization_id=org.id,
            claim_id=saved[0].id,
            scopes=[mine],
            to="project",
            run_person=user.id,
            conversation_id=conversation.id,
        )


async def test_a_claim_outside_the_readable_scopes_is_not_shared(db: AsyncSession) -> None:
    user, org, agent, project, conversation = await _world(db)
    mine = ClaimScope(person_owner_key(user.id), agent.id)
    other = ClaimScope(person_owner_key(uuid.uuid4()), agent.id)
    saved = await _remember(org, other, "Secret", user, conversation, subject="secret")
    assert saved is not None

    shared = await runtime.share(
        organization_id=org.id,
        claim_id=saved[0].id,
        scopes=[mine],
        to="organization",
        run_person=user.id,
        conversation_id=conversation.id,
    )

    assert shared is None


async def test_somebody_who_may_not_edit_the_project_cannot_share_into_it(
    db: AsyncSession,
) -> None:
    user, org, agent, project, conversation = await _world(db, role="viewer")
    stranger = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Bo")
    db.add(stranger)
    await db.flush()
    project.owner_user_id = stranger.id
    await db.flush()
    mine = ClaimScope(person_owner_key(user.id), agent.id)
    saved = await _remember(org, mine, "Launch is 3 March", user, conversation, subject="launch")
    assert saved is not None

    with pytest.raises(runtime.ShareRefused, match="may not edit this project"):
        await runtime.share(
            organization_id=org.id,
            claim_id=saved[0].id,
            scopes=[mine],
            to="project",
            run_person=user.id,
            conversation_id=conversation.id,
        )
