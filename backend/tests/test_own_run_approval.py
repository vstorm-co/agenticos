"""Tests for the own-run exception on the approval decide path.

A member or builder holds `approvals:decide` at `OWN` - their own runs only -
and the ownership is enforced per run in `may_decide_approval`, not by the
role. These tests pin the matrix: who may decide which run, from which
session, on which surface - and that the exception never widens into deciding
somebody else's run, a run a key started, or a run nobody can name.
"""

import uuid

import pytest

from app.core.audit import set_impersonator
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_run import AgentRun, RunSurface
from app.services.approvals import may_decide_approval, may_waive_own_run

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
