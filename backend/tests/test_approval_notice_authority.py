"""Who is handed an approval link, and who is told an approval expired.

The decision itself is `may_decide_approval`'s. These pin that the notification
paths - the decide link in the inbox and the email, the run the expiry notice
opens, and who the expiry notice goes to at all - read the same answer, so a
starter who was demoted, removed, or only ever a publisher's fallback identity is
never offered a link the decision would refuse.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.notification import Notification, NotificationEventType
from app.services.approval_authority import (
    may_decide_approval,
    may_follow_decision_link,
    starter_of,
    stored_starter_id,
)
from app.services.email.service import EmailKey
from app.services.notification_center import NotificationCenterService
from app.services.notification_delivery import NotificationDeliveryService
from app.services.notifications import NotificationService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_ORG = uuid.uuid4()
_STARTER = uuid.uuid4()
_OTHER = uuid.uuid4()
_MODULE = "app.services.notifications"


def _ctx(role: str, user_id: uuid.UUID | None = _STARTER, **overrides) -> AuthContext:
    return AuthContext(user_id=user_id, organization_id=_ORG, role=role, **overrides)


def _run(
    user_id: uuid.UUID | None = _STARTER,
    surface: str = RunSurface.WEB.value,
    *,
    publisher_fallback: bool = False,
) -> AgentRun:
    return AgentRun(
        id=uuid.uuid4(),
        organization_id=_ORG,
        user_id=user_id,
        surface=surface,
        initiated_by_publisher_fallback=publisher_fallback,
    )


class TestTheStoredStarter:
    def test_a_run_a_person_started_names_them(self):
        assert starter_of(_run()) == _STARTER

    @pytest.mark.parametrize(
        "run",
        [
            None,
            _run(None),
            _run(publisher_fallback=True),
            _run(surface=RunSurface.API.value),
            _run(surface=RunSurface.SCHEDULE.value),
        ],
    )
    def test_a_run_nobody_attended_names_nobody(self, run):
        assert starter_of(run) is None

    def test_a_stored_id_reads_back(self):
        assert stored_starter_id(str(_STARTER)) == _STARTER

    @pytest.mark.parametrize("stored", [None, "", "not-an-id"])
    def test_a_missing_or_malformed_id_reads_as_nobody(self, stored):
        assert stored_starter_id(stored) is None


class TestTheLinkFollowsTheDecision:
    @pytest.mark.parametrize("role", ["owner", "admin", "operator"])
    def test_a_privileged_decider_follows_any_link(self, role):
        assert may_follow_decision_link(_ctx(role, _OTHER), _STARTER) is True
        assert may_follow_decision_link(_ctx(role, _OTHER), None) is True

    @pytest.mark.parametrize("role", ["member", "builder"])
    def test_the_starter_follows_their_own_link(self, role):
        assert may_follow_decision_link(_ctx(role), _STARTER) is True

    def test_somebody_else_does_not(self):
        assert may_follow_decision_link(_ctx("member", _OTHER), _STARTER) is False

    def test_a_starter_demoted_to_viewer_does_not(self):
        assert may_follow_decision_link(_ctx("viewer"), _STARTER) is False

    def test_a_row_with_no_stored_starter_offers_no_link(self):
        assert may_follow_decision_link(_ctx("member"), None) is False

    def test_it_is_the_answer_the_decision_gives(self):
        for role in ("owner", "operator", "member", "builder", "viewer"):
            ctx = _ctx(role)
            for run in (_run(), _run(_OTHER), _run(publisher_fallback=True), None):
                assert may_follow_decision_link(ctx, starter_of(run)) is may_decide_approval(
                    ctx, run
                )


def _notification(run_user_id: str | None) -> Notification:
    context = {"agent_name": "Clerk"}
    if run_user_id is not None:
        context["run_user_id"] = run_user_id
    return Notification(
        id=uuid.uuid4(),
        organization_id=_ORG,
        event_type=NotificationEventType.APPROVAL_REQUESTED.value,
        summary="Clerk is waiting on your approval",
        context_url="/runs?tab=approvals",
        render_context=context,
    )


class TestTheInboxLink:
    async def _gate(self, ctx: AuthContext, run_user_id: str | None):
        return await NotificationCenterService(MagicMock()).gate_for(
            ctx, _notification(run_user_id), cache=MagicMock()
        )

    async def test_the_starter_keeps_the_link(self):
        gate = await self._gate(_ctx("member"), str(_STARTER))
        assert gate.visible and not gate.strip_context_url

    async def test_a_demoted_starter_reads_the_fact_without_the_link(self):
        gate = await self._gate(_ctx("viewer"), str(_STARTER))
        assert gate.visible and gate.strip_context_url
        assert gate.summary_override == "Clerk's run is held, waiting on an approval"

    async def test_a_publisher_standing_in_reads_the_fact_without_the_link(self):
        """The request stores no starter for a fallback run, so nobody holds it as theirs."""
        gate = await self._gate(_ctx("builder"), None)
        assert gate.strip_context_url

    async def test_an_operator_keeps_the_link(self):
        gate = await self._gate(_ctx("operator", _OTHER), str(_STARTER))
        assert not gate.strip_context_url


class TestTheEmailLink:
    def _key(self, ctx: AuthContext, run_user_id: str | None) -> tuple[EmailKey, dict]:
        notification = _notification(run_user_id)
        notification.render_context["approvals_url"] = "https://app.example/runs?tab=approvals"
        return NotificationDeliveryService(MagicMock())._render(notification, ctx=ctx)

    def test_the_starter_gets_the_decide_email(self):
        key, context = self._key(_ctx("member"), str(_STARTER))
        assert key is EmailKey.APPROVAL_REQUESTED
        assert "approvals_url" in context

    def test_a_demoted_starter_gets_the_notice_without_a_link(self):
        key, context = self._key(_ctx("viewer"), str(_STARTER))
        assert key is EmailKey.APPROVAL_PENDING
        assert "approvals_url" not in context

    def test_an_app_admin_keeps_the_decide_email(self):
        key, _ = self._key(_ctx("", _OTHER, is_app_admin=True), str(_STARTER))
        assert key is EmailKey.APPROVAL_REQUESTED

    def test_a_row_with_no_stored_starter_gets_no_link(self):
        key, context = self._key(_ctx("member"), None)
        assert key is EmailKey.APPROVAL_PENDING
        assert "approvals_url" not in context


class TestWhatTheRequestStores:
    async def _written(self, run: AgentRun) -> dict:
        service = NotificationService(MagicMock())
        service._center = MagicMock(write=AsyncMock())
        approval = MagicMock(id=uuid.uuid4(), tool_id="send_email", account=None)
        with (
            patch.object(service, "_audience_ids", new=AsyncMock(return_value={_STARTER})),
            patch.object(service, "_asked_by", new=AsyncMock(return_value=("", "Waiting"))),
            patch(f"{_MODULE}.agent_face", return_value={}),
        ):
            await service.approval_requested(
                run,
                agent=MagicMock(id=uuid.uuid4(), owner_user_id=None, name="Clerk"),
                spec=MagicMock(),
                approvals=[approval],
            )
            return service._center.write.await_args.kwargs["render_context"]

    async def test_a_run_a_person_started_stores_its_starter(self):
        context = await self._written(_run())
        assert context["run_user_id"] == str(_STARTER)

    async def test_a_publishers_fallback_run_stores_no_starter(self):
        context = await self._written(_run(publisher_fallback=True))
        assert "run_user_id" not in context

    async def test_a_run_nobody_started_stores_no_starter(self):
        context = await self._written(_run(None))
        assert "run_user_id" not in context


class TestTheExpiryNotice:
    async def _told(self, run: AgentRun, starter: AuthContext | None) -> AsyncMock:
        service = NotificationService(MagicMock())
        service._center = MagicMock(write=AsyncMock())
        with patch(f"{_MODULE}.member_context", new=AsyncMock(return_value=starter)):
            await service.approval_expired(
                run, agent=MagicMock(name="Clerk"), approvals=[MagicMock(tool_id="send_email")]
            )
        return service._center.write

    async def test_a_starter_who_can_still_decide_is_told(self):
        run = _run()
        write = await self._told(run, _ctx("member"))
        write.assert_awaited_once()
        assert write.await_args.kwargs["recipients"] == [_STARTER]
        assert write.await_args.kwargs["context_url"].startswith(f"/runs?run={run.id}")

    async def test_an_owner_who_started_their_run_is_told(self):
        write = await self._told(_run(), _ctx("owner"))
        write.assert_awaited_once()

    async def test_a_starter_demoted_to_viewer_hears_nothing(self):
        write = await self._told(_run(), _ctx("viewer"))
        write.assert_not_awaited()

    async def test_a_starter_no_longer_in_the_organization_hears_nothing(self):
        write = await self._told(_run(), None)
        write.assert_not_awaited()

    async def test_a_publisher_standing_in_hears_nothing(self):
        write = await self._told(_run(publisher_fallback=True), _ctx(OrgRoleName.BUILDER.value))
        write.assert_not_awaited()

    async def test_a_run_on_an_unattended_surface_tells_nobody(self):
        write = await self._told(_run(surface=RunSurface.API.value), _ctx("member"))
        write.assert_not_awaited()

    async def test_a_run_nobody_started_tells_nobody(self):
        write = await self._told(_run(None), _ctx("member"))
        write.assert_not_awaited()
