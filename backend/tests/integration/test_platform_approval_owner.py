"""Who may let a platform call that always asks run: only the person its run acts for.

A platform call - `agenticos_accept_improvement`, `agenticos_publish_agent` - runs
with the platform authority of the person the run belongs to. The approvals queue
is the organization's, so an answer from anybody else holding `approvals:decide`
would let them make a change through that person that they could not make by hand.
These tests hold the rule at the two places a parked call can be released: the
decision and the continuation.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.approval import ApprovalGranted
from app.api import deps
from app.core.audit import set_impersonator
from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, RunSurface, ToolApproval
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.main import app
from app.schemas.conversation import HistoryProvenance
from app.services.agent_runner import AgentRunnerService, PausedRunState
from app.services.approvals import ApprovalService
from app.services.parked_runs import ParkedRunService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
_ACCEPT = "agenticos_accept_improvement"
_CALL_ID = "call-accept"


async def _member(db: AsyncSession, org: Organization, role: OrgRoleName) -> AuthContext:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role=role.value
        )
    )
    await db.flush()
    return AuthContext(user_id=user.id, organization_id=org.id, role=role.value)


async def _org(db: AsyncSession) -> Organization:
    founder = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(founder)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(org)
    await db.flush()
    return org


async def _parked(
    db: AsyncSession,
    org: Organization,
    owner: AuthContext,
    *,
    tool_id: str = _ACCEPT,
    always_asks: bool = True,
    status: ApprovalStatus = ApprovalStatus.PENDING,
) -> tuple[AgentRun, ToolApproval]:
    """`owner`'s run, parked on one call, as the Architect leaves it."""
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"architect-{uuid.uuid4().hex[:8]}",
        name="Architect",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    approval_id = uuid.uuid4()
    arguments = {"agent_id": str(uuid.uuid4()), "session_id": str(uuid.uuid4()), "publish": True}
    state = PausedRunState(
        messages=ModelMessagesTypeAdapter.dump_python(
            [
                ModelRequest(parts=[UserPromptPart("Accept the improvement and publish it")]),
                ModelResponse(parts=[ToolCallPart(tool_id, arguments, tool_call_id=_CALL_ID)]),
            ],
            mode="json",
        ),
        tool_call_ids={str(approval_id): _CALL_ID},
        history_provenance=HistoryProvenance(
            agent_id=agent.id,
            configuration_digest="a" * 64,
            mcp_destination_digest="b" * 64,
        ),
    )
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        user_id=owner.user_id,
        status=RunStatus.AWAITING_APPROVAL.value,
        surface=RunSurface.WEB.value,
        started_at=_NOW,
        paused_state=state.model_dump(mode="json"),
    )
    db.add(run)
    await db.flush()
    approval = ToolApproval(
        id=approval_id,
        organization_id=org.id,
        run_id=run.id,
        agent_id=agent.id,
        tool_id=tool_id,
        tool_args=arguments,
        status=status.value,
        always_asks=always_asks,
        created_at=_NOW,
    )
    db.add(approval)
    await db.flush()
    return run, approval


@contextmanager
def _impersonated_by(administrator: uuid.UUID) -> Iterator[None]:
    set_impersonator(administrator)
    try:
        yield
    finally:
        set_impersonator(None)


class TestApprovingAPlatformCallThatAlwaysAsks:
    async def test_another_approver_cannot_approve_a_call_made_for_someone_else(
        self, db: AsyncSession
    ):
        """An Operator holds `approvals:decide` and not the authority the call runs with."""
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        operator = await _member(db, org, OrgRoleName.OPERATOR)
        _run, approval = await _parked(db, org, builder)

        with pytest.raises(AuthorizationError):
            await ApprovalService(db).decide(operator, approval.id, approved=True)

        await db.refresh(approval)
        assert approval.status == ApprovalStatus.PENDING.value

    async def test_an_administrator_cannot_approve_it_either(self, db: AsyncSession):
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        admin = await _member(db, org, OrgRoleName.ADMIN)
        _run, approval = await _parked(db, org, builder)

        with pytest.raises(AuthorizationError):
            await ApprovalService(db).decide(admin, approval.id, approved=True)

    async def test_the_runs_own_person_approves_it(self, db: AsyncSession):
        org = await _org(db)
        admin = await _member(db, org, OrgRoleName.ADMIN)
        _run, approval = await _parked(db, org, admin)

        decided = await ApprovalService(db).decide(admin, approval.id, approved=True)

        assert decided.status == ApprovalStatus.APPROVED.value
        assert decided.decided_by_user_id == admin.user_id

    async def test_another_approver_may_still_reject_it(self, db: AsyncSession):
        """A rejection releases no authority, so the queue keeps it."""
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        operator = await _member(db, org, OrgRoleName.OPERATOR)
        _run, approval = await _parked(db, org, builder)

        decided = await ApprovalService(db).decide(operator, approval.id, approved=False)

        assert decided.status == ApprovalStatus.REJECTED.value

    async def test_the_runs_own_key_cannot_approve_it(self, db: AsyncSession):
        """The card asks for a person's fresh answer; a key is not one, even the person's own."""
        org = await _org(db)
        admin = await _member(db, org, OrgRoleName.ADMIN)
        _run, approval = await _parked(db, org, admin)

        with pytest.raises(AuthorizationError):
            await ApprovalService(db).decide(
                replace(admin, api_key_id=uuid.uuid4()), approval.id, approved=True
            )

    async def test_an_impersonated_session_cannot_approve_it(self, db: AsyncSession):
        org = await _org(db)
        admin = await _member(db, org, OrgRoleName.ADMIN)
        _run, approval = await _parked(db, org, admin)

        with _impersonated_by(uuid.uuid4()), pytest.raises(AuthorizationError):
            await ApprovalService(db).decide(admin, approval.id, approved=True)

    async def test_a_call_from_another_organization_is_not_found(self, db: AsyncSession):
        org = await _org(db)
        admin = await _member(db, org, OrgRoleName.ADMIN)
        _run, approval = await _parked(db, org, admin)
        elsewhere = await _member(db, await _org(db), OrgRoleName.OWNER)

        with pytest.raises(NotFoundError):
            await ApprovalService(db).decide(elsewhere, approval.id, approved=True)

    @pytest.mark.parametrize(
        ("tool_id", "always_asks"),
        [("github_merge_pull_request", True), ("agenticos_update_agent_draft", False)],
    )
    async def test_other_calls_keep_the_queues_own_rule(
        self, db: AsyncSession, tool_id: str, always_asks: bool
    ):
        """Only a platform call that always asks is reserved for the run's person."""
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        operator = await _member(db, org, OrgRoleName.OPERATOR)
        _run, approval = await _parked(db, org, builder, tool_id=tool_id, always_asks=always_asks)

        decided = await ApprovalService(db).decide(operator, approval.id, approved=True)

        assert decided.status == ApprovalStatus.APPROVED.value


class TestContinuingPastAnApprovedPlatformCall:
    async def test_another_approver_cannot_continue_the_run(self, db: AsyncSession):
        """Continuing would replay the call on the owner's authority, whoever approved it."""
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        operator = await _member(db, org, OrgRoleName.OPERATOR)
        run, _approval = await _parked(db, org, builder, status=ApprovalStatus.APPROVED)

        with pytest.raises(AuthorizationError):
            await AgentRunnerService(db).resume(operator, run.id)

        await db.refresh(run)
        assert run.status == RunStatus.AWAITING_APPROVAL.value

    async def test_the_runs_own_person_continues_with_the_approved_call(self, db: AsyncSession):
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        run, approval = await _parked(db, org, builder, status=ApprovalStatus.APPROVED)
        state = PausedRunState.model_validate(run.paused_state)

        decided, _plan = await AgentRunnerService(db)._decisions(builder, run=run, state=state)

        assert decided == {_CALL_ID: ApprovalGranted(tool_args=approval.tool_args)}

    async def test_the_runs_own_key_cannot_continue_it(self, db: AsyncSession):
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        run, _approval = await _parked(db, org, builder, status=ApprovalStatus.APPROVED)
        state = PausedRunState.model_validate(run.paused_state)

        with pytest.raises(AuthorizationError):
            await AgentRunnerService(db)._decisions(
                replace(builder, api_key_id=uuid.uuid4()), run=run, state=state
            )

    async def test_an_impersonated_session_cannot_continue_it(self, db: AsyncSession):
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        run, _approval = await _parked(db, org, builder, status=ApprovalStatus.APPROVED)

        with _impersonated_by(uuid.uuid4()), pytest.raises(AuthorizationError):
            await AgentRunnerService(db).resume(builder, run.id)

        await db.refresh(run)
        assert run.status == RunStatus.AWAITING_APPROVAL.value

    async def test_a_rejected_call_does_not_hold_the_run(self, db: AsyncSession):
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        operator = await _member(db, org, OrgRoleName.OPERATOR)
        run, _approval = await _parked(db, org, builder, status=ApprovalStatus.REJECTED)
        state = PausedRunState.model_validate(run.paused_state)

        decided, _plan = await AgentRunnerService(db)._decisions(operator, run=run, state=state)

        assert list(decided) == [_CALL_ID]


@asynccontextmanager
async def _client(db: AsyncSession, ctx: AuthContext) -> AsyncIterator[AsyncClient]:
    overrides = app.dependency_overrides.copy()
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_redis] = lambda: AsyncMock()
    app.dependency_overrides[deps.get_parked_run_service] = lambda: ParkedRunService(
        db, runner=AgentRunnerService(db), approvals=ApprovalService(db)
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides)


async def test_the_queue_refuses_another_persons_approval_with_403(db: AsyncSession):
    org = await _org(db)
    builder = await _member(db, org, OrgRoleName.BUILDER)
    operator = await _member(db, org, OrgRoleName.OPERATOR)
    _run, approval = await _parked(db, org, builder)

    async with _client(db, operator) as client:
        response = await client.post(
            f"{settings.API_V1_STR}/approvals/{approval.id}", json={"approved": True}
        )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "AUTHORIZATION_ERROR"


class TestTheRunsPersonWithoutApprovalsDecide:
    """A Builder or a Member holds no `approvals:decide`; their own platform call is
    still theirs to answer, and nothing else in the queue is."""

    async def test_they_approve_their_own_platform_call(self, db: AsyncSession):
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        _run, approval = await _parked(db, org, builder)

        decided = await ApprovalService(db).decide(builder, approval.id, approved=True)

        assert decided.status == ApprovalStatus.APPROVED.value

    async def test_they_reject_their_own_platform_call(self, db: AsyncSession):
        org = await _org(db)
        member = await _member(db, org, OrgRoleName.MEMBER)
        _run, approval = await _parked(db, org, member)

        decided = await ApprovalService(db).decide(member, approval.id, approved=False)

        assert decided.status == ApprovalStatus.REJECTED.value

    @pytest.mark.parametrize("approved", [True, False])
    async def test_they_cannot_decide_somebody_elses_platform_call(
        self, db: AsyncSession, approved: bool
    ):
        org = await _org(db)
        admin = await _member(db, org, OrgRoleName.ADMIN)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        _run, approval = await _parked(db, org, admin)

        with pytest.raises(AuthorizationError):
            await ApprovalService(db).decide(builder, approval.id, approved=approved)

    async def test_they_cannot_decide_their_own_call_of_another_tool(self, db: AsyncSession):
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        _run, approval = await _parked(
            db, org, builder, tool_id="github_merge_pull_request", always_asks=True
        )

        with pytest.raises(AuthorizationError):
            await ApprovalService(db).decide(builder, approval.id, approved=True)

    async def test_they_continue_their_own_run_past_their_platform_call(self, db: AsyncSession):
        """Past the permission check: the next refusal is the spec the fixture never published."""
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        run, _approval = await _parked(db, org, builder, status=ApprovalStatus.APPROVED)

        with pytest.raises(BadRequestError, match="no longer exists"):
            await _parked_runs(db).resume(builder, run.id)

    async def test_they_cannot_continue_somebody_elses_run(self, db: AsyncSession):
        org = await _org(db)
        admin = await _member(db, org, OrgRoleName.ADMIN)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        run, _approval = await _parked(db, org, admin, status=ApprovalStatus.APPROVED)

        with pytest.raises(AuthorizationError):
            await _parked_runs(db).resume(builder, run.id)

    async def test_they_cannot_continue_their_run_past_another_tool(self, db: AsyncSession):
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        run, _approval = await _parked(
            db,
            org,
            builder,
            tool_id="github_merge_pull_request",
            status=ApprovalStatus.APPROVED,
        )

        with pytest.raises(AuthorizationError):
            await _parked_runs(db).resume(builder, run.id)


class TestWhatEachReaderIsOffered:
    async def test_the_runs_person_reads_their_card_as_theirs_to_approve(self, db: AsyncSession):
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        run, _approval = await _parked(db, org, builder)

        [call] = await AgentRunnerService(db).parked_calls(builder, run, for_decision=True)

        assert (call.may_decide, call.may_approve) == (True, True)

    async def test_an_operator_reads_it_as_theirs_to_reject_only(self, db: AsyncSession):
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        operator = await _member(db, org, OrgRoleName.OPERATOR)
        run, _approval = await _parked(db, org, builder)

        [call] = await AgentRunnerService(db).parked_calls(operator, run)

        assert (call.may_decide, call.may_approve) == (True, False)

    async def test_somebody_elses_parked_run_is_not_read_without_the_permission(
        self, db: AsyncSession
    ):
        org = await _org(db)
        admin = await _member(db, org, OrgRoleName.ADMIN)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        run, _approval = await _parked(db, org, admin)

        with pytest.raises(AuthorizationError):
            await AgentRunnerService(db).parked_calls(builder, run, for_decision=True)

    async def test_the_queue_offers_an_operator_approval_only_where_it_counts(
        self, db: AsyncSession
    ):
        org = await _org(db)
        builder = await _member(db, org, OrgRoleName.BUILDER)
        operator = await _member(db, org, OrgRoleName.OPERATOR)
        _first, platform = await _parked(db, org, builder)
        _second, other = await _parked(db, org, builder, tool_id="send_email", always_asks=False)

        rows, _total = await ApprovalService(db).list_approvals(operator)

        offered = {row.id: row.may_approve for row in rows}
        assert offered == {platform.id: False, other.id: True}


def _parked_runs(db: AsyncSession) -> ParkedRunService:
    return ParkedRunService(db, runner=AgentRunnerService(db), approvals=ApprovalService(db))


async def test_the_runs_person_approves_through_the_queue_route_without_the_permission(
    db: AsyncSession,
):
    org = await _org(db)
    builder = await _member(db, org, OrgRoleName.BUILDER)
    _run, approval = await _parked(db, org, builder)

    async with _client(db, builder) as client:
        response = await client.post(
            f"{settings.API_V1_STR}/approvals/{approval.id}", json={"approved": True}
        )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == ApprovalStatus.APPROVED.value
