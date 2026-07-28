"""Tests for run notifications - the emails about runs nobody was watching.

What is worth guarding here is not the wording. It is who hears about a run
that stopped, that the run itself never fails because of the email, and that a
weekly report about nothing is never sent.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.email.service import EmailKey
from app.services.notifications import NotificationService

MODULE = "app.services.notifications"


def _run(*, org_id=None, user_id=None, cost="1.50"):
    run = MagicMock()
    run.id = uuid.uuid4()
    run.organization_id = org_id or uuid.uuid4()
    run.user_id = user_id
    run.cost_usd = Decimal(cost)
    return run


def _agent(*, owner_user_id=None, name="Support"):
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.name = name
    agent.owner_user_id = owner_user_id
    return agent


class _Sent:
    """Records what `_send` was asked to deliver, without a mail server."""

    def __init__(self) -> None:
        self.calls: list[tuple[EmailKey, list[str], dict[str, str]]] = []

    def __call__(self, key, recipients, context) -> None:
        self.calls.append((key, recipients, context))


@pytest.fixture
def sent(monkeypatch) -> _Sent:
    recorder = _Sent()
    monkeypatch.setattr(NotificationService, "_send", recorder)
    return recorder


class TestBudgetExceeded:
    @pytest.mark.anyio
    async def test_the_owner_and_the_admins_are_both_told(self, sent):
        """The builder fixes the agent; the people paying decide if the cap was too low."""
        owner_id = uuid.uuid4()
        with (
            patch(
                f"{MODULE}.member_repo.list_emails_by_role",
                new=AsyncMock(return_value=["admin@acme.test"]),
            ),
            patch(
                f"{MODULE}.user_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(email="builder@acme.test", is_active=True)),
            ),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(), agent=_agent(owner_user_id=owner_id), reason="Monthly cap reached"
            )

        key, recipients, _ = sent.calls[0]
        assert key is EmailKey.BUDGET_EXCEEDED
        assert recipients == ["admin@acme.test", "builder@acme.test"]

    @pytest.mark.anyio
    async def test_a_deactivated_owner_is_not_mailed(self, sent):
        """Deactivation is how an account is taken away; mail is part of what it takes."""
        with (
            patch(
                f"{MODULE}.member_repo.list_emails_by_role",
                new=AsyncMock(return_value=["admin@acme.test"]),
            ),
            patch(
                f"{MODULE}.user_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(email="gone@acme.test", is_active=False)),
            ),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(), agent=_agent(owner_user_id=uuid.uuid4()), reason="cap"
            )

        _, recipients, _ = sent.calls[0]
        assert recipients == ["admin@acme.test"]

    @pytest.mark.anyio
    async def test_an_address_that_is_both_owner_and_admin_is_mailed_once(self, sent):
        """The common case in a small organization - and two identical emails read as a bug."""
        with (
            patch(
                f"{MODULE}.member_repo.list_emails_by_role",
                new=AsyncMock(return_value=["boss@acme.test"]),
            ),
            patch(
                f"{MODULE}.user_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(email="boss@acme.test", is_active=True)),
            ),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(), agent=_agent(owner_user_id=uuid.uuid4()), reason="cap"
            )

        _, recipients, _ = sent.calls[0]
        assert recipients == ["boss@acme.test"]

    @pytest.mark.anyio
    async def test_nothing_is_sent_when_there_is_nobody_to_send_to(self, sent):
        """A deleted owner and an organization with no admins is not an error to raise."""
        with patch(f"{MODULE}.member_repo.list_emails_by_role", new=AsyncMock(return_value=[])):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(), agent=_agent(), reason="cap"
            )

        assert sent.calls == []


class TestApprovalRequested:
    @pytest.mark.anyio
    async def test_the_person_who_started_the_run_is_the_one_told(self, sent):
        user_id = uuid.uuid4()
        with patch(
            f"{MODULE}.member_repo.get_emails_for_users",
            new=AsyncMock(return_value={user_id: "asker@acme.test"}),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=user_id), agent=_agent(), tools=["send_email"]
            )

        key, recipients, context = sent.calls[0]
        assert key is EmailKey.APPROVAL_REQUESTED
        assert recipients == ["asker@acme.test"]
        assert context["tools"] == "send_email"

    @pytest.mark.anyio
    async def test_a_run_with_no_user_escalates_instead_of_going_nowhere(self, sent):
        """A scheduled or channel run has nobody attached, and a parked run nobody
        is told about sits parked until somebody happens to look."""
        with (
            patch(
                f"{MODULE}.member_repo.list_emails_by_role",
                new=AsyncMock(return_value=["admin@acme.test"]),
            ),
            patch(f"{MODULE}.user_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=None), agent=_agent(), tools=[]
            )

        _, recipients, context = sent.calls[0]
        assert recipients == ["admin@acme.test"]
        assert context["tools"] == "a tool call"

    @pytest.mark.anyio
    async def test_a_parked_run_with_nobody_at_all_is_not_an_error(self, sent):
        """Every recipient gone is a state to survive, not to raise inside a `finally`."""
        with (
            patch(f"{MODULE}.member_repo.get_emails_for_users", new=AsyncMock(return_value={})),
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=AsyncMock(return_value=[])),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=uuid.uuid4()), agent=_agent(), tools=["x"]
            )

        assert sent.calls == []


class TestUsageReport:
    @pytest.mark.anyio
    async def test_an_organization_that_ran_nothing_gets_no_email(self, sent):
        """A weekly '0 runs, $0.00' is what teaches people to filter the sender."""
        with patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=[])):
            reported = await NotificationService(MagicMock()).usage_report(
                uuid.uuid4(), period="weekly"
            )

        assert reported is False
        assert sent.calls == []

    @pytest.mark.anyio
    async def test_the_total_sums_every_row_not_just_the_biggest(self, sent):
        """The breakdown is per agent *and* model, so one agent appears on several rows."""
        rows = [
            (uuid.uuid4(), "gpt-5", Decimal("2.00"), 3),
            (uuid.uuid4(), "claude", Decimal("0.50"), 1),
        ]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(
                f"{MODULE}.member_repo.list_emails_by_role",
                new=AsyncMock(return_value=["admin@acme.test"]),
            ),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            reported = await NotificationService(MagicMock()).usage_report(
                uuid.uuid4(), period="monthly"
            )

        assert reported is True
        _, _, context = sent.calls[0]
        assert context["total"] == "2.50"
        assert context["runs"] == "4"
        assert context["period"] == "month"

    @pytest.mark.anyio
    async def test_a_report_with_nobody_to_read_it_is_not_sent(self, sent):
        """An organization whose last admin left still has runs; it has no reader."""
        rows = [(uuid.uuid4(), "gpt-5", Decimal("1.00"), 1)]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=AsyncMock(return_value=[])),
        ):
            reported = await NotificationService(MagicMock()).usage_report(
                uuid.uuid4(), period="weekly"
            )

        assert reported is False
        assert sent.calls == []


class TestDelivery:
    @pytest.mark.anyio
    async def test_a_send_is_handed_to_the_background(self, monkeypatch):
        """The caller is a run's `finally` block: it must not wait on a mail server."""
        spawned: list[str] = []

        def fake_spawn(coro, *, name):
            coro.close()
            spawned.append(name)

        monkeypatch.setattr(f"{MODULE}.spawn", fake_spawn)
        NotificationService(MagicMock())._send(
            EmailKey.BUDGET_EXCEEDED, ["a@acme.test", "b@acme.test"], {}
        )

        assert spawned == ["email:budget_exceeded:a@acme.test", "email:budget_exceeded:b@acme.test"]

    @pytest.mark.anyio
    async def test_a_mail_server_that_is_down_does_not_raise(self):
        """Nothing is left to raise into - the run it was reporting on has ended."""
        from app.services.notifications import _deliver

        with patch(
            f"{MODULE}.get_email_service",
            return_value=MagicMock(send=AsyncMock(side_effect=RuntimeError("smtp down"))),
        ):
            await _deliver(key=EmailKey.USAGE_REPORT, to="a@acme.test", context={})

    @pytest.mark.anyio
    async def test_a_send_that_works_reaches_the_email_service(self):
        service = MagicMock(send=AsyncMock())
        from app.services.notifications import _deliver

        with patch(f"{MODULE}.get_email_service", return_value=service):
            await _deliver(key=EmailKey.USAGE_REPORT, to="a@acme.test", context={"x": "1"})

        assert service.send.call_args.kwargs["to"] == "a@acme.test"


def test_the_service_factory_returns_one_bound_to_the_session():
    from app.services.notifications import get_notification_service

    db = MagicMock()
    assert get_notification_service(db).db is db
