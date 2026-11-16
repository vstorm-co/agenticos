"""Current-owner capture discovery against PostgreSQL, with no live browser or model."""

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import get_args
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, event, select, update

from app.api.deps import Auth, BrowserTeachingSvc
from app.api.exception_handlers import register_exception_handlers
from app.api.routes.v1 import browser_teaching as routes
from app.core.audit import current_impersonator, set_impersonator
from app.core.browser_teaching import TeachingReason, TeachingRefused
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.browser_teaching import BrowserTeachingSession
from app.db.models.organization import OrganizationMember
from app.db.models.skill_proposal import SkillProposal
from app.repositories import browser_teaching as repo
from app.schemas.browser_teaching import TeachingSummary
from app.services.browser_teaching import _listing
from tests.integration.test_browser_teaching import teaching as teaching
from tests.integration.test_personal_coding_accounts import context, organization, person
from tests.test_browser_teaching_contracts import ORIGIN, SECRET

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def capture(t, *, owner=None, org=None, **changes):
    owner, org = owner or t.owner, org or t.org
    agent, run = t.agent, t.run
    if org.id != t.org.id:
        agent = Agent(
            organization_id=org.id,
            owner_user_id=owner.id,
            name="Other tenant teacher",
            slug=uuid4().hex,
            draft_spec={},
        )
        t.db.add(agent)
        await t.db.flush()
        run = AgentRun(organization_id=org.id, user_id=owner.id, agent_id=agent.id)
        t.db.add(run)
        await t.db.flush()
    now = datetime.now(UTC)
    values = {
        "id": uuid4(),
        "organization_id": org.id,
        "owner_user_id": owner.id,
        "agent_id": agent.id,
        "run_id": run.id,
        "controller_id": uuid4(),
        "takeover_id": uuid4(),
        "connection_id": uuid4(),
        "call_id": "synthetic-private-call",
        "tab_id": "synthetic-private-tab",
        "title": "Synthetic retained capture",
        "allowed_origins": [ORIGIN],
        "source": "manual",
        "policy_generation": uuid4(),
        "request_fingerprint": "a" * 64,
        "status": "review",
        "created_at": now,
        "expires_at": now + timedelta(hours=24),
        "capture_ends_at": now + timedelta(minutes=30),
    }
    values.update(changes)
    row = BrowserTeachingSession(**values)
    t.db.add(row)
    await t.db.flush()
    return row


@asynccontextmanager
async def api(t, ctx=None):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(routes.router)
    app.dependency_overrides[get_args(Auth)[1].dependency] = lambda: ctx or t.ctx
    app.dependency_overrides[get_args(BrowserTeachingSvc)[1].dependency] = lambda: t.service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


async def test_owner_discovery_never_lists_a_colleague_or_the_same_person_in_another_tenant(
    teaching,
):
    t = teaching
    mine = await capture(t)
    other = await person(t.db)
    t.db.add(OrganizationMember(organization_id=t.org.id, user_id=other.id, role="owner"))
    await t.db.flush()
    colleague = await capture(t, owner=other)
    elsewhere = await organization(t.db, t.owner)
    other_tenant = await capture(t, org=elsewhere)
    for ctx, expected in (
        (t.ctx, mine.id),
        (context(other, t.org), colleague.id),
        (context(t.owner, elsewhere), other_tenant.id),
    ):
        result = await t.service.list(ctx)
        assert [item.id for item in result.items] == [expected]
        assert result.next_cursor is None


async def test_http_list_is_closed_and_the_query_never_loads_capture_values_or_private_ids(
    teaching,
):
    t = teaching
    row = await capture(
        t,
        sanitized_events=[{"value": SECRET}],
        review={"value": SECRET},
        procedure={"value": SECRET},
        source_hash="b" * 64,
        generation_token=uuid4(),
    )
    expected_id = row.id
    t.db.expunge(row)
    statements = []

    def inspect_sql(connection, cursor, statement, parameters, context, executemany):
        if "FROM browser_teaching_sessions" in statement:
            statements.append(statement)

    bind = t.db.get_bind()
    event.listen(bind, "before_cursor_execute", inspect_sql)
    try:
        async with api(t) as client:
            response = await client.get("/browser-teachings")
    finally:
        event.remove(bind, "before_cursor_execute", inspect_sql)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"items", "next_cursor"}
    assert body["items"][0]["id"] == str(expected_id)
    assert set(body["items"][0]) == set(TeachingSummary.model_fields)
    assert SECRET not in response.text
    assert "synthetic-private" not in response.text
    assert len(statements) == 1 and "FOR UPDATE" not in statements[0]
    selected = statements[0].split("FROM", 1)[0]
    for private in (
        "sanitized_events",
        "review",
        "procedure",
        "run_id",
        "controller_id",
        "call_id",
        "tab_id",
        "takeover_id",
        "connection_id",
        "generation_token",
        "max_cost_usd",
    ):
        assert f"browser_teaching_sessions.{private}" not in selected
    assert not t.db.dirty


async def test_newest_first_cursor_keeps_ties_stable_after_insert_and_boundary_deletion(teaching):
    t = teaching
    when = datetime.now(UTC) - timedelta(hours=1)
    ids = [UUID(int=i) for i in range(1, 6)]
    for session_id in ids:
        await capture(t, id=session_id, created_at=when)
    first = await t.service.list(t.ctx, limit=2)
    assert [item.id for item in first.items] == [ids[4], ids[3]]
    assert first.next_cursor is not None
    newer = await capture(t, created_at=when + timedelta(seconds=1))
    await t.db.execute(delete(BrowserTeachingSession).where(BrowserTeachingSession.id == ids[3]))
    second = await t.service.list(t.ctx, limit=2, cursor=first.next_cursor)
    assert [item.id for item in second.items] == [ids[2], ids[1]]
    assert second.next_cursor is not None
    third = await t.service.list(t.ctx, limit=2, cursor=second.next_cursor)
    assert [item.id for item in third.items] == [ids[0]]
    assert third.next_cursor is None
    exhausted = await t.service.list(
        t.ctx,
        cursor=_listing.encode_cursor(
            t.org.id, t.owner.id, BrowserTeachingSession(id=ids[0], created_at=when)
        ),
    )
    assert exhausted.items == () and exhausted.next_cursor is None
    fresh = await t.service.list(t.ctx, limit=1)
    assert fresh.items[0].id == newer.id


async def test_maximum_page_is_bounded_and_a_single_lookahead_does_not_drop_the_last_capture(
    teaching,
):
    t = teaching
    when = datetime.now(UTC) - timedelta(hours=2)
    for number in range(101):
        await capture(t, created_at=when + timedelta(seconds=number), status="discarded")
    first = await t.service.list(t.ctx, limit=100)
    assert len(first.items) == 100 and first.next_cursor is not None
    final = await t.service.list(t.ctx, limit=100, cursor=first.next_cursor)
    assert len(final.items) == 1 and final.next_cursor is None
    assert final.items[0].created_at == when
    assert final.items[0].id not in {item.id for item in first.items}


@pytest.mark.parametrize(
    ("status", "generation"),
    [
        ("recording", "none"),
        ("paused", "none"),
        ("review", "none"),
        ("review", "queued"),
        ("review", "generating"),
    ],
)
async def test_expiry_projection_matches_owner_read_without_mutating_the_capture(
    teaching, status, generation
):
    t = teaching
    row = await capture(
        t,
        status=status,
        revision=7,
        generation_state=generation,
        generation_token=uuid4(),
        generation_revision=7,
        source_hash="c" * 64,
        sanitized_events=[{"value": SECRET}],
        review={"value": SECRET},
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    result = (await t.service.list(t.ctx)).items[0]
    assert result.status == "expired" and result.reason_code == "teaching_expired"
    assert result.title == "" and result.allowed_origins == () and result.revision == 8
    assert result.generation_state == ("none" if generation == "none" else "cancelled")
    assert not t.db.dirty
    stored = (
        await t.db.execute(
            select(
                BrowserTeachingSession.status,
                BrowserTeachingSession.revision,
                BrowserTeachingSession.title,
                BrowserTeachingSession.sanitized_events,
            ).where(BrowserTeachingSession.id == row.id)
        )
    ).one()
    assert stored == (status, 7, "Synthetic retained capture", [{"value": SECRET}])
    canonical = await t.service.get(t.ctx, row.id)
    assert result == TeachingSummary.model_validate(canonical, from_attributes=True)
    assert (await t.service.list(t.ctx)).items[0] == result


@pytest.mark.parametrize("status", ["proposed", "discarded", "expired"])
async def test_terminal_captures_keep_the_canonical_read_lifecycle(teaching, status):
    t = teaching
    proposal = SkillProposal(
        organization_id=t.org.id, name="Synthetic proposal", source="browser_teaching"
    )
    t.db.add(proposal)
    await t.db.flush()
    row = await capture(
        t,
        status=status,
        proposal_id=proposal.id if status == "proposed" else None,
        title="" if status != "proposed" else "Synthetic retained capture",
        allowed_origins=[] if status != "proposed" else [ORIGIN],
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    listed = (await t.service.list(t.ctx)).items[0]
    canonical = await t.service.get(t.ctx, row.id)
    assert listed == TeachingSummary.model_validate(canonical, from_attributes=True)
    assert listed.status == status and listed.revision == 1


async def test_accepted_owner_recovery_survives_ended_tabs_disabled_teaching_and_lost_edit_permission(
    teaching, monkeypatch
):
    t = teaching
    row = await capture(
        t,
        source="refinement",
        takeover_id=None,
        connection_id=None,
        preference_generation=uuid4(),
        browser_completed=True,
        verified_success=True,
    )
    await t.lease.close()
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", False)
    await t.db.execute(
        update(OrganizationMember)
        .where(
            OrganizationMember.organization_id == t.org.id,
            OrganizationMember.user_id == t.owner.id,
        )
        .values(role="viewer")
    )
    policy = await repo.policy(t.db, t.org.id)
    policy.enabled = False
    await t.db.flush()
    viewer = replace(t.ctx, role="viewer")
    assert not viewer.has(Perm.SKILLS_EDIT)
    async with api(t, viewer) as client:
        response = await client.get("/browser-teachings")
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == str(row.id)
    assert response.json()["items"][0]["source"] == "refinement"
    assert response.json()["items"][0]["verified_success"] is True
    assert (await t.service.get(viewer, row.id)).id == row.id


@pytest.mark.parametrize("revocation", ["membership", "inactive_user"])
async def test_each_page_refreshes_membership_before_even_reading_its_cursor(teaching, revocation):
    t = teaching
    await capture(t)
    await capture(t)
    first = await t.service.list(t.ctx, limit=1)
    assert first.next_cursor is not None
    if revocation == "membership":
        await t.db.execute(
            delete(OrganizationMember).where(
                OrganizationMember.organization_id == t.org.id,
                OrganizationMember.user_id == t.owner.id,
            )
        )
    else:
        t.owner.is_active = False
    await t.db.flush()
    for value in (first.next_cursor, "malformed"):
        with pytest.raises(TeachingRefused) as caught:
            await t.service.list(t.ctx, cursor=value)
        assert caught.value.reason == TeachingReason.UNAVAILABLE
    async with api(t) as client:
        response = await client.get("/browser-teachings", params={"cursor": first.next_cursor})
    assert response.status_code == 400
    assert response.json()["error"]["details"]["reason_code"] == "teaching_unavailable"
    assert "Synthetic" not in response.text


@pytest.mark.parametrize(
    "identity", ["api_key", "impersonated_context", "anonymous", "publisher", "audit_impersonator"]
)
async def test_nonpersonal_or_impersonated_callers_cannot_discover_owner_captures(
    teaching, identity
):
    t = teaching
    await capture(t)
    ctx = t.ctx
    previous = current_impersonator()
    if identity == "api_key":
        ctx = replace(ctx, api_key_id=uuid4())
    elif identity == "impersonated_context":
        ctx = replace(ctx, is_impersonated=True)
    elif identity == "anonymous":
        ctx = AuthContext.anonymous(t.org.id)
    elif identity == "publisher":
        ctx = replace(ctx, subject_is_publisher_fallback=True)
    else:
        set_impersonator(uuid4())
    try:
        with pytest.raises(TeachingRefused) as caught:
            await t.service.list(ctx)
        assert caught.value.reason == TeachingReason.UNAVAILABLE
    finally:
        set_impersonator(previous)


@pytest.mark.parametrize("audience", ["organization", "owner"])
async def test_a_page_cursor_cannot_be_reused_after_an_audience_switch(teaching, audience):
    t = teaching
    await capture(t)
    await capture(t)
    first = await t.service.list(t.ctx, limit=1)
    if audience == "organization":
        ctx = context(t.owner, await organization(t.db, t.owner))
    else:
        other = await person(t.db)
        t.db.add(OrganizationMember(organization_id=t.org.id, user_id=other.id, role="owner"))
        await t.db.flush()
        ctx = context(other, t.org)
    async with api(t, ctx) as client:
        response = await client.get("/browser-teachings", params={"cursor": first.next_cursor})
        fresh = await client.get("/browser-teachings")
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "BAD_REQUEST"
    assert error["details"]["reason_code"] == "invalid_cursor"
    assert error["details"]["fields"][0]["field"] == "cursor"
    assert first.next_cursor not in response.text
    assert fresh.status_code == 200 and fresh.json() == {"items": [], "next_cursor": None}


@pytest.mark.parametrize("limit", [0, 101])
async def test_service_page_bound_cannot_be_bypassed_by_an_internal_caller(teaching, limit):
    with pytest.raises(BadRequestError) as caught:
        await teaching.service.list(teaching.ctx, limit=limit)
    assert caught.value.details["fields"][0]["field"] == "limit"


async def test_empty_cursor_is_a_fixed_bad_request_not_an_empty_first_page(teaching):
    async with api(teaching) as client:
        response = await client.get("/browser-teachings", params={"cursor": ""})
    assert response.status_code == 400
    assert response.json()["error"]["details"]["reason_code"] == "invalid_cursor"
