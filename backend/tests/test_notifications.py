"""Tests for run notifications - the emails about runs nobody was watching.

What is worth guarding here is not the wording. It is who hears about a run that
stopped, that the run itself never fails because of the email, and that a weekly
report about nothing is never sent.

Two resolvers do all the work, and the split between them is a security boundary:

- `member_repo.list_emails_by_role` + `list_app_admin_emails` answer the `admins`
  audience, and are deliberately wider than one organization.
- `member_repo.list_emails_for_members` answers everything keyed on a *person* -
  the agent's owner, the run's initiator, and the ids an author typed into
  `AlertSpec.user_ids`. It is membership-scoped.

These are unit tests, so they pin the **wiring**: which organization and which ids
reach the scoped resolver, and that nothing keyed on a person bypasses it. Whether
the query itself is really scoped, and really honours `is_active` and the opt-out
column, is SQL - see `tests/integration/test_notification_recipients.py`.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.budget import BudgetScope
from app.agents.spec import AgentSpec, AlertAudience, AlertSpec, NotificationSpec
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


def _agent(*, owner_user_id=None, name="Support", org_id=None):
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.name = name
    agent.owner_user_id = owner_user_id
    agent.organization_id = org_id or uuid.uuid4()
    return agent


def _spec(**alerts) -> AgentSpec:
    """A spec whose notification block is whatever the test is about.

    Defaulted, so a test that does not mention an alert exercises the shipped
    default for it rather than a value the test invented.
    """
    return AgentSpec(name="Support", notifications=NotificationSpec(**alerts))


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


@pytest.fixture(autouse=True)
def _no_app_admins():
    """No app admins unless a test says otherwise.

    Autouse because every audience that includes `admins` asks for them, and an
    unpatched `MagicMock` session would answer with a mock that is neither a list
    of addresses nor an error anybody could read.
    """
    with patch(f"{MODULE}.member_repo.list_app_admin_emails", new=AsyncMock(return_value=[])):
        yield


def _roles(*addresses: str) -> AsyncMock:
    return AsyncMock(return_value=list(addresses))


def _members(*addresses: str) -> AsyncMock:
    return AsyncMock(return_value=list(addresses))


def _bill(amount: str) -> AsyncMock:
    """`app.services.spend.organization_spend_since` - runs plus ingestion.

    Deliberately not the sum of whatever breakdown a test also passes: the point of
    reading it from there is that the two are different numbers.
    """
    return AsyncMock(return_value=Decimal(amount))


def _window_days(since: datetime) -> int:
    """How wide a window a call asked for, to the nearest day.

    Rounded because the boundary is `datetime.now(UTC)` inside the call and cannot
    be reproduced here; a report that covered the wrong period would be out by
    days, not by microseconds.
    """
    return round((datetime.now(UTC) - since).total_seconds() / 86_400)


class TestBudgetExceeded:
    @pytest.mark.anyio
    async def test_the_owner_and_the_admins_are_both_told(self, sent):
        """The builder fixes the agent; the people paying decide if the cap was too low."""
        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles("admin@acme.test")),
            patch(
                f"{MODULE}.member_repo.list_emails_for_members",
                new=_members("builder@acme.test"),
            ),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(),
                agent=_agent(owner_user_id=uuid.uuid4()),
                spec=_spec(),
                reason="Monthly cap reached",
                scope=BudgetScope.AGENT,
            )

        key, recipients, _ = sent.calls[0]
        assert key is EmailKey.BUDGET_EXCEEDED
        assert recipients == ["admin@acme.test", "builder@acme.test"]

    @pytest.mark.anyio
    async def test_an_address_reached_two_ways_is_mailed_once(self, sent):
        """The common case in a small organization - and two identical emails read as a bug."""
        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles("boss@acme.test")),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=_members("boss@acme.test")),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(),
                agent=_agent(owner_user_id=uuid.uuid4()),
                spec=_spec(),
                reason="cap",
                scope=BudgetScope.AGENT,
            )

        _, recipients, _ = sent.calls[0]
        assert recipients == ["boss@acme.test"]

    @pytest.mark.anyio
    async def test_nothing_is_sent_when_there_is_nobody_to_send_to(self, sent):
        """A deleted owner and an organization with no admins is not an error to raise."""
        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=_members()),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(), agent=_agent(), spec=_spec(), reason="cap", scope=BudgetScope.AGENT
            )

        assert sent.calls == []

    @pytest.mark.anyio
    async def test_an_agent_can_silence_its_own_budget_alert(self, sent):
        """The whole reason this moved into the spec: one noisy agent should be
        quietenable without going deaf to the others."""
        with patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles("admin@acme.test")):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(),
                agent=_agent(),
                spec=_spec(budget=AlertSpec(enabled=False)),
                reason="cap",
                scope=BudgetScope.AGENT,
            )

        assert sent.calls == []

    @pytest.mark.anyio
    async def test_the_organizations_cap_ignores_what_the_agent_asked_for(self, sent):
        """A spec cannot silence a limit its author cannot raise.

        The organization's cap has just stopped this run and is about to stop
        every other one in the organization.
        """
        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles("admin@acme.test")),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(),
                agent=_agent(),
                spec=_spec(budget=AlertSpec(enabled=False)),
                reason="cap",
                scope=BudgetScope.ORGANIZATION,
            )

        _, recipients, _ = sent.calls[0]
        assert recipients == ["admin@acme.test"]

    @pytest.mark.anyio
    async def test_the_deployments_app_admins_hear_about_the_organizations_cap(self, sent):
        """An app admin holds no membership row, so a query scoped to one misses
        exactly the person who administers the deployment."""
        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles()),
            patch(
                f"{MODULE}.member_repo.list_app_admin_emails",
                new=AsyncMock(return_value=["root@platform.test"]),
            ),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(),
                agent=_agent(),
                spec=_spec(),
                reason="cap",
                scope=BudgetScope.ORGANIZATION,
            )

        _, recipients, _ = sent.calls[0]
        assert recipients == ["root@platform.test"]


class TestEveryPersonIsResolvedInsideTheOrganization:
    """The tenant boundary on alert recipients.

    `AlertSpec.user_ids` is written by whoever may edit the agent. Resolved
    globally, an author could name a user id belonging to another organization and
    have them mailed this organization's name, the agent's name, the reason a run
    stopped and what it spent - all of which go into the email context. So every
    audience keyed on a person goes through one membership-scoped resolver, and
    these tests are about the argument it is handed.
    """

    @pytest.mark.anyio
    async def test_chosen_ids_are_resolved_only_among_this_organizations_members(self, sent):
        chosen = [uuid.uuid4(), uuid.uuid4()]
        run = _run()
        scoped = _members("rota@acme.test")

        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=scoped),
        ):
            await NotificationService(MagicMock()).approval_requested(
                run,
                agent=_agent(),
                spec=_spec(approvals=AlertSpec(to=[AlertAudience.CHOSEN], user_ids=chosen)),
                tools=["send_email"],
            )

        kwargs = scoped.await_args.kwargs
        # The run's organization, not the agent's and not none: this is the tenant
        # the alert is about, and it is what bounds who may be mailed.
        assert kwargs["organization_id"] == run.organization_id
        assert kwargs["user_ids"] == chosen
        assert kwargs["preference"] == "notify_approval_requests"

    @pytest.mark.anyio
    async def test_a_foreign_id_contributes_no_recipient(self, sent):
        """The regression. The scoped resolver answers with nothing for an id that
        is not a member, and nothing is what must then be mailed - rather than the
        address being resolved some other way."""
        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=_members()),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(),
                agent=_agent(),
                spec=_spec(approvals=AlertSpec(to=[AlertAudience.CHOSEN], user_ids=[uuid.uuid4()])),
                tools=["x"],
            )

        assert sent.calls == []

    @pytest.mark.anyio
    async def test_the_owner_goes_through_the_scoped_resolver_too(self, sent):
        """Not because an agent's owner is likely to be foreign, but because one
        resolver for all three cannot be right for two of them and wrong for the
        third."""
        owner = uuid.uuid4()
        scoped = _members("owner@acme.test")

        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=scoped),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(),
                agent=_agent(owner_user_id=owner),
                spec=_spec(budget=AlertSpec(to=[AlertAudience.OWNER])),
                reason="cap",
                scope=BudgetScope.AGENT,
            )

        assert scoped.await_args.kwargs["user_ids"] == [owner]

    @pytest.mark.anyio
    async def test_the_initiator_goes_through_the_scoped_resolver_too(self, sent):
        initiator = uuid.uuid4()
        scoped = _members("asker@acme.test")

        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=scoped),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=initiator),
                agent=_agent(),
                spec=_spec(approvals=AlertSpec(to=[AlertAudience.INITIATOR])),
                tools=["x"],
            )

        assert scoped.await_args.kwargs["user_ids"] == [initiator]

    @pytest.mark.anyio
    async def test_an_audience_naming_nobody_costs_no_query(self, sent):
        """An `admins`-only alert must not ask the scoped resolver about an empty
        list - and, more to the point, must not ask it about `None`."""
        scoped = _members()

        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles("admin@acme.test")),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=scoped),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(),
                agent=_agent(owner_user_id=uuid.uuid4()),
                spec=_spec(budget=AlertSpec(to=[AlertAudience.ADMINS])),
                reason="cap",
                scope=BudgetScope.AGENT,
            )

        scoped.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_run_with_no_initiator_asks_about_nobody(self, sent):
        """A scheduled run has no user. Passing `None` into an `IN (...)` would be
        a query about a null id rather than about nobody."""
        scoped = _members()

        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles("admin@acme.test")),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=scoped),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=None),
                agent=_agent(owner_user_id=None),
                spec=_spec(),
                tools=[],
            )

        scoped.assert_not_awaited()


class TestApprovalRequested:
    @pytest.mark.anyio
    async def test_the_person_who_started_the_run_is_told(self, sent):
        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=_members("asker@acme.test")),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=uuid.uuid4()),
                agent=_agent(),
                spec=_spec(),
                tools=["send_email"],
            )

        key, recipients, context = sent.calls[0]
        assert key is EmailKey.APPROVAL_REQUESTED
        assert recipients == ["asker@acme.test"]
        assert context["tools"] == "send_email"

    @pytest.mark.anyio
    async def test_a_run_with_no_user_still_reaches_the_admins(self, sent):
        """A scheduled or channel run has nobody attached, and a parked run nobody
        is told about sits parked until somebody happens to look."""
        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles("admin@acme.test")),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=_members()),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=None), agent=_agent(), spec=_spec(), tools=[]
            )

        _, recipients, context = sent.calls[0]
        assert recipients == ["admin@acme.test"]
        assert context["tools"] == "a tool call"

    @pytest.mark.anyio
    async def test_a_parked_run_with_nobody_at_all_is_not_an_error(self, sent):
        """Every recipient gone is a state to survive, not to raise inside a `finally`."""
        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=_members()),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=uuid.uuid4()), agent=_agent(), spec=_spec(), tools=["x"]
            )

        assert sent.calls == []

    @pytest.mark.anyio
    async def test_an_agent_can_send_approvals_only_to_whoever_asked(self, sent):
        """The ticket's other case: an agent whose approvals are nobody's business
        but the asker's. Expressible now, and it was not before."""
        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=AsyncMock()) as roles,
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=_members("asker@acme.test")),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=uuid.uuid4()),
                agent=_agent(),
                spec=_spec(approvals=AlertSpec(to=[AlertAudience.INITIATOR])),
                tools=["send_email"],
            )

        _, recipients, _ = sent.calls[0]
        assert recipients == ["asker@acme.test"]
        # Not merely absent from the result - never asked for. An audience that
        # is not named must not cost a query.
        roles.assert_not_awaited()


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
    async def test_the_run_count_sums_every_row_and_the_agents_are_counted_once(self, sent):
        """The breakdown is per agent *and* model, so one agent that was repointed
        mid-window appears on two rows - four runs, one agent, not two."""
        one_agent = uuid.uuid4()
        rows = [
            (one_agent, "gpt-5", Decimal("2.00"), 3),
            (one_agent, "claude", Decimal("0.50"), 1),
        ]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.organization_spend_since", new=_bill("2.50")),
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles("admin@acme.test")),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            reported = await NotificationService(MagicMock()).usage_report(
                uuid.uuid4(), period="monthly"
            )

        assert reported is True
        _, _, context = sent.calls[0]
        assert context["runs"] == "4"
        assert context["agents"] == "1"
        assert context["period"] == "month"

    @pytest.mark.anyio
    async def test_the_total_is_the_bill_and_not_the_sum_of_the_breakdown(self, sent):
        """This email said $1.40 for $1.00 of work.

        Summing the breakdown got the arithmetic wrong in both directions at once:
        a delegated run appeared twice, because a delegate's tokens are already
        inside its parent's `cost_usd`, and ingestion's embedding spend appeared not
        at all. `app.services.spend` is the one place that question is answered, so
        this figure now agrees with the budget the platform enforces.
        """
        rows = [(uuid.uuid4(), "gpt-5", Decimal("1.00"), 1)]
        bill = _bill("1.12")
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.organization_spend_since", new=bill),
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles("admin@acme.test")),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).usage_report(uuid.uuid4(), period="weekly")

        _, _, context = sent.calls[0]
        assert context["total"] == "1.12"
        # And over the window the email says it covers, not the calendar month a
        # cap is metered on - "over the past week" has to mean the past week.
        assert _window_days(bill.await_args.args[2]) == 7

    @pytest.mark.anyio
    async def test_a_report_with_nobody_to_read_it_is_not_sent(self, sent):
        """An organization whose last admin left still has runs; it has no reader."""
        rows = [(uuid.uuid4(), "gpt-5", Decimal("1.00"), 1)]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles()),
        ):
            reported = await NotificationService(MagicMock()).usage_report(
                uuid.uuid4(), period="weekly"
            )

        assert reported is False
        assert sent.calls == []


class TestPerAgentUsageReport:
    """The opt-in report about one agent, rather than the estate."""

    @pytest.mark.anyio
    async def test_an_agent_that_did_not_ask_gets_no_report(self, sent):
        """Off by default: a weekly email per agent for forty agents is forty
        emails nobody reads, which is how the one that mattered gets filtered."""
        reported = await NotificationService(MagicMock()).agent_usage_report(
            _agent(), _spec(), period="weekly"
        )

        assert reported is False
        assert sent.calls == []

    @pytest.mark.anyio
    async def test_the_report_covers_this_agent_and_not_its_neighbours(self, sent):
        """The breakdown is the organization's, so the wrong filter here would
        report the estate's spend as one agent's."""
        agent = _agent()
        rows = [
            (agent.id, "gpt-5", Decimal("2.00"), 3),
            (uuid.uuid4(), "gpt-5", Decimal("90.00"), 100),
        ]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles("admin@acme.test")),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=_members()),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            reported = await NotificationService(MagicMock()).agent_usage_report(
                agent, _spec(usage=AlertSpec(enabled=True)), period="weekly"
            )

        assert reported is True
        _, _, context = sent.calls[0]
        assert context["total"] == "2.00"
        assert context["runs"] == "3"
        assert context["agents"] == agent.name

    @pytest.mark.anyio
    async def test_it_counts_the_runs_this_agent_was_delegated_into(self, sent):
        """The mirror image of the organization's report, and the one question that
        wants the child rows.

        An agent used as somebody's delegate spends money in runs that are recorded
        only as its own delegated rows - so a report that excluded them would tell
        the person answerable for that agent it had cost nothing.
        """
        agent = _agent()
        rows = [(agent.id, "claude", Decimal("0.40"), 1)]
        breakdown = AsyncMock(return_value=rows)
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=breakdown),
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles("admin@acme.test")),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=_members()),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).agent_usage_report(
                agent, _spec(usage=AlertSpec(enabled=True)), period="weekly"
            )

        assert breakdown.await_args.kwargs["include_delegations"] is True
        _, _, context = sent.calls[0]
        assert context["total"] == "0.40"

    @pytest.mark.anyio
    async def test_a_per_agent_report_is_scoped_to_the_agents_own_organization(self, sent):
        """It has no run to take a tenant from, so the agent's own column is what
        bounds who may be mailed."""
        agent = _agent(owner_user_id=uuid.uuid4())
        rows = [(agent.id, "gpt-5", Decimal("1.00"), 1)]
        scoped = _members("owner@acme.test")

        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=scoped),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).agent_usage_report(
                agent,
                _spec(usage=AlertSpec(enabled=True, to=[AlertAudience.OWNER])),
                period="weekly",
            )

        assert scoped.await_args.kwargs["organization_id"] == agent.organization_id

    @pytest.mark.anyio
    async def test_an_agent_that_ran_nothing_is_silent_even_when_asked(self, sent):
        agent = _agent()
        rows = [(uuid.uuid4(), "gpt-5", Decimal("5.00"), 2)]
        with patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)):
            reported = await NotificationService(MagicMock()).agent_usage_report(
                agent, _spec(usage=AlertSpec(enabled=True)), period="weekly"
            )

        assert reported is False
        assert sent.calls == []

    @pytest.mark.anyio
    async def test_a_report_nobody_is_left_to_read_is_not_sent(self, sent):
        agent = _agent()
        rows = [(agent.id, "gpt-5", Decimal("1.00"), 1)]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=_members()),
        ):
            reported = await NotificationService(MagicMock()).agent_usage_report(
                agent, _spec(usage=AlertSpec(enabled=True)), period="weekly"
            )

        assert reported is False
        assert sent.calls == []


class TestPreferences:
    """The opt-outs from `/settings/notifications`, honoured at the send site.

    Both resolvers filter in SQL, so what a unit test can pin is the contract:
    which preference each kind of email asks for. Passing the wrong column would
    honour one opt-out by silencing a different email, and every address would
    still look plausible.
    """

    @pytest.mark.anyio
    async def test_each_email_kind_asks_the_role_query_for_its_own_preference(self, sent):
        roles = _roles()
        rows = [(uuid.uuid4(), "gpt-5", Decimal("1.00"), 1)]
        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=roles),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=_members()),
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
        ):
            service = NotificationService(MagicMock())
            await service.budget_exceeded(
                _run(), agent=_agent(), spec=_spec(), reason="cap", scope=BudgetScope.AGENT
            )
            await service.approval_requested(
                _run(user_id=None), agent=_agent(), spec=_spec(), tools=[]
            )
            await service.usage_report(uuid.uuid4(), period="weekly")

        assert [call.kwargs["preference"] for call in roles.call_args_list] == [
            "notify_budget_alerts",
            "notify_approval_requests",
            "notify_usage_reports",
        ]

    @pytest.mark.anyio
    async def test_the_scoped_resolver_is_asked_for_the_same_preference(self, sent):
        """Two resolvers, one opt-out. A mismatch would mail somebody who declined
        this kind of email while correctly excluding them from the other kind."""
        scoped = _members()
        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=scoped),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(),
                agent=_agent(owner_user_id=uuid.uuid4()),
                spec=_spec(budget=AlertSpec(to=[AlertAudience.OWNER])),
                reason="cap",
                scope=BudgetScope.AGENT,
            )

        assert scoped.await_args.kwargs["preference"] == "notify_budget_alerts"

    @pytest.mark.anyio
    async def test_an_opt_out_removes_somebody_and_promotes_nobody(self, sent):
        """An audience is a set of roles; an opt-out subtracts from what it
        resolved to. It never fills the gap with somebody else - so an
        initiator-only alert whose initiator declined is silence."""
        with (
            patch(f"{MODULE}.member_repo.list_emails_by_role", new=AsyncMock()) as roles,
            patch(f"{MODULE}.member_repo.list_emails_for_members", new=_members()),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=uuid.uuid4()),
                agent=_agent(),
                spec=_spec(approvals=AlertSpec(to=[AlertAudience.INITIATOR])),
                tools=["send_email"],
            )

        assert sent.calls == []
        roles.assert_not_awaited()


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
