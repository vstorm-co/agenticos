"""Tests for the own-run exception on the approval decide path.

A member or builder holds `approvals:decide` at `OWN` - their own runs only -
and the ownership is enforced per run in `may_decide_approval`, not by the
role. These tests pin the matrix: who may decide which run, from which
session, on which surface - and that the exception never widens into deciding
somebody else's run, a run a key started, or a run nobody can name.
"""

import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.audit import set_impersonator
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunSurface
from app.services.approvals import ApprovalService, may_decide_approval, may_waive_own_run

pytestmark = pytest.mark.security

_OWNER = uuid.uuid4()
_MEMBER = uuid.uuid4()
_OTHER = uuid.uuid4()


def _ctx(role: str, user_id: uuid.UUID | None = _MEMBER, **overrides) -> AuthContext:
    return AuthContext(
        user_id=user_id,
        organization_id=uuid.uuid4(),
        role=role,
        **overrides,
    )


def _run(user_id: uuid.UUID | None = _MEMBER, surface: str = RunSurface.WEB.value) -> AgentRun:
    return AgentRun(user_id=user_id, surface=surface)


class TestPrivilegedDeciders:
    def test_owner_decides_another_persons_run(self):
        assert may_decide_approval(_ctx("owner", _OWNER), _run(_MEMBER)) is True

    def test_admin_decides_another_persons_run(self):
        assert may_decide_approval(_ctx("admin", _OWNER), _run(_MEMBER)) is True

    def test_operator_decides_another_persons_run(self):
        assert may_decide_approval(_ctx("operator", _OWNER), _run(_MEMBER)) is True

    def test_privileged_decider_needs_no_run(self):
        assert may_decide_approval(_ctx("owner", _OWNER), None) is True


class TestOwnRunException:
    def test_member_decides_their_own_web_run(self):
        assert may_decide_approval(_ctx("member"), _run(_MEMBER)) is True

    def test_builder_decides_their_own_web_run(self):
        assert may_decide_approval(_ctx("builder"), _run(_MEMBER)) is True

    def test_member_decides_their_own_channel_run(self):
        assert may_decide_approval(_ctx("member"), _run(_MEMBER, RunSurface.SLACK.value)) is True

    def test_member_cannot_decide_somebody_elses_run(self):
        assert may_decide_approval(_ctx("member"), _run(_OTHER)) is False

    def test_member_cannot_decide_an_api_run_they_started(self):
        assert may_decide_approval(_ctx("member"), _run(_MEMBER, RunSurface.API.value)) is False

    def test_member_cannot_decide_a_scheduled_run_they_started(self):
        assert (
            may_decide_approval(_ctx("member"), _run(_MEMBER, RunSurface.SCHEDULE.value)) is False
        )

    def test_member_cannot_decide_a_workflow_run_they_started(self):
        assert (
            may_decide_approval(_ctx("member"), _run(_MEMBER, RunSurface.WORKFLOW.value)) is False
        )

    def test_member_cannot_decide_a_run_nobody_can_name(self):
        assert may_decide_approval(_ctx("member"), None) is False


class TestSignedInSessionOnly:
    def test_an_api_key_cannot_decide_its_own_run(self):
        """A key deciding its own approval is the agent approving itself."""
        ctx = _ctx("member", api_key_id=uuid.uuid4(), key_scopes=frozenset({Perm.APPROVALS_DECIDE}))
        assert may_decide_approval(ctx, _run(_MEMBER)) is False

    def test_an_api_key_without_the_permission_cannot_decide_any_run(self):
        """A key narrowed away from `approvals:decide` holds nothing, even for its issuer's run."""
        ctx = _ctx("member", api_key_id=uuid.uuid4(), key_scopes=frozenset({Perm.AGENTS_VIEW}))
        assert may_decide_approval(ctx, _run(_MEMBER)) is False
        assert may_decide_approval(ctx, _run(_OTHER)) is False

    def test_an_all_scoped_key_still_decides_another_persons_run(self):
        """The privileged path is unchanged: an owner's decide-scoped key reaches any run."""
        ctx = _ctx("owner", api_key_id=uuid.uuid4(), key_scopes=frozenset({Perm.APPROVALS_DECIDE}))
        assert may_decide_approval(ctx, _run(_OTHER)) is True

    def test_a_publisher_fallback_cannot_decide(self):
        ctx = _ctx("member", subject_is_publisher_fallback=True)
        assert may_decide_approval(ctx, _run(_MEMBER)) is False

    def test_a_routine_cannot_decide(self):
        ctx = _ctx("member", routine_id=uuid.uuid4())
        assert may_decide_approval(ctx, _run(_MEMBER)) is False

    def test_a_fired_trigger_cannot_decide_as_its_creator(self):
        ctx = _ctx("member", fired_as_creator="schedule")
        assert may_decide_approval(ctx, _run(_MEMBER)) is False

    def test_an_impersonated_session_cannot_decide(self):
        set_impersonator(uuid.uuid4())
        try:
            assert may_decide_approval(_ctx("member"), _run(_MEMBER)) is False
        finally:
            set_impersonator(None)

    def test_a_subject_less_context_cannot_decide(self):
        assert may_decide_approval(_ctx("member", None), _run(None)) is False

    def test_a_viewer_cannot_decide_even_a_run_they_started(self):
        """The permission is the authority; ownership is only its scope.

        A member demoted to viewer after starting a run loses the decision
        with the permission, rather than keeping it on ownership alone.
        """
        assert may_decide_approval(_ctx("viewer"), _run(_MEMBER)) is False


class TestMayWaiveOwnRun:
    def test_member_may_waive_their_own_runs(self):
        assert may_waive_own_run(_ctx("member")) is True

    def test_owner_may_waive(self):
        assert may_waive_own_run(_ctx("owner", _OWNER)) is True

    def test_viewer_may_not_waive(self):
        assert may_waive_own_run(_ctx("viewer")) is False

    def test_a_key_may_not_waive(self):
        ctx = _ctx("member", api_key_id=uuid.uuid4(), key_scopes=frozenset({Perm.APPROVALS_DECIDE}))
        assert may_waive_own_run(ctx) is False

    def test_an_impersonated_session_may_not_waive(self):
        set_impersonator(uuid.uuid4())
        try:
            assert may_waive_own_run(_ctx("member")) is False
        finally:
            set_impersonator(None)


class TestDecideEnforcesIt:
    """`ApprovalService.decide` is the one enforcement point: the route has no gate."""

    @staticmethod
    @contextmanager
    def _repositories(run: AgentRun, *, status: str = ApprovalStatus.PENDING.value):
        approval = MagicMock(
            id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            tool_id="send_email",
            tool_args={},
            status=status,
            always_asks=False,
            subagent_name=None,
        )
        with (
            patch(
                "app.services.approvals.agent_run_repo.get_approval",
                new=AsyncMock(return_value=approval),
            ),
            patch("app.services.approvals.agent_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(
                "app.services.approvals.agent_run_repo.decide_approval",
                new=AsyncMock(return_value=approval),
            ) as decide,
            patch(
                "app.services.approvals.voice_call_repo.is_live_run",
                new=AsyncMock(return_value=False),
            ),
            patch("app.services.approvals.record_audit", new=AsyncMock()),
            patch.object(ApprovalService, "_settle_outcomes", new=AsyncMock()),
        ):
            yield approval, decide

    @staticmethod
    def _service() -> ApprovalService:
        return ApprovalService(MagicMock(flush=AsyncMock(), refresh=AsyncMock(), add=MagicMock()))

    @pytest.mark.anyio
    async def test_a_member_decides_their_own_run(self):
        ctx = _ctx("member")
        with self._repositories(_run(_MEMBER)) as (approval, decide):
            await self._service().decide(ctx, approval.id, approved=True)

        assert decide.await_args.kwargs["status"] == ApprovalStatus.APPROVED.value

    @pytest.mark.anyio
    async def test_a_member_cannot_decide_somebody_elses_run(self):
        ctx = _ctx("member")
        with (
            self._repositories(_run(_OTHER)) as (approval, decide),
            pytest.raises(AuthorizationError),
        ):
            await self._service().decide(ctx, approval.id, approved=True)

        decide.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_key_cannot_decide_its_issuers_run(self):
        ctx = _ctx("member", api_key_id=uuid.uuid4(), key_scopes=frozenset({Perm.APPROVALS_DECIDE}))
        with (
            self._repositories(_run(_MEMBER)) as (approval, decide),
            pytest.raises(AuthorizationError),
        ):
            await self._service().decide(ctx, approval.id, approved=True)

        decide.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_key_without_the_permission_cannot_decide_any_run(self):
        ctx = _ctx("owner", api_key_id=uuid.uuid4(), key_scopes=frozenset({Perm.AGENTS_VIEW}))
        with (
            self._repositories(_run(_OTHER)) as (approval, decide),
            pytest.raises(AuthorizationError),
        ):
            await self._service().decide(ctx, approval.id, approved=True)

        decide.assert_not_awaited()

    @pytest.mark.anyio
    async def test_an_owners_decide_scoped_key_decides_another_persons_run(self):
        ctx = _ctx("owner", api_key_id=uuid.uuid4(), key_scopes=frozenset({Perm.APPROVALS_DECIDE}))
        with self._repositories(_run(_OTHER)) as (approval, decide):
            await self._service().decide(ctx, approval.id, approved=False)

        assert decide.await_args.kwargs["status"] == ApprovalStatus.REJECTED.value

    @pytest.mark.anyio
    async def test_a_refused_caller_learns_nothing_about_the_approvals_state(self):
        """Refused before the already-decided check, so the answer is the same either way."""
        ctx = _ctx("member")
        with (
            self._repositories(_run(_OTHER), status=ApprovalStatus.APPROVED.value) as (
                approval,
                _,
            ),
            pytest.raises(AuthorizationError),
        ):
            await self._service().decide(ctx, approval.id, approved=True)
