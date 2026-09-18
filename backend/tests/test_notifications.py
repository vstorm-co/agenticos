"""Tests for run notifications - who hears about a run nobody was watching.

What is worth guarding here is not the wording. It is who a row is written
for, that the run itself never fails because a write did, and that a weekly
report about nothing is never written.

Two resolvers do all the work, and the split between them is a security
boundary:

- `member_repo.list_member_ids_by_role` + `list_app_admin_ids` answer the
  `admins` audience, and are deliberately wider than one organization.
- `member_repo.list_member_ids_for` answers everything keyed on a *person* -
  the agent's owner, the run's initiator, and the ids an author typed into
  `AlertSpec.user_ids`. It is membership-scoped.

These are unit tests, so they pin the **wiring**: which organization and which
ids reach the scoped resolver, and that nothing keyed on a person bypasses it.
Whether the query itself is really scoped, and really honours `is_active`, is
SQL - see `tests/integration/test_notification_recipients.py`. What each write
actually does with a resolved audience - dedup, preference, the savepoint - is
`tests/integration/test_notification_center.py`'s job; here, only that
`NotificationCenterService.write` is called with the right arguments.
"""

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.budget import BudgetScope
from app.agents.spec import AgentSpec, AlertAudience, AlertSpec, NotificationSpec
from app.db.models.notification import NotificationEventType
from app.services.notification_center import NotificationCenterService
from app.services.notifications import NotificationService

MODULE = "app.services.notifications"


def _run(*, org_id=None, user_id=None, cost="1.50", initiated_by_publisher_fallback=False):
    run = MagicMock()
    run.id = uuid.uuid4()
    run.organization_id = org_id or uuid.uuid4()
    run.user_id = user_id
    run.cost_usd = Decimal(cost)
    run.initiated_by_publisher_fallback = initiated_by_publisher_fallback
    return run


def _approvals(*tool_ids: str) -> list[MagicMock]:
    """A pending `ToolApproval` per tool id, each with its own fresh id -
    what `approval_requested`'s occurrence key is now built from."""
    approvals = []
    for tool_id in tool_ids:
        approval = MagicMock()
        approval.id = uuid.uuid4()
        approval.tool_id = tool_id
        approvals.append(approval)
    return approvals


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


class _Written:
    """Records what `NotificationCenterService.write` was asked to do.

    Returns one placeholder row per recipient - every real caller only
    reaches `write()` once it already has a non-empty recipient list, and a
    caller like `usage_report` reads this return value to decide whether it
    actually wrote anything (Decision 2), so an always-empty stub would make
    every one of those callers look like a silently swallowed failure.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> list[Any]:
        self.calls.append(kwargs)
        return [MagicMock() for _ in kwargs.get("recipients", [])]


@pytest.fixture
def written(monkeypatch) -> _Written:
    recorder = _Written()
    monkeypatch.setattr(NotificationCenterService, "write", recorder)
    return recorder


@pytest.fixture(autouse=True)
def _no_app_admins():
    """No app admins unless a test says otherwise.

    Autouse because every audience that includes `admins` asks for them, and an
    unpatched `MagicMock` session would answer with a mock that is neither a
    set of ids nor an error anybody could read.
    """
    with patch(f"{MODULE}.member_repo.list_app_admin_ids", new=AsyncMock(return_value=[])):
        yield


def _roles(*ids: uuid.UUID) -> AsyncMock:
    return AsyncMock(return_value=list(ids))


def _members(*ids: uuid.UUID) -> AsyncMock:
    return AsyncMock(return_value=set(ids))


def _bill(amount: str) -> AsyncMock:
    """`app.services.spend.organization_spend_since` - runs plus ingestion.

    Deliberately not the sum of whatever breakdown a test also passes: the
    point of reading it from there is that the two are different numbers.
    """
    return AsyncMock(return_value=Decimal(amount))


def _window_days(since: datetime, window_start: datetime) -> int:
    return round((window_start - since).total_seconds() / 86_400)


class TestBudgetExceeded:
    @pytest.mark.anyio
    async def test_the_owner_and_the_admins_are_both_told(self, written):
        """The builder fixes the agent; the people paying decide if the cap was too low."""
        admin_id, owner_id = uuid.uuid4(), uuid.uuid4()
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(admin_id)),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(owner_id)),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(),
                agent=_agent(owner_user_id=owner_id),
                spec=_spec(),
                reason="Monthly cap reached",
                scope=BudgetScope.AGENT,
            )

        call = written.calls[0]
        assert call["event_type"] is NotificationEventType.BUDGET_EXCEEDED
        assert set(call["recipients"]) == {admin_id, owner_id}

    @pytest.mark.anyio
    async def test_an_id_reached_two_ways_is_notified_once(self, written):
        """The common case in a small organization - and two identical rows read as a bug."""
        boss_id = uuid.uuid4()
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(boss_id)),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(boss_id)),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(),
                agent=_agent(owner_user_id=uuid.uuid4()),
                spec=_spec(),
                reason="cap",
                scope=BudgetScope.AGENT,
            )

        assert written.calls[0]["recipients"] == [boss_id]

    @pytest.mark.anyio
    async def test_nothing_is_written_when_there_is_nobody_to_write_to(self, written):
        """A deleted owner and an organization with no admins is not an error to raise."""
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(), agent=_agent(), spec=_spec(), reason="cap", scope=BudgetScope.AGENT
            )

        assert written.calls == []

    @pytest.mark.anyio
    async def test_an_agent_can_silence_its_own_budget_alert(self, written):
        """The whole reason this moved into the spec: one noisy agent should be
        quietenable without going deaf to the others."""
        with patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(),
                agent=_agent(),
                spec=_spec(budget=AlertSpec(enabled=False)),
                reason="cap",
                scope=BudgetScope.AGENT,
            )

        assert written.calls == []

    @pytest.mark.anyio
    async def test_the_organizations_cap_ignores_what_the_agent_asked_for(self, written):
        """A spec cannot silence a limit its author cannot raise.

        The organization's cap has just stopped this run and is about to stop
        every other one in the organization.
        """
        admin_id = uuid.uuid4()
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(admin_id)),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(),
                agent=_agent(),
                spec=_spec(budget=AlertSpec(enabled=False)),
                reason="cap",
                scope=BudgetScope.ORGANIZATION,
            )

        assert written.calls[0]["recipients"] == [admin_id]

    @pytest.mark.anyio
    async def test_the_deployments_app_admins_hear_about_the_organizations_cap(self, written):
        """An app admin holds no membership row, so a query scoped to one misses
        exactly the person who administers the deployment."""
        root_id = uuid.uuid4()
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles()),
            patch(
                f"{MODULE}.member_repo.list_app_admin_ids", new=AsyncMock(return_value=[root_id])
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

        assert written.calls[0]["recipients"] == [root_id]

    @pytest.mark.anyio
    async def test_the_write_carries_a_savepoint(self, written):
        """`finish` cannot afford a write failure here to poison the transaction
        that just recorded the run's own outcome (Decision 2)."""
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                _run(), agent=_agent(), spec=_spec(), reason="cap", scope=BudgetScope.AGENT
            )

        assert written.calls[0]["use_savepoint"] is True

    @pytest.mark.anyio
    async def test_the_occurrence_id_is_the_run(self, written):
        """One report per run, at the moment it is recorded as stopped - not per
        model request that was refused. Enforced by the database now: the
        dedup key is the run id."""
        run = _run()
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                run, agent=_agent(), spec=_spec(), reason="cap", scope=BudgetScope.AGENT
            )

        assert written.calls[0]["occurrence_id"] == str(run.id)


class TestEveryPersonIsResolvedInsideTheOrganization:
    """The tenant boundary on alert recipients.

    `AlertSpec.user_ids` is written by whoever may edit the agent. Resolved
    globally, an author could name a user id belonging to another organization
    and have them notified of this organization's name, the agent's name, the
    reason a run stopped and what it spent - all of which go into
    `render_context`. So every audience keyed on a person goes through one
    membership-scoped resolver, and these tests are about the argument it is
    handed.
    """

    @pytest.mark.anyio
    async def test_chosen_ids_are_resolved_only_among_this_organizations_members(self, written):
        chosen = [uuid.uuid4(), uuid.uuid4()]
        run = _run()
        scoped = _members(uuid.uuid4())

        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=scoped),
        ):
            await NotificationService(MagicMock()).approval_requested(
                run,
                agent=_agent(),
                spec=_spec(approvals=AlertSpec(to=[AlertAudience.CHOSEN], user_ids=chosen)),
                approvals=_approvals("send_email"),
            )

        kwargs = scoped.await_args.kwargs
        # The run's organization, not the agent's and not none: this is the
        # tenant the alert is about, and it is what bounds who may be notified.
        assert kwargs["organization_id"] == run.organization_id
        assert kwargs["user_ids"] == chosen

    @pytest.mark.anyio
    async def test_a_foreign_id_contributes_no_recipient(self, written):
        """The regression. The scoped resolver answers with nobody for an id
        that is not a member, and nobody is what must then be notified - rather
        than the identity being resolved some other way."""
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(),
                agent=_agent(),
                spec=_spec(approvals=AlertSpec(to=[AlertAudience.CHOSEN], user_ids=[uuid.uuid4()])),
                approvals=_approvals("x"),
            )

        assert written.calls == []

    @pytest.mark.anyio
    async def test_the_owner_goes_through_the_scoped_resolver_too(self, written):
        """Not because an agent's owner is likely to be foreign, but because one
        resolver for all three cannot be right for two of them and wrong for the
        third."""
        owner = uuid.uuid4()
        scoped = _members(owner)

        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=scoped),
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
    async def test_the_initiator_goes_through_the_scoped_resolver_too(self, written):
        initiator = uuid.uuid4()
        scoped = _members(initiator)

        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=scoped),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=initiator),
                agent=_agent(),
                spec=_spec(approvals=AlertSpec(to=[AlertAudience.INITIATOR])),
                approvals=_approvals("x"),
            )

        assert scoped.await_args.kwargs["user_ids"] == [initiator]

    @pytest.mark.anyio
    async def test_an_audience_naming_nobody_costs_no_query(self, written):
        """An `admins`-only alert must not ask the scoped resolver about an empty
        list - and, more to the point, must not ask it about `None`."""
        scoped = _members()

        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=scoped),
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
    async def test_a_run_with_no_initiator_asks_about_nobody(self, written):
        """A scheduled run has no user. Passing `None` into an `IN (...)` would
        be a query about a null id rather than about nobody."""
        scoped = _members()

        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=scoped),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=None), agent=_agent(owner_user_id=None), spec=_spec(), approvals=[]
            )

        scoped.assert_not_awaited()


class TestApprovalRequested:
    """One row per recipient, regardless of who may currently decide.

    The split into "gets the request" and "gets the fact" happens at send
    time now (`notification_delivery_sweep`) and at read time
    (`NotificationCenterService`'s gate), against each recipient's *current*
    standing - not here, against a snapshot from the moment the run parked.
    """

    @pytest.mark.anyio
    async def test_the_whole_audience_is_written_undivided(self, written):
        boss_id, asker_id = uuid.uuid4(), uuid.uuid4()
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(boss_id)),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(asker_id)),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=uuid.uuid4()),
                agent=_agent(),
                spec=_spec(),
                approvals=_approvals("send_email"),
            )

        assert len(written.calls) == 1
        call = written.calls[0]
        assert call["event_type"] is NotificationEventType.APPROVAL_REQUESTED
        assert set(call["recipients"]) == {boss_id, asker_id}
        assert call["render_context"]["tools"] == "send_email"

    @pytest.mark.anyio
    async def test_an_app_admin_is_part_of_the_admins_audience(self, written):
        """They hold no membership row; the `admins` resolver reaches them the
        same way it reaches an organization's own owners and admins."""
        root_id = uuid.uuid4()
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles()),
            patch(
                f"{MODULE}.member_repo.list_app_admin_ids", new=AsyncMock(return_value=[root_id])
            ),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=None), agent=_agent(), spec=_spec(), approvals=_approvals("x")
            )

        assert written.calls[0]["recipients"] == [root_id]

    @pytest.mark.anyio
    async def test_a_run_with_no_user_still_reaches_the_admins(self, written):
        """A scheduled or channel run has nobody attached, and a parked run
        nobody is told about sits parked until somebody happens to look."""
        admin_id = uuid.uuid4()
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(admin_id)),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=None), agent=_agent(), spec=_spec(), approvals=[]
            )

        call = written.calls[0]
        assert call["recipients"] == [admin_id]
        assert call["render_context"]["tools"] == "a tool call"

    @pytest.mark.anyio
    async def test_a_parked_run_with_nobody_at_all_is_not_an_error(self, written):
        """Every recipient gone is a state to survive, not to raise inside a `finally`."""
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=uuid.uuid4()), agent=_agent(), spec=_spec(), approvals=_approvals("x")
            )

        assert written.calls == []

    @pytest.mark.anyio
    async def test_an_agent_can_send_approvals_only_to_whoever_asked(self, written):
        """The ticket's other case: an agent whose approvals are nobody's
        business but the asker's."""
        asker_id = uuid.uuid4()
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=AsyncMock()) as roles,
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(asker_id)),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=uuid.uuid4()),
                agent=_agent(),
                spec=_spec(approvals=AlertSpec(to=[AlertAudience.INITIATOR])),
                approvals=_approvals("send_email"),
            )

        assert written.calls[0]["recipients"] == [asker_id]
        # Asked once, and only about who may decide has nothing to do with the
        # write path any more - `admins` was not named, and an audience that is
        # not named must not cost a query.
        roles.assert_not_awaited()

    @pytest.mark.anyio
    async def test_the_occurrence_id_is_the_approval_not_the_run(self, written):
        """A resumed run can park again on a new gated call while keeping the
        same `AgentRun.id` - the design's own occurrence key for this event
        is the approval id, precisely so the second request is not discarded
        as a repeat of the first."""
        run = _run(user_id=uuid.uuid4())
        approvals = _approvals("x")
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(uuid.uuid4())),
        ):
            await NotificationService(MagicMock()).approval_requested(
                run, agent=_agent(), spec=_spec(), approvals=approvals
            )

        assert (
            written.calls[0]["occurrence_id"]
            == hashlib.sha256(str(approvals[0].id).encode()).hexdigest()
        )
        assert written.calls[0]["occurrence_id"] != str(run.id)

    @pytest.mark.anyio
    async def test_two_pauses_on_the_same_run_get_two_occurrence_ids(self, written):
        run = _run(user_id=uuid.uuid4())
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(uuid.uuid4())),
        ):
            await NotificationService(MagicMock()).approval_requested(
                run, agent=_agent(), spec=_spec(), approvals=_approvals("x")
            )
            await NotificationService(MagicMock()).approval_requested(
                run, agent=_agent(), spec=_spec(), approvals=_approvals("y")
            )

        first, second = written.calls[0]["occurrence_id"], written.calls[1]["occurrence_id"]
        assert first != second

    @pytest.mark.anyio
    async def test_several_calls_parked_at_once_share_one_occurrence_id(self, written):
        """One write per pause, not per tool call - the sorted, joined set of
        approval ids is stable regardless of which order they are handed in."""
        run = _run(user_id=uuid.uuid4())
        approvals = _approvals("send_email", "delete_file")
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(uuid.uuid4())),
        ):
            await NotificationService(MagicMock()).approval_requested(
                run, agent=_agent(), spec=_spec(), approvals=approvals
            )

        assert (
            written.calls[0]["occurrence_id"]
            == hashlib.sha256(":".join(sorted(str(a.id) for a in approvals)).encode()).hexdigest()
        )

    @pytest.mark.anyio
    async def test_many_approvals_parked_at_once_fit_the_occurrence_id_column(self, written):
        """`notifications.occurrence_id` is `String(255)`; seven or more
        colon-joined UUIDs (37 chars apiece) would overflow it - the digest
        this event's occurrence key hashes to never does, regardless of how
        many tool calls parked at once."""
        run = _run(user_id=uuid.uuid4())
        approvals = _approvals(*[f"tool_{i}" for i in range(12)])
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(uuid.uuid4())),
        ):
            await NotificationService(MagicMock()).approval_requested(
                run, agent=_agent(), spec=_spec(), approvals=approvals
            )

        assert len(written.calls[0]["occurrence_id"]) <= 255

    @pytest.mark.anyio
    async def test_the_write_carries_a_savepoint(self, written):
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(uuid.uuid4())),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(user_id=uuid.uuid4()), agent=_agent(), spec=_spec(), approvals=_approvals("x")
            )

        assert written.calls[0]["use_savepoint"] is True


class TestRunCompletedAndFailed:
    """A run that ended off a surface nobody was watching live - `WEB`'s
    exclusion is `_notify`'s job (`tests/test_coverage_edges.py`), not this
    service's; these tests are about the audience and the write itself."""

    @pytest.mark.anyio
    async def test_the_initiator_is_told_a_run_completed(self, written):
        initiator = uuid.uuid4()
        run = _run(user_id=initiator)
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(initiator)):
            await NotificationService(MagicMock()).run_completed(run, agent=_agent())

        call = written.calls[0]
        assert call["event_type"] is NotificationEventType.RUN_COMPLETED
        assert call["recipients"] == [initiator]
        assert call["occurrence_id"] == str(run.id)
        assert call["use_savepoint"] is True

    @pytest.mark.anyio
    async def test_a_run_with_no_initiator_notifies_nobody(self, written):
        await NotificationService(MagicMock()).run_completed(_run(user_id=None), agent=_agent())

        assert written.calls == []

    @pytest.mark.anyio
    async def test_an_initiator_no_longer_a_member_notifies_nobody(self, written):
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()):
            await NotificationService(MagicMock()).run_completed(
                _run(user_id=uuid.uuid4()), agent=_agent()
            )

        assert written.calls == []

    @pytest.mark.anyio
    async def test_a_publisher_fallback_run_notifies_nobody(self, written):
        """A public embed, a hosted page or an unlinked channel message runs
        as the surface's publisher - `user_id` is set, but that person did
        not start this run, and a busy public surface would otherwise mail
        its publisher after every anonymous visitor's turn."""
        publisher = uuid.uuid4()
        run = _run(user_id=publisher, initiated_by_publisher_fallback=True)
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(publisher)):
            await NotificationService(MagicMock()).run_completed(run, agent=_agent())

        assert written.calls == []

    @pytest.mark.anyio
    async def test_the_initiator_is_told_a_run_failed_with_its_reason(self, written):
        initiator = uuid.uuid4()
        run = _run(user_id=initiator)
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(initiator)):
            await NotificationService(MagicMock()).run_failed(
                run, agent=_agent(), error="provider timeout"
            )

        call = written.calls[0]
        assert call["event_type"] is NotificationEventType.RUN_FAILED
        assert call["recipients"] == [initiator]
        assert "provider timeout" in call["summary"]

    @pytest.mark.anyio
    async def test_a_failure_with_no_reason_still_notifies(self, written):
        initiator = uuid.uuid4()
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(initiator)):
            await NotificationService(MagicMock()).run_failed(
                _run(user_id=initiator), agent=_agent(), error=None
            )

        assert len(written.calls) == 1

    @pytest.mark.anyio
    async def test_a_failed_run_with_no_initiator_notifies_nobody(self, written):
        await NotificationService(MagicMock()).run_failed(
            _run(user_id=None), agent=_agent(), error="x"
        )

        assert written.calls == []

    @pytest.mark.anyio
    async def test_a_failed_runs_initiator_no_longer_a_member_notifies_nobody(self, written):
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()):
            await NotificationService(MagicMock()).run_failed(
                _run(user_id=uuid.uuid4()), agent=_agent(), error="x"
            )

        assert written.calls == []

    @pytest.mark.anyio
    async def test_a_failed_publisher_fallback_run_notifies_nobody(self, written):
        publisher = uuid.uuid4()
        run = _run(user_id=publisher, initiated_by_publisher_fallback=True)
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(publisher)):
            await NotificationService(MagicMock()).run_failed(run, agent=_agent(), error="x")

        assert written.calls == []


_UNSET = object()


def _doc(
    *, org_id=_UNSET, initiated_by=None, kb_id=None, filename="handbook.pdf", collection="docs"
):
    doc = MagicMock()
    doc.id = uuid.uuid4()
    doc.organization_id = uuid.uuid4() if org_id is _UNSET else org_id
    doc.initiated_by_user_id = initiated_by
    doc.knowledge_base_id = kb_id
    doc.filename = filename
    doc.collection_name = collection
    return doc


class TestIngestionCompletedAndFailed:
    """A single document's own outcome - the per-document half of Decision
    1's ingestion events, reached once `RAGDocumentService.complete_ingestion`/
    `fail_ingestion` has confirmed a settlement is not stale."""

    @pytest.mark.anyio
    async def test_the_uploader_is_told_a_document_finished(self, written):
        uploader = uuid.uuid4()
        doc = _doc(initiated_by=uploader)
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(uploader)):
            await NotificationService(MagicMock()).ingestion_completed(
                doc, attempt=1, chunk_count=9
            )

        call = written.calls[0]
        assert call["event_type"] is NotificationEventType.INGESTION_COMPLETED
        assert call["recipients"] == [uploader]
        assert call["occurrence_id"] == f"{doc.id}:1"
        assert call["organization_id"] == doc.organization_id
        assert call["use_savepoint"] is True

    @pytest.mark.anyio
    async def test_the_occurrence_id_carries_the_attempt_it_settled(self, written):
        """Not `doc.ingestion_attempt` - the caller's own, passed in (#1598)."""
        uploader = uuid.uuid4()
        doc = _doc(initiated_by=uploader)
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(uploader)):
            await NotificationService(MagicMock()).ingestion_completed(
                doc, attempt=3, chunk_count=1
            )

        assert written.calls[0]["occurrence_id"] == f"{doc.id}:3"

    @pytest.mark.anyio
    async def test_a_synced_document_falls_back_to_the_administrators(self, written):
        """No uploader to tell individually - a connector sync's rows carry
        no `initiated_by_user_id` at all."""
        admin = uuid.uuid4()
        doc = _doc(initiated_by=None)
        with patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(admin)):
            await NotificationService(MagicMock()).ingestion_completed(
                doc, attempt=1, chunk_count=9
            )

        assert written.calls[0]["recipients"] == [admin]

    @pytest.mark.anyio
    async def test_a_document_outside_any_organization_notifies_nobody(self, written):
        doc = _doc(org_id=None, initiated_by=uuid.uuid4())

        await NotificationService(MagicMock()).ingestion_completed(doc, attempt=1, chunk_count=9)

        assert written.calls == []

    @pytest.mark.anyio
    async def test_an_uploader_no_longer_a_member_notifies_nobody(self, written):
        """No admin fallback here, the same as `run_completed`'s: the id was
        real, not null, so this is not the case the fallback is for."""
        doc = _doc(initiated_by=uuid.uuid4())
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()):
            await NotificationService(MagicMock()).ingestion_completed(
                doc, attempt=1, chunk_count=9
            )

        assert written.calls == []

    @pytest.mark.anyio
    async def test_the_uploader_is_told_a_document_failed_with_its_reason(self, written):
        uploader = uuid.uuid4()
        doc = _doc(initiated_by=uploader)
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(uploader)):
            await NotificationService(MagicMock()).ingestion_failed(
                doc, attempt=2, error_message="unreadable PDF"
            )

        call = written.calls[0]
        assert call["event_type"] is NotificationEventType.INGESTION_FAILED
        assert call["occurrence_id"] == f"{doc.id}:2"
        assert "unreadable PDF" in call["summary"]

    @pytest.mark.anyio
    async def test_a_failed_documents_organization_gates_it_too(self, written):
        doc = _doc(org_id=None, initiated_by=uuid.uuid4())

        await NotificationService(MagicMock()).ingestion_failed(doc, attempt=1, error_message="x")

        assert written.calls == []

    @pytest.mark.anyio
    async def test_a_failed_documents_uploader_no_longer_a_member_notifies_nobody(self, written):
        doc = _doc(initiated_by=uuid.uuid4())
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()):
            await NotificationService(MagicMock()).ingestion_failed(
                doc, attempt=1, error_message="x"
            )

        assert written.calls == []


class TestSyncCompletedAndFailed:
    """The whole-attempt half of Decision 1's ingestion events - a connector
    sync's own outcome, wired at the `rag_tasks.py` call sites rather than
    inside `RAGSyncService`/`SyncSourceService` (Decision 1's "hooking both
    double-fires" rule)."""

    @pytest.mark.anyio
    async def test_the_triggering_user_is_told_the_sync_finished(self, written):
        triggerer = uuid.uuid4()
        org_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(triggerer)):
            await NotificationService(MagicMock()).sync_completed(
                organization_id=org_id,
                initiator_user_id=triggerer,
                occurrence_id="log-1:2024-01-01",
                collection_name="docs",
                collection_id=kb_id,
                ingested=3,
                updated=1,
                skipped=2,
                failed=0,
            )

        call = written.calls[0]
        assert call["event_type"] is NotificationEventType.INGESTION_COMPLETED
        assert call["recipients"] == [triggerer]
        assert call["occurrence_id"] == "log-1:2024-01-01"
        assert call["organization_id"] == org_id
        assert str(kb_id) in call["render_context"]["collection_id"]

    @pytest.mark.anyio
    async def test_a_scheduled_syncs_completion_falls_back_to_the_administrators(self, written):
        admin = uuid.uuid4()
        with patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(admin)):
            await NotificationService(MagicMock()).sync_completed(
                organization_id=uuid.uuid4(),
                initiator_user_id=None,
                occurrence_id="log-2:2024-01-01",
                collection_name="docs",
                collection_id=None,
                ingested=0,
                updated=0,
                skipped=0,
                failed=0,
            )

        assert written.calls[0]["recipients"] == [admin]
        assert written.calls[0]["render_context"]["collection_id"] == ""

    @pytest.mark.anyio
    async def test_nobody_to_notify_writes_nothing(self, written):
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()):
            await NotificationService(MagicMock()).sync_completed(
                organization_id=uuid.uuid4(),
                initiator_user_id=uuid.uuid4(),
                occurrence_id="log-3:2024-01-01",
                collection_name="docs",
                collection_id=None,
                ingested=1,
                updated=0,
                skipped=0,
                failed=0,
            )

        assert written.calls == []

    @pytest.mark.anyio
    async def test_the_triggering_user_is_told_the_sync_failed_with_its_reason(self, written):
        triggerer = uuid.uuid4()
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(triggerer)):
            await NotificationService(MagicMock()).sync_failed(
                organization_id=uuid.uuid4(),
                initiator_user_id=triggerer,
                occurrence_id="src-1:2024-01-01",
                collection_name="docs",
                collection_id=None,
                error="Unknown connector: not_a_real_connector",
            )

        call = written.calls[0]
        assert call["event_type"] is NotificationEventType.INGESTION_FAILED
        assert "Unknown connector" in call["summary"]

    @pytest.mark.anyio
    async def test_a_failed_syncs_no_initiator_falls_back_to_the_administrators(self, written):
        admin = uuid.uuid4()
        with patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(admin)):
            await NotificationService(MagicMock()).sync_failed(
                organization_id=uuid.uuid4(),
                initiator_user_id=None,
                occurrence_id="src-2:2024-01-01",
                collection_name="docs",
                collection_id=None,
                error="Source has no assigned collection.",
            )

        assert written.calls[0]["recipients"] == [admin]

    @pytest.mark.anyio
    async def test_a_source_with_no_collection_keeps_the_gates_empty_marker(self, written):
        """An empty `collection_name` beside an empty `collection_id` is what
        tells `_collections_visible` a source was never assigned a collection
        from one whose collection was deleted mid-sync - and the two are shown
        to different people, so a readable stand-in in this field hides the
        failure from the very person who triggered it."""
        triggerer = uuid.uuid4()
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(triggerer)):
            await NotificationService(MagicMock()).sync_failed(
                organization_id=uuid.uuid4(),
                initiator_user_id=triggerer,
                occurrence_id="src-4:2024-01-01",
                collection_name="",
                collection_id=None,
                error="Source has no assigned collection.",
            )

        call = written.calls[0]
        assert call["render_context"]["collection_name"] == ""
        assert call["render_context"]["collection_id"] == ""
        # The sentence still reads, without an empty pair of quotes in it.
        assert call["summary"] == (
            "Sync of a source with no collection failed: Source has no assigned collection."
        )

    @pytest.mark.anyio
    async def test_a_failed_sync_with_nobody_to_tell_writes_nothing(self, written):
        with patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()):
            await NotificationService(MagicMock()).sync_failed(
                organization_id=uuid.uuid4(),
                initiator_user_id=uuid.uuid4(),
                occurrence_id="src-3:2024-01-01",
                collection_name="docs",
                collection_id=None,
                error="x",
            )

        assert written.calls == []


def _entry(
    *,
    action: str,
    org_id=_UNSET,
    actor=_UNSET,
    target_type="user",
    impersonator=None,
):
    entry = MagicMock()
    entry.id = uuid.uuid4()
    entry.action = action
    entry.organization_id = uuid.uuid4() if org_id is _UNSET else org_id
    entry.actor_user_id = uuid.uuid4() if actor is _UNSET else actor
    entry.target_type = target_type
    # `MagicMock()` is truthy by default, and `security_event` reads this
    # with `entry.impersonator_user_id or entry.actor_user_id` - an
    # unconfigured mock here would silently win that `or` on every test that
    # never mentions impersonation, rather than falling through to the actor
    # every one of them actually means to assert on.
    entry.impersonator_user_id = impersonator
    return entry


class TestSecurityEventAndConfigurationChanged:
    """The two mandatory events, wired at the record_audit call sites this
    plan curates as genuinely security-sensitive (#1598) - impersonation, an
    organization's own secrets and sandbox connections, an app admin's user
    management, and the deployment's own settings.

    Rate limiting itself is not this class's job: both methods pass
    `actor_user_id` through to `NotificationCenterService.write`, which
    already carries the per-`(actor_user_id, event_type)` mandatory-write
    limit (built in phase 2, `tests/integration/test_notification_center.py`
    - `test_a_rate_limited_mandatory_write_writes_nothing` and its sibling).
    What belongs here is that the id reaches that call correctly."""

    @pytest.mark.anyio
    async def test_an_org_scoped_entry_reaches_that_organizations_admins(self, written):
        admin = uuid.uuid4()
        entry = _entry(action="secret.created", target_type="secret")
        with patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(admin)):
            await NotificationService(MagicMock()).security_event(entry)

        call = written.calls[0]
        assert call["event_type"] is NotificationEventType.SECURITY_EVENT
        assert call["recipients"] == [admin]
        assert call["occurrence_id"] == str(entry.id)
        assert call["organization_id"] == entry.organization_id
        assert call["actor_user_id"] == entry.actor_user_id
        assert call["use_savepoint"] is True
        assert "/vault" in call["context_url"]

    @pytest.mark.anyio
    async def test_an_impersonated_write_rate_limits_the_impersonator_not_the_target(self, written):
        """`record_audit` records an impersonated write's *actor* as the
        impersonated account and the *impersonator* separately - keying the
        rate limit on the actor alone gave every impersonated target its own
        fresh budget and never bounded the administrator actually doing the
        impersonating."""
        admin = uuid.uuid4()
        impersonator = uuid.uuid4()
        entry = _entry(action="secret.created", target_type="secret", impersonator=impersonator)
        with patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(admin)):
            await NotificationService(MagicMock()).security_event(entry)

        assert written.calls[0]["actor_user_id"] == impersonator
        assert written.calls[0]["actor_user_id"] != entry.actor_user_id

    @pytest.mark.anyio
    async def test_an_org_scoped_entry_never_reaches_a_deployment_app_admin_alone(self, written):
        """`_security_audience` never unions in app admins for an org-scoped
        row - unlike `_administrator_ids` - because an app admin with no
        membership in this organization has no standing over its secret."""
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles()),
            patch(
                f"{MODULE}.member_repo.list_app_admin_ids",
                new=AsyncMock(return_value=[uuid.uuid4()]),
            ),
        ):
            await NotificationService(MagicMock()).security_event(
                _entry(action="secret.created", target_type="secret")
            )

        assert written.calls == []

    @pytest.mark.anyio
    async def test_an_app_admin_scoped_entry_reaches_deployment_app_admins(self, written):
        app_admin = uuid.uuid4()
        entry = _entry(action="admin.user.impersonate", org_id=None, target_type="user")
        with patch(
            f"{MODULE}.member_repo.list_app_admin_ids", new=AsyncMock(return_value=[app_admin])
        ):
            await NotificationService(MagicMock()).security_event(entry)

        call = written.calls[0]
        assert call["recipients"] == [app_admin]
        assert call["organization_id"] is None
        assert "?org=" not in call["context_url"]
        assert "/admin/users" in call["context_url"]

    @pytest.mark.anyio
    async def test_an_unrecognised_target_type_falls_back_to_the_admin_console(self, written):
        with patch(
            f"{MODULE}.member_repo.list_app_admin_ids", new=AsyncMock(return_value=[uuid.uuid4()])
        ):
            await NotificationService(MagicMock()).security_event(
                _entry(action="something.new", org_id=None, target_type="something_new")
            )

        assert written.calls[0]["context_url"].endswith("/admin")

    @pytest.mark.anyio
    async def test_an_action_with_no_curated_sentence_still_names_itself(self, written):
        with patch(
            f"{MODULE}.member_repo.list_app_admin_ids", new=AsyncMock(return_value=[uuid.uuid4()])
        ):
            await NotificationService(MagicMock()).security_event(
                _entry(action="something.new", org_id=None, target_type=None)
            )

        assert "something.new" in written.calls[0]["summary"]

    @pytest.mark.anyio
    async def test_nobody_to_tell_writes_nothing(self, written):
        with patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles()):
            await NotificationService(MagicMock()).security_event(
                _entry(action="secret.created", target_type="secret")
            )

        assert written.calls == []

    @pytest.mark.anyio
    async def test_an_actorless_entry_passes_no_actor_through(self, written):
        """The approval expiry sweep is the one `record_audit` caller with no
        actor - not one of this plan's curated call sites, but `write`'s own
        rate limit only turns on for a mandatory event type when
        `actor_user_id is not None` (`NotificationCenterService.write`), so a
        null one here must reach it as `None`, not skip the write outright."""
        admin = uuid.uuid4()
        with patch(f"{MODULE}.member_repo.list_app_admin_ids", new=AsyncMock(return_value=[admin])):
            await NotificationService(MagicMock()).security_event(
                _entry(action="secret.created", org_id=None, actor=None, target_type="secret")
            )

        call = written.calls[0]
        assert call["recipients"] == [admin]
        assert call["actor_user_id"] is None

    @pytest.mark.anyio
    async def test_configuration_changed_always_reaches_app_admins_never_org_admins(self, written):
        app_admin = uuid.uuid4()
        entry = _entry(action="deployment.settings_updated", org_id=None, target_type="deployment")
        with (
            patch(
                f"{MODULE}.member_repo.list_app_admin_ids", new=AsyncMock(return_value=[app_admin])
            ),
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
        ):
            await NotificationService(MagicMock()).configuration_changed(entry)

        call = written.calls[0]
        assert call["event_type"] is NotificationEventType.CONFIGURATION_CHANGED
        assert call["recipients"] == [app_admin]
        assert call["organization_id"] is None
        assert call["actor_user_id"] == entry.actor_user_id

    @pytest.mark.anyio
    async def test_configuration_changed_with_no_app_admins_writes_nothing(self, written):
        with patch(f"{MODULE}.member_repo.list_app_admin_ids", new=AsyncMock(return_value=[])):
            await NotificationService(MagicMock()).configuration_changed(
                _entry(action="deployment.settings_updated", org_id=None, target_type="deployment")
            )

        assert written.calls == []


class TestUsageReport:
    @pytest.mark.anyio
    async def test_an_organization_that_ran_nothing_gets_no_report(self, written):
        """A weekly '0 runs, $0.00' is what teaches people to filter the sender."""
        with patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=[])):
            reported = await NotificationService(MagicMock()).usage_report(
                uuid.uuid4(), period="weekly", window_start=datetime.now(UTC)
            )

        assert reported is False
        assert written.calls == []

    @pytest.mark.anyio
    async def test_a_swallowed_write_failure_reports_nothing_written(self, monkeypatch):
        """`write()` can return `[]` for a reason other than "nothing to
        report" - a rate limit, or a savepoint that swallowed a DB error
        (Decision 2). `usage_report` must not claim a report went out when
        the underlying write never actually landed."""
        monkeypatch.setattr(NotificationCenterService, "write", AsyncMock(return_value=[]))
        rows = [(uuid.uuid4(), "gpt-5", Decimal("2.00"), 3)]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.organization_spend_since", new=_bill("2.00")),
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            reported = await NotificationService(MagicMock()).usage_report(
                uuid.uuid4(), period="weekly", window_start=datetime.now(UTC)
            )

        assert reported is False

    @pytest.mark.anyio
    async def test_the_run_count_sums_every_row_and_the_agents_are_counted_once(self, written):
        """The breakdown is per agent *and* model, so one agent that was
        repointed mid-window appears on two rows - four runs, one agent, not
        two."""
        one_agent = uuid.uuid4()
        rows = [
            (one_agent, "gpt-5", Decimal("2.00"), 3),
            (one_agent, "claude", Decimal("0.50"), 1),
        ]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.organization_spend_since", new=_bill("2.50")),
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            reported = await NotificationService(MagicMock()).usage_report(
                uuid.uuid4(), period="monthly", window_start=datetime.now(UTC)
            )

        assert reported is True
        context = written.calls[0]["render_context"]
        assert context["runs"] == "4"
        assert context["agents"] == "1"
        assert context["period"] == "month"

    @pytest.mark.anyio
    async def test_the_total_is_the_bill_and_not_the_sum_of_the_breakdown(self, written):
        """This report said $1.40 for $1.00 of work.

        Summing the breakdown got the arithmetic wrong in both directions at
        once: a delegated run appeared twice, because a delegate's tokens are
        already inside its parent's `cost_usd`, and ingestion's embedding
        spend appeared not at all. `app.services.spend` is the one place that
        question is answered, so this figure now agrees with the budget the
        platform enforces.
        """
        rows = [(uuid.uuid4(), "gpt-5", Decimal("1.00"), 1)]
        bill = _bill("1.12")
        window_start = datetime.now(UTC)
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.organization_spend_since", new=bill),
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).usage_report(
                uuid.uuid4(), period="weekly", window_start=window_start
            )

        context = written.calls[0]["render_context"]
        assert context["total"] == "1.12"
        # And over the window the report says it covers, not the calendar
        # month a cap is metered on - "over the past week" has to mean the
        # past week.
        assert _window_days(bill.await_args.args[2], window_start) == 7

    @pytest.mark.anyio
    async def test_a_report_with_nobody_to_read_it_is_not_written(self, written):
        """An organization whose last admin left still has runs; it has no reader."""
        rows = [(uuid.uuid4(), "gpt-5", Decimal("1.00"), 1)]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles()),
        ):
            reported = await NotificationService(MagicMock()).usage_report(
                uuid.uuid4(), period="weekly", window_start=datetime.now(UTC)
            )

        assert reported is False
        assert written.calls == []

    @pytest.mark.anyio
    async def test_the_occurrence_id_carries_the_window_so_a_retry_does_not_duplicate(
        self, written
    ):
        """A restarted report flow must compute the same occurrence id on its
        second attempt, or the dedup constraint has nothing to catch - every
        organization already notified once would be notified again."""
        organization_id = uuid.uuid4()
        window_start = datetime.now(UTC)
        rows = [(uuid.uuid4(), "gpt-5", Decimal("1.00"), 1)]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.organization_spend_since", new=_bill("1.00")),
        ):
            await NotificationService(MagicMock()).usage_report(
                organization_id, period="weekly", window_start=window_start
            )

        assert (
            written.calls[0]["occurrence_id"]
            == f"{organization_id}:weekly:{window_start.isoformat()}"
        )

    @pytest.mark.anyio
    async def test_the_write_carries_a_savepoint(self, written):
        """The report flow shares one session across every organization in the
        estate - a write failure here must not poison the loop's remaining
        iterations."""
        rows = [(uuid.uuid4(), "gpt-5", Decimal("1.00"), 1)]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.organization_spend_since", new=_bill("1.00")),
        ):
            await NotificationService(MagicMock()).usage_report(
                uuid.uuid4(), period="weekly", window_start=datetime.now(UTC)
            )

        assert written.calls[0]["use_savepoint"] is True


class TestPerAgentUsageReport:
    """The opt-in report about one agent, rather than the estate."""

    @pytest.mark.anyio
    async def test_an_agent_that_did_not_ask_gets_no_report(self, written):
        """Off by default: a weekly report per agent for forty agents is forty
        rows nobody reads, which is how the one that mattered gets filtered."""
        reported = await NotificationService(MagicMock()).agent_usage_report(
            _agent(), _spec(), period="weekly", window_start=datetime.now(UTC)
        )

        assert reported is False
        assert written.calls == []

    @pytest.mark.anyio
    async def test_the_report_covers_this_agent_and_not_its_neighbours(self, written):
        """The breakdown is the organization's, so the wrong filter here would
        report the estate's spend as one agent's."""
        agent = _agent()
        rows = [
            (agent.id, "gpt-5", Decimal("2.00"), 3),
            (uuid.uuid4(), "gpt-5", Decimal("90.00"), 100),
        ]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            reported = await NotificationService(MagicMock()).agent_usage_report(
                agent,
                _spec(usage=AlertSpec(enabled=True)),
                period="weekly",
                window_start=datetime.now(UTC),
            )

        assert reported is True
        context = written.calls[0]["render_context"]
        assert context["total"] == "2.00"
        assert context["runs"] == "3"
        assert context["agents"] == agent.name

    @pytest.mark.anyio
    async def test_it_counts_the_runs_this_agent_was_delegated_into(self, written):
        """The mirror image of the organization's report, and the one question
        that wants the child rows.

        An agent used as somebody's delegate spends money in runs that are
        recorded only as its own delegated rows - so a report that excluded
        them would tell the person answerable for that agent it had cost
        nothing.
        """
        agent = _agent()
        rows = [(agent.id, "claude", Decimal("0.40"), 1)]
        breakdown = AsyncMock(return_value=rows)
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=breakdown),
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).agent_usage_report(
                agent,
                _spec(usage=AlertSpec(enabled=True)),
                period="weekly",
                window_start=datetime.now(UTC),
            )

        assert breakdown.await_args.kwargs["include_delegations"] is True
        assert written.calls[0]["render_context"]["total"] == "0.40"

    @pytest.mark.anyio
    async def test_a_per_agent_report_is_scoped_to_the_agents_own_organization(self, written):
        """It has no run to take a tenant from, so the agent's own column is
        what bounds who may be notified."""
        agent = _agent(owner_user_id=uuid.uuid4())
        rows = [(agent.id, "gpt-5", Decimal("1.00"), 1)]
        scoped = _members(uuid.uuid4())

        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=scoped),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).agent_usage_report(
                agent,
                _spec(usage=AlertSpec(enabled=True, to=[AlertAudience.OWNER])),
                period="weekly",
                window_start=datetime.now(UTC),
            )

        assert scoped.await_args.kwargs["organization_id"] == agent.organization_id

    @pytest.mark.anyio
    async def test_an_agent_that_ran_nothing_is_silent_even_when_asked(self, written):
        agent = _agent()
        rows = [(uuid.uuid4(), "gpt-5", Decimal("5.00"), 2)]
        with patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)):
            reported = await NotificationService(MagicMock()).agent_usage_report(
                agent,
                _spec(usage=AlertSpec(enabled=True)),
                period="weekly",
                window_start=datetime.now(UTC),
            )

        assert reported is False
        assert written.calls == []

    @pytest.mark.anyio
    async def test_a_report_nobody_is_left_to_read_is_not_written(self, written):
        agent = _agent()
        rows = [(agent.id, "gpt-5", Decimal("1.00"), 1)]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles()),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()),
        ):
            reported = await NotificationService(MagicMock()).agent_usage_report(
                agent,
                _spec(usage=AlertSpec(enabled=True)),
                period="weekly",
                window_start=datetime.now(UTC),
            )

        assert reported is False
        assert written.calls == []

    @pytest.mark.anyio
    async def test_the_occurrence_id_carries_the_window_so_a_retry_does_not_duplicate(
        self, written
    ):
        agent = _agent()
        window_start = datetime.now(UTC)
        rows = [(agent.id, "gpt-5", Decimal("1.00"), 1)]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).agent_usage_report(
                agent,
                _spec(usage=AlertSpec(enabled=True)),
                period="weekly",
                window_start=window_start,
            )

        assert written.calls[0]["occurrence_id"] == f"{agent.id}:weekly:{window_start.isoformat()}"


class TestEveryLinkNamesItsOrganization:
    """An alert opens the tenant it is about, not the one the reader last used.

    `apiClient` stamps `X-Organization-Id` from a selection persisted per
    browser, and every alert URL was organization-agnostic - so somebody in two
    organizations who was last working in Globex opened the approval alert for a
    run in Acme and read Globex's queue: very likely empty, and reading as
    "nothing is waiting" about a run that is parked and ageing towards
    `ApprovalService.expire_stale` (#1204). The agent links were worse in a
    quieter way: `/agents/{id}` under the wrong organization is a refusal for an
    agent the reader can genuinely see, one switch away.

    One parameter name, decided in `_link` rather than at four call sites.
    """

    @pytest.mark.anyio
    async def test_the_budget_alert_names_the_runs_organization(self, written):
        run = _run()
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).budget_exceeded(
                run,
                agent=_agent(),
                spec=_spec(),
                reason="cap",
                scope=BudgetScope.AGENT,
            )

        call = written.calls[0]
        assert call["render_context"]["run_url"].endswith(f"?org={run.organization_id}")
        assert call["context_url"] == call["render_context"]["run_url"]
        assert call["organization_id"] == run.organization_id

    @pytest.mark.anyio
    async def test_the_approval_alert_names_the_runs_organization(self, written):
        """The run's, not the agent's: they are the same today and the run is
        what the alert is about, so a delegated run in another tenant would
        still open the queue holding it."""
        run = _run(org_id=uuid.uuid4())
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members(uuid.uuid4())),
        ):
            await NotificationService(MagicMock()).approval_requested(
                run, agent=_agent(), spec=_spec(), approvals=_approvals("send_email")
            )

        call = written.calls[0]
        assert call["render_context"]["approvals_url"].endswith(f"&org={run.organization_id}")
        assert call["context_url"] == call["render_context"]["approvals_url"]

    @pytest.mark.anyio
    async def test_the_organization_report_names_the_organization_it_reports_on(self, written):
        organization_id = uuid.uuid4()
        rows = [(uuid.uuid4(), "gpt-5", Decimal("2.00"), 3)]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.organization_spend_since", new=_bill("2.00")),
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).usage_report(
                organization_id, period="weekly", window_start=datetime.now(UTC)
            )

        context = written.calls[0]["render_context"]
        assert context["dashboard_url"].endswith(f"?org={organization_id}")

    @pytest.mark.anyio
    async def test_the_agent_report_names_the_agents_organization(self, written):
        agent = _agent(org_id=uuid.uuid4(), owner_user_id=uuid.uuid4())
        rows = [(agent.id, "gpt-5", Decimal("1.00"), 2)]
        with (
            patch(f"{MODULE}.agent_run_repo.cost_breakdown", new=AsyncMock(return_value=rows)),
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()),
            patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        ):
            await NotificationService(MagicMock()).agent_usage_report(
                agent,
                _spec(usage=AlertSpec(enabled=True, to=[AlertAudience.ADMINS])),
                period="weekly",
                window_start=datetime.now(UTC),
            )

        context = written.calls[0]["render_context"]
        assert context["dashboard_url"].endswith(f"?org={agent.organization_id}")

    def test_the_parameter_name_is_decided_in_one_place(self):
        """Four call sites inventing one is what the issue is about, one level up."""
        service = NotificationService(MagicMock())
        organization_id = uuid.uuid4()

        assert service._link("/agents", organization_id).endswith(f"/agents?org={organization_id}")
        # The approvals link already carries `?tab=`, and a second `?` would
        # name no organization at all - the console would read the whole tail
        # as the tab.
        assert service._link("/runs?tab=approvals", organization_id).endswith(
            f"/runs?tab=approvals&org={organization_id}"
        )


class TestWhereAnAlertSends:
    """The link is the whole point of an alert, and nothing else checks it.

    An email that says a run is parked is read by somebody who has to decide,
    and the only thing they can do with it is click. Every one of these URLs
    is a hand-built f-string that no route table, no type and no other test
    looks at - so a page that moves, or a surface built somewhere other than
    where the string guessed, is found by a person following the link and not
    finding the control.
    """

    @pytest.mark.anyio
    async def test_the_approval_alert_addresses_the_queue_not_the_builder(self, written):
        """The regression. `/agents/{id}` is the Builder: it holds one sentence
        of prose about tool calls reaching a queue, and no queue. So the click
        landed on a page whose own subject is editing the agent, while the
        parked run aged towards `ApprovalService.expire_stale` (#935)."""
        with (
            patch(f"{MODULE}.member_repo.list_member_ids_by_role", new=_roles(uuid.uuid4())),
            patch(f"{MODULE}.member_repo.list_member_ids_for", new=_members()),
        ):
            await NotificationService(MagicMock()).approval_requested(
                _run(), agent=_agent(), spec=_spec(), approvals=_approvals("send_email")
            )

        approvals_url = written.calls[0]["render_context"]["approvals_url"]
        assert "/runs?tab=approvals&" in approvals_url
        # Named because it is what the link used to be, and the agent id is
        # still in scope at the call site.
        assert "/agents/" not in approvals_url
