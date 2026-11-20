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


def test_a_workflow_approval_hands_over_its_title_and_a_step_s_own_notice_nothing():
    asked = {"approval_title": "Send the refund?"}
    assert _params(NotificationEventType.WORKFLOW_NOTIFICATION, asked) == {
        "approval_title": "Send the refund?"
    }
    assert _params(NotificationEventType.WORKFLOW_NOTIFICATION, {"text": "Deployed"}) is None


@pytest.mark.parametrize(
    ("event_type", "context", "served"),
    [
        (
            NotificationEventType.RUN_FAILED,
            {
                "wording": "run_failed",
                "agent_name": "Probe",
                "error": "Timed out",
                "run_url": "https://console.example/agents/1",
                "run_id": str(uuid4()),
            },
            {"wording": "run_failed", "agent_name": "Probe", "error": "Timed out"},
        ),
        (
            NotificationEventType.RUN_FAILED,
            {"wording": "routine_blocked", "routine_detail": "watch_auto_stopped", "failures": 3},
            {"wording": "routine_blocked", "routine_detail": "watch_auto_stopped", "failures": "3"},
        ),
        (
            NotificationEventType.BUDGET_EXCEEDED,
            {
                "wording": "routine_budget_paused",
                "routine_kind": "watch",
                "limit": "5.00",
                "spent": "5.10",
                "routine_budget_paused": True,
                "cause": "routine:watch:1:budget:2026-11-01",
            },
            {
                "wording": "routine_budget_paused",
                "routine_kind": "watch",
                "limit": "5.00",
                "spent": "5.10",
            },
        ),
        (
            NotificationEventType.INGESTION_COMPLETED,
            {
                "wording": "sync_completed",
                "collection_name": "Handbook",
                "ingested": 3,
                "updated": 0,
                "skipped": 1,
                "removed": 0,
                "failed": 0,
                "sync_url": "https://console.example/rag/1",
            },
            {
                "wording": "sync_completed",
                "collection_name": "Handbook",
                "ingested": "3",
                "updated": "0",
                "skipped": "1",
                "removed": "0",
                "failed": "0",
            },
        ),
        (
            NotificationEventType.CONFIGURATION_CHANGED,
            {"wording": "configuration_changed", "action": "settings.update", "url": "/admin"},
            {"wording": "configuration_changed"},
        ),
        (
            NotificationEventType.SECURITY_EVENT,
            {"wording": "coalesced", "coalesced": "security_event", "action": "secret.created"},
            {"wording": "coalesced", "coalesced": "security_event"},
        ),
    ],
)
def test_a_worded_row_hands_over_its_wording_and_only_the_values_it_lists(
    event_type, context, served
):
    read = NotificationRead.from_row(_row(event_type, context), strip_context_url=False)
    assert read.params is None
    assert read.wording_params == served


@pytest.mark.parametrize(
    "context",
    [
        # A sentence this console does not know.
        {"wording": "something_new", "agent_name": "Probe"},
        # A required value missing.
        {"wording": "capability_requested", "agent_name": "Probe"},
        # A required value that is not plain text.
        {"wording": "briefing", "count": True},
        {"wording": "run_completed", "agent_name": {"nested": "secret"}},
    ],
)
def test_a_worded_row_the_console_cannot_word_keeps_its_english_summary(context):
    read = NotificationRead.from_row(
        _row(NotificationEventType.RUN_COMPLETED, context), strip_context_url=False
    )
    assert read.params is None
    assert read.wording_params is None


@pytest.mark.parametrize("wording", ["routine_budget_paused", "routine_blocked"])
def test_worded_budget_rows_do_not_expose_legacy_budget_params(wording: str):
    context = {
        "wording": wording,
        "routine_kind": "watch",
        "limit": "5",
        "spent": "6",
        "routine_detail": "run_budget",
    }
    read = NotificationRead.from_row(
        _row(NotificationEventType.BUDGET_EXCEEDED, context), strip_context_url=False
    )
    assert read.params is None  # An older console must retain the stored summary.
    assert read.wording_params is not None
    degraded = NotificationRead.from_row(
        _row(NotificationEventType.BUDGET_EXCEEDED, context),
        strip_context_url=True,
        summary_override="Redacted summary",
    )
    assert degraded.params is None
    assert degraded.wording_params is None
