"""Browser teaching capture (#113 slice 1) against a real database.

What is checked here is what the schema and the service refuse: recording
without the human-control lease, another person's or another tab's session,
a repeated or conflicting event, a limit, an origin outside the allowed list,
and retention. Secrets fed to the capture boundary - typed text, URL tokens,
OTP input and page text - must appear in no stored row, audit entry or log.
"""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.agents.browser_events import BrowserCommand
from app.agents.spec import AgentSpec
from app.clients.redis import RedisClient
from app.core.browser_teaching import (
    MAX_EVENTS,
    Observation,
    Role,
    StructuralTarget,
    TeachingConflict,
    TeachingReason,
    TeachingRefused,
    TeachingState,
)
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.browser_teaching import BrowserTeachingSession
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.schemas.browser_teaching import TeachingChange, TeachingStart
from app.services.browser_teaching import _capture, _hold, _sweep
from app.services.browser_teaching._capture import HoldCapture
from app.services.browser_teaching._hold import Hold
from app.services.browser_teaching._service import BrowserTeachingService

pytestmark = pytest.mark.anyio

ORIGIN = "https://portal.example.test"
SECRETS = (
    "hunter2-synthetic-password",
    "otp-424242",
    "tok_SYNTHETIC_URL_TOKEN",
    "sessionid=SYNTHETIC_COOKIE",
    "Synthetic invoice text on the page",
)


class FakeRedis:
    """Just enough of `RedisClient` for the hold lease: SET NX, GET and the two scripts."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    @property
    def raw(self) -> FakeRedis:
        return self

    async def eval(self, script: str, _count: int, key: str, value: str, *_args: object) -> int:
        if self.values.get(key) != value:
            return 0
        if "del" in script:
            del self.values[key]
        return 1


def _redis(client: FakeRedis) -> RedisClient:
    """Treat the test double as the subset of Redis used by browser teaching."""
    return cast(RedisClient, client)


@pytest.fixture(autouse=True)
def enabled(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    allowed: list[uuid.UUID] = []
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", True)
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ORGANIZATION_IDS", allowed)
    return allowed


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


async def _person(db, organization: Organization, role: str = "builder") -> User:
    user = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=organization.id, user_id=user.id, role=role
        )
    )
    await db.flush()
    return user


async def _world(db, enabled: list[uuid.UUID]) -> tuple[Organization, User, Agent]:
    founder = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(founder)
    await db.flush()
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=founder.id
    )
    db.add(organization)
    await db.flush()
    enabled.append(organization.id)
    owner = await _person(db, organization)
    agent = Agent(
        organization_id=organization.id,
        owner_user_id=owner.id,
        name="Teacher",
        slug=f"teacher-{uuid.uuid4().hex[:8]}",
        draft_spec=AgentSpec(name="Teacher").model_dump(mode="json"),
        visibility=Visibility.ORG.value,
    )
    db.add(agent)
    await db.flush()
    return organization, owner, agent


async def _run(db, agent: Agent, user: User) -> AgentRun:
    run = AgentRun(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        user_id=user.id,
        status="running",
        surface=RunSurface.WEB.value,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    return run


def _ctx(user: User, organization: Organization, role: str = "builder") -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=organization.id, role=role)


async def _hold_for(
    redis: FakeRedis, run: AgentRun, user: User, call_id: str = "call-1", tab: str = "main"
) -> Hold:
    hold = Hold(
        organization_id=run.organization_id,
        run_id=run.id,
        agent_id=run.agent_id,
        user_id=user.id,
        call_id=call_id,
        tab_id=tab,
        hold_id=uuid.uuid4(),
    )
    assert await _hold.claim(_redis(redis), hold)
    return hold


def _start(run: AgentRun, call_id: str = "call-1") -> TeachingStart:
    return TeachingStart(
        run_id=run.id, call_id=call_id, title="Download invoice", allowed_origins=(ORIGIN,)
    )


def _seen(role: Role = "button", n: int = 1, *, auth: bool = False) -> Observation:
    return Observation(
        origin=ORIGIN,
        target=StructuralTarget(role=role, fingerprint="sha256:" + f"{n:064x}"),
        authentication=auth,
    )


async def _recording(db, redis: FakeRedis, enabled: list[uuid.UUID]):
    organization, owner, agent = await _world(db, enabled)
    run = await _run(db, agent, owner)
    hold = await _hold_for(redis, run, owner)
    service = BrowserTeachingService(db, _redis(redis))
    started = await service.start(_ctx(owner, organization), _start(run), "key-1")
    return organization, owner, agent, run, hold, service, started


async def test_recording_needs_the_owner_to_hold_the_view_now(db, redis, enabled) -> None:
    organization, owner, agent = await _world(db, enabled)
    run = await _run(db, agent, owner)
    service = BrowserTeachingService(db, redis)
    with pytest.raises(TeachingRefused) as refused:
        await service.start(_ctx(owner, organization), _start(run), None)
    assert refused.value.reason == TeachingReason.NOT_HELD


async def test_teaching_is_refused_while_the_deployment_flag_is_off(
    db, redis, enabled, monkeypatch
) -> None:
    organization, owner, agent = await _world(db, enabled)
    run = await _run(db, agent, owner)
    await _hold_for(redis, run, owner)
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", False)
    with pytest.raises(TeachingRefused) as refused:
        await BrowserTeachingService(db, redis).start(_ctx(owner, organization), _start(run), None)
    assert refused.value.reason == TeachingReason.DISABLED


async def test_a_repeated_start_returns_the_same_session_and_a_reused_key_conflicts(
    db, redis, enabled
) -> None:
    organization, owner, _, run, _, service, started = await _recording(db, redis, enabled)
    again = await service.start(_ctx(owner, organization), _start(run), "key-1")
    assert again.id == started.id
    changed = TeachingStart(
        run_id=run.id, call_id="call-1", title="Other", allowed_origins=(ORIGIN,)
    )
    with pytest.raises(TeachingConflict) as conflict:
        await service.start(_ctx(owner, organization), changed, "key-1")
    assert conflict.value.reason == TeachingReason.REQUEST_REUSED


@pytest.mark.security
async def test_another_person_holding_the_tab_cannot_record_into_the_session(
    db, redis, enabled
) -> None:
    organization, owner, agent, run, hold, service, started = await _recording(db, redis, enabled)
    intruder = await _person(db, organization)
    with pytest.raises(NotFoundError):
        await service.get(_ctx(intruder, organization), started.id)
    stranger_hold = hold.model_copy(update={"user_id": intruder.id, "hold_id": uuid.uuid4()})
    await service.record(stranger_hold, input_id=uuid.uuid4(), action="click", observation=_seen())
    assert (await service.get(_ctx(owner, organization), started.id)).events == ()


@pytest.mark.security
async def test_a_second_tab_cannot_record_into_the_first_tabs_session(db, redis, enabled) -> None:
    organization, owner, _, run, hold, service, started = await _recording(db, redis, enabled)
    other_tab = await _hold_for(redis, run, owner, call_id="call-2", tab="second")
    await service.record(other_tab, input_id=uuid.uuid4(), action="click", observation=_seen())
    await service.record(hold, input_id=uuid.uuid4(), action="click", observation=_seen())
    events = (await service.get(_ctx(owner, organization), started.id)).events
    assert [event.sequence for event in events] == [1]


@pytest.mark.security
async def test_another_organization_cannot_read_the_session(db, redis, enabled) -> None:
    _, _, _, _, _, service, started = await _recording(db, redis, enabled)
    elsewhere, outsider, _ = await _world(db, enabled)
    with pytest.raises(NotFoundError):
        await service.get(_ctx(outsider, elsewhere), started.id)


async def test_a_repeated_input_is_stored_once_and_a_changed_one_pauses(db, redis, enabled) -> None:
    organization, owner, _, _, hold, service, started = await _recording(db, redis, enabled)
    input_id = uuid.uuid4()
    await service.record(hold, input_id=input_id, action="click", observation=_seen())
    await service.record(hold, input_id=input_id, action="click", observation=_seen())
    read = await service.get(_ctx(owner, organization), started.id)
    assert len(read.events) == 1 and read.status == TeachingState.RECORDING
    await service.record(hold, input_id=input_id, action="click", observation=_seen(n=2))
    read = await service.get(_ctx(owner, organization), started.id)
    assert len(read.events) == 1
    assert (read.status, read.reason_code) == (TeachingState.PAUSED, TeachingReason.EVENT_CONFLICT)


async def test_the_event_limit_pauses_capture_instead_of_truncating(db, redis, enabled) -> None:
    organization, owner, _, _, hold, service, started = await _recording(db, redis, enabled)
    row = await db.get(BrowserTeachingSession, started.id)
    row.sanitized_events = [
        {
            "sequence": n,
            "input_id": str(uuid.uuid4()),
            "action": "scroll",
            "origin": ORIGIN,
            "target": None,
            "direction": "down",
            "human_step": False,
        }
        for n in range(1, MAX_EVENTS + 1)
    ]
    await db.flush()
    await service.record(hold, input_id=uuid.uuid4(), action="click", observation=_seen())
    read = await service.get(_ctx(owner, organization), started.id)
    assert len(read.events) == MAX_EVENTS
    assert (read.status, read.reason_code) == (TeachingState.PAUSED, TeachingReason.EVENT_LIMIT)
    with pytest.raises(TeachingRefused) as refused:
        await service.change(
            _ctx(owner, organization), started.id, TeachingChange(action="resume"), read.revision
        )
    assert refused.value.reason == TeachingReason.EVENT_LIMIT


async def test_the_capture_time_limit_pauses_capture(db, redis, enabled) -> None:
    organization, owner, _, _, hold, service, started = await _recording(db, redis, enabled)
    await db.execute(
        update(BrowserTeachingSession)
        .where(BrowserTeachingSession.id == started.id)
        .values(capture_ends_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await service.record(hold, input_id=uuid.uuid4(), action="click", observation=_seen())
    read = await service.get(_ctx(owner, organization), started.id)
    assert (read.status, read.reason_code, read.events) == (
        TeachingState.PAUSED,
        TeachingReason.TIME_LIMIT,
        (),
    )


async def test_an_origin_outside_the_allowed_list_pauses_capture(db, redis, enabled) -> None:
    organization, owner, _, _, hold, service, started = await _recording(db, redis, enabled)
    elsewhere = Observation(origin="https://other.example.test")
    await service.record(hold, input_id=uuid.uuid4(), action="navigate", observation=elsewhere)
    read = await service.get(_ctx(owner, organization), started.id)
    assert (read.status, read.reason_code, read.events) == (
        TeachingState.PAUSED,
        TeachingReason.ORIGIN_REFUSED,
        (),
    )


async def test_an_authentication_input_becomes_a_human_step_and_pauses(db, redis, enabled) -> None:
    organization, owner, _, _, hold, service, started = await _recording(db, redis, enabled)
    await service.record(
        hold,
        input_id=uuid.uuid4(),
        action="input_parameter",
        observation=_seen("textbox", auth=True),
    )
    read = await service.get(_ctx(owner, organization), started.id)
    assert read.events[0].action == "checkpoint" and read.events[0].human_step
    assert read.events[0].target is None
    assert (read.status, read.reason_code) == (TeachingState.PAUSED, TeachingReason.AUTHENTICATION)


async def test_a_lost_hold_stops_capture_and_resume_needs_a_fresh_one(db, redis, enabled) -> None:
    organization, owner, _, run, hold, service, started = await _recording(db, redis, enabled)
    await _hold.release(redis, hold)
    await service.record(hold, input_id=uuid.uuid4(), action="click", observation=_seen())
    read = await service.get(_ctx(owner, organization), started.id)
    assert (read.status, read.reason_code, read.events) == (
        TeachingState.PAUSED,
        TeachingReason.OWNERSHIP_LOST,
        (),
    )
    with pytest.raises(TeachingRefused):
        await service.change(
            _ctx(owner, organization), started.id, TeachingChange(action="resume"), read.revision
        )
    fresh = await _hold_for(redis, run, owner)
    resumed = await service.change(
        _ctx(owner, organization), started.id, TeachingChange(action="resume"), read.revision
    )
    assert resumed.status == TeachingState.RECORDING
    await service.record(hold, input_id=uuid.uuid4(), action="click", observation=_seen())
    await service.record(fresh, input_id=uuid.uuid4(), action="click", observation=_seen())
    assert len((await service.get(_ctx(owner, organization), started.id)).events) == 1


async def test_a_stale_revision_conflicts_and_pause_stops_recording(db, redis, enabled) -> None:
    organization, owner, _, _, hold, service, started = await _recording(db, redis, enabled)
    with pytest.raises(TeachingConflict):
        await service.change(
            _ctx(owner, organization),
            started.id,
            TeachingChange(action="pause"),
            started.revision + 7,
        )
    paused = await service.change(
        _ctx(owner, organization), started.id, TeachingChange(action="pause"), started.revision
    )
    await service.record(hold, input_id=uuid.uuid4(), action="click", observation=_seen())
    read = await service.get(_ctx(owner, organization), started.id)
    assert (paused.status, read.events) == (TeachingState.PAUSED, ())


async def test_stop_is_repeatable_and_discard_erases_the_payload(db, redis, enabled) -> None:
    organization, owner, _, _, hold, service, started = await _recording(db, redis, enabled)
    await service.record(hold, input_id=uuid.uuid4(), action="click", observation=_seen())
    stopped = await service.stop(_ctx(owner, organization), started.id)
    assert stopped == await service.stop(_ctx(owner, organization), started.id)
    assert stopped.status == TeachingState.REVIEW and len(stopped.events) == 1
    await service.discard(_ctx(owner, organization), started.id)
    row = await db.get(BrowserTeachingSession, started.id)
    assert (row.status, row.sanitized_events, row.allowed_origins, row.title) == (
        "discarded",
        [],
        [],
        "",
    )


async def test_a_removed_member_cannot_record_on(db, redis, enabled) -> None:
    organization, owner, _, _, hold, service, started = await _recording(db, redis, enabled)
    await db.execute(
        update(OrganizationMember)
        .where(OrganizationMember.user_id == owner.id)
        .values(role="viewer")
    )
    await service.record(hold, input_id=uuid.uuid4(), action="click", observation=_seen())
    row = await db.get(BrowserTeachingSession, started.id)
    assert (row.status, row.reason_code, row.sanitized_events) == (
        "paused",
        "authority_changed",
        [],
    )


async def test_the_schema_refuses_a_second_active_session_for_one_view(db, redis, enabled) -> None:
    _, _, _, _, _, _, started = await _recording(db, redis, enabled)
    row = await db.get(BrowserTeachingSession, started.id)
    twin = BrowserTeachingSession(
        **{
            c: getattr(row, c)
            for c in (
                "organization_id",
                "owner_user_id",
                "agent_id",
                "run_id",
                "call_id",
                "tab_id",
                "title",
                "allowed_origins",
                "request_fingerprint",
                "capture_ends_at",
                "expires_at",
            )
        },
        id=uuid.uuid4(),
        request_key="other",
        status="paused",
        revision=1,
    )
    db.add(twin)
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_the_schema_refuses_an_erased_row_that_still_holds_steps(db, redis, enabled) -> None:
    _, _, _, _, hold, service, started = await _recording(db, redis, enabled)
    await service.record(hold, input_id=uuid.uuid4(), action="click", observation=_seen())
    with pytest.raises(IntegrityError):
        await db.execute(
            update(BrowserTeachingSession)
            .where(BrowserTeachingSession.id == started.id)
            .values(status="discarded")
        )


async def test_retention_expires_and_erases_open_sessions(db, redis, enabled, monkeypatch) -> None:
    _, _, _, _, hold, service, started = await _recording(db, redis, enabled)
    await service.record(hold, input_id=uuid.uuid4(), action="click", observation=_seen())
    await db.execute(
        update(BrowserTeachingSession)
        .where(BrowserTeachingSession.id == started.id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", False)
    monkeypatch.setattr(_sweep.live_browse, "client", lambda: redis)
    monkeypatch.setattr(_sweep.live_browse, "connect_in_worker", _noop)
    monkeypatch.setattr(_sweep, "get_db_context", _contexts(db))
    assert await _sweep.sweep_browser_teachings() >= 1
    row = await db.get(BrowserTeachingSession, started.id)
    assert (row.status, row.reason_code, row.sanitized_events) == (
        "expired",
        "teaching_expired",
        [],
    )


async def test_the_sweep_pauses_a_recording_whose_hold_is_gone(
    db, redis, enabled, monkeypatch
) -> None:
    _, _, _, _, hold, _, started = await _recording(db, redis, enabled)
    await _hold.release(redis, hold)
    monkeypatch.setattr(_sweep.live_browse, "client", lambda: redis)
    monkeypatch.setattr(_sweep.live_browse, "connect_in_worker", _noop)
    monkeypatch.setattr(_sweep, "get_db_context", _contexts(db))
    await _sweep.sweep_browser_teachings()
    row = await db.get(BrowserTeachingSession, started.id)
    assert (row.status, row.reason_code) == ("paused", "browser_ownership_lost")


@pytest.mark.security
async def test_secrets_at_the_input_boundary_reach_no_row_audit_or_log(
    db, redis, enabled, monkeypatch, caplog
) -> None:
    """Typed passwords, OTP codes, URL tokens, cookies and page text are never persisted.

    The commands carry synthetic secrets through the real capture object; the
    observer stands in for the page and reports only structure.
    """
    organization, owner, _, run, _, service, started = await _recording(db, redis, enabled)
    capture = HoldCapture(
        organization_id=organization.id,
        run_id=run.id,
        agent_id=run.agent_id,
        user_id=owner.id,
        tab_id="main",
        redis=redis,
        run_observer=_observer({"point": "button", "focus": "textbox"}),
    )
    hold = await _hold.current(_redis(redis), run.id, "call-1")
    assert hold is not None
    await _hold.release(_redis(redis), hold)
    monkeypatch.setattr(_capture, "get_db_context", _contexts(db))
    caplog.set_level(logging.DEBUG)
    await capture.begin("call-1", str(owner.id))
    await service.change(
        _ctx(owner, organization), started.id, TeachingChange(action="pause"), started.revision
    )
    read = await service.get(_ctx(owner, organization), started.id)
    await service.change(
        _ctx(owner, organization), started.id, TeachingChange(action="resume"), read.revision
    )
    by = str(owner.id)
    commands = [
        BrowserCommand(
            type="navigate",
            url=f"https://portal.example.test/inv/{SECRETS[2]}?token={SECRETS[2]}#{SECRETS[1]}",
            by_user_id=by,
        ),
        BrowserCommand(type="click", x=10, y=20, by_user_id=by),
        BrowserCommand(type="type", text=SECRETS[0], by_user_id=by),
        BrowserCommand(type="type", text=SECRETS[1], by_user_id=by),
        BrowserCommand(type="key", key="Enter", by_user_id=by),
        BrowserCommand(type="scroll", dy=300, by_user_id=by),
    ]
    for command in commands:
        prepared = await capture.before_input(command)
        await capture.after_input(prepared)
    await capture.end()
    row = await db.get(BrowserTeachingSession, started.id)
    audits = (
        await db.scalars(
            select(AppAdminAuditLog).where(AppAdminAuditLog.target_id == str(started.id))
        )
    ).all()
    stored = (
        json.dumps(
            {
                "row": [row.sanitized_events, row.title, row.allowed_origins, row.reason_code],
                "audit": [entry.details for entry in audits],
            },
            default=str,
        )
        + caplog.text
    )
    assert [event["action"] for event in row.sanitized_events] == [
        "navigate",
        "click",
        "input_parameter",
        "input_parameter",
        "checkpoint",
        "scroll",
    ]
    for secret in (*SECRETS, "token=", "/inv"):
        assert secret not in stored
    assert row.status == "paused" and row.reason_code == "browser_ownership_lost"


async def _noop() -> None:
    return None


def _contexts(db):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def context():
        yield db
        await db.flush()

    return context


def _observer(roles: dict[str, str]):
    """A page that answers with structure only, the way the isolated-world observer does."""

    async def run(_function: str, mode: str, _x: float, _y: float) -> object:
        role = roles.get(mode)
        return {
            "origin": ORIGIN,
            "role": role,
            "path": [["button" if role == "button" else "input", 0], ["form", 0], ["body", 0]]
            if role
            else None,
            "auth": False,
        }

    return run
