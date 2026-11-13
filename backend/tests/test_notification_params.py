"""What an inbox row hands the console to word itself, and nothing more."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.agents.capabilities.budget import BudgetExceeded, BudgetScope, usd
from app.db.models.notification import Notification, NotificationEventType
from app.schemas.notification import NotificationRead


def _row(event_type: NotificationEventType, context: dict[str, object] | None) -> Notification:
    return Notification(
        id=uuid4(),
        event_type=event_type.value,
        summary="English summary",
        context_url=None,
        render_context=context,
        read_at=None,
        created_at=datetime.now(UTC),
    )


def _params(event_type: NotificationEventType, context: dict[str, object] | None):
    return NotificationRead.from_row(_row(event_type, context), strip_context_url=False).params


def test_a_budget_stop_hands_over_its_numbers_and_none_of_the_rest():
    context = {
        "agent_name": "Probe agent",
        "scope": "agent",
        "limit_usd": "0.0005",
        "spent_usd": "0.0008",
        "reason": "Agent monthly budget exhausted: $0.0008 spent of $0.0005 limit",
        "run_url": "https://console.example/agents/1?org=2",
        "org_name": "Acme",
        "routine_failure_owner_id": str(uuid4()),
    }
    assert _params(NotificationEventType.BUDGET_EXCEEDED, context) == {
        "agent_name": "Probe agent",
        "scope": "agent",
        "limit_usd": "0.0005",
        "spent_usd": "0.0008",
    }


def test_a_department_s_budget_stop_names_the_department():
    context = {
        "agent_name": "Probe agent",
        "scope": "group",
        "limit_usd": "10",
        "spent_usd": "10.02",
        "subject": "Sales",
    }
    assert _params(NotificationEventType.BUDGET_EXCEEDED, context) == context


def test_an_approval_request_hands_over_only_the_agent_name():
    context = {
        "agent_name": "Memory probe",
        "approvals_url": "https://console.example/runs?tab=approvals",
        "tools": "remember",
        "asked_by": "",
    }
    assert _params(NotificationEventType.APPROVAL_REQUESTED, context) == {
        "agent_name": "Memory probe"
    }


def test_a_department_warning_hands_over_its_share_as_text():
    context = {"group_name": "Sales", "share": 82, "limit": "100.00", "spent": "82.00"}
    assert _params(NotificationEventType.BUDGET_WARNING, context) == {
        "group_name": "Sales",
        "share": "82",
        "limit": "100.00",
    }


@pytest.mark.parametrize(
    ("event_type", "context"),
    [
        # Written before the numbers were kept: the English summary stands.
        (NotificationEventType.BUDGET_EXCEEDED, {"agent_name": "Probe", "reason": "cap"}),
        # Asked through a chat by somebody unverified: wording the console does not have.
        (
            NotificationEventType.APPROVAL_REQUESTED,
            {"agent_name": "Probe", "asked_by": "Asked in Slack by Ann (unverified)."},
        ),
        # A kind the console does not word.
        (NotificationEventType.RUN_FAILED, {"agent_name": "Probe"}),
        (NotificationEventType.BUDGET_EXCEEDED, None),
        # A value that is not a plain string or number.
        (
            NotificationEventType.APPROVAL_REQUESTED,
            {"agent_name": {"nested": "secret"}},
        ),
    ],
)
def test_no_params_where_the_console_cannot_word_the_row(event_type, context):
    assert _params(event_type, context) is None


def test_a_reader_served_another_wording_gets_no_params():
    row = _row(NotificationEventType.APPROVAL_REQUESTED, {"agent_name": "Probe", "asked_by": ""})
    read = NotificationRead.from_row(
        row, strip_context_url=True, summary_override="Probe's run is held, waiting on an approval"
    )
    assert read.params is None
    assert read.summary == "Probe's run is held, waiting on an approval"


@pytest.mark.parametrize(
    ("amount", "said"),
    [
        (Decimal("0.0005"), "$0.0005"),
        (Decimal("0.00005"), "$0.000050"),
        (Decimal("0"), "$0.00"),
        (Decimal("0.01"), "$0.01"),
        (Decimal("20"), "$20.00"),
    ],
)
def test_a_limit_below_a_cent_is_not_rounded_to_nothing(amount, said):
    assert usd(amount) == said


def test_a_refusal_names_a_sub_cent_limit_as_it_is():
    refusal = BudgetExceeded(
        limit_usd=Decimal("0.0005"), spent_usd=Decimal("0.0008"), scope=BudgetScope.AGENT
    )
    assert str(refusal) == "Agent monthly budget exhausted: $0.0008 spent of $0.0005 limit"
