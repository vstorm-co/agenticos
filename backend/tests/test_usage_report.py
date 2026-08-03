"""What a turn cost, and when a channel says it out loud.

The reporting mode is the part worth testing, and not because the arithmetic is
hard. A bot that stops answering because its organization hit a monthly cap looks
broken; the difference between "broken" and "out of budget" is somebody having
said so beforehand. So:

* `off` still records - unspoken is not unmeasured, because "the bot went quiet"
  is a question asked days later;
* `always` is offered and is not the default, because a footer under every reply
  in a busy channel is how a channel learns to skip the line that later matters;
* `near_limit` watches the workspace as well as the money, because a workspace
  about to refuse a write goes quiet the same way a budget does;
* `every_n` counts per chat, not per bot.

And the cost of measuring: a container's memory is a daemon round trip, so a
report nobody will see is never fetched.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.permissions import AuthContext, OrgRoleName
from app.repositories import agent_workspace_repo
from app.services.usage_report import (
    SandboxUsage,
    UsageReport,
    UsageReportService,
    format_footer,
    needs_sandbox_sample,
    should_report,
    usage_frame,
)

pytestmark = pytest.mark.anyio


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


def _report(**overrides: Any) -> UsageReport:
    fields: dict[str, Any] = {
        "input_tokens": 1200,
        "output_tokens": 300,
        "cost_usd": Decimal("0.0125"),
    }
    return UsageReport(**{**fields, **overrides})


def _run(**overrides: Any) -> MagicMock:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "input_tokens": 1200,
        "output_tokens": 300,
        "cost_usd": Decimal("0.0125"),
    }
    return MagicMock(**{**fields, **overrides})


class TestHowFullTheWorkspaceIs:
    def test_a_stored_workspace_is_measured_in_bytes_against_the_platform_cap(self):
        usage = SandboxUsage(kind="state", bytes_used=1024, bytes_limit=4096)

        assert usage.percent == 25

    def test_a_container_is_measured_in_memory_against_its_hosts_ceiling(self):
        usage = SandboxUsage(kind="service", memory_bytes=256, memory_limit_bytes=1024)

        assert usage.percent == 25

    def test_a_sandbox_nobody_sampled_reports_nothing_rather_than_zero(self):
        """ "0% full" would be a claim, and this has none to make."""
        assert SandboxUsage(kind="service").percent is None

    def test_a_sandbox_with_no_ceiling_reports_nothing_either(self):
        assert SandboxUsage(kind="service", memory_bytes=256).percent is None


class TestHowMuchOfTheMonthIsGone:
    def test_the_share_of_the_budget_spent(self):
        report = _report(period_spend_usd=Decimal("40"), budget_usd=Decimal("100"))

        assert report.budget_percent == 40

    def test_an_organization_with_no_cap_has_no_percentage(self):
        assert _report(period_spend_usd=Decimal("40")).budget_percent is None

    def test_a_cap_of_zero_is_not_divided_by(self):
        assert _report(budget_usd=Decimal("0")).budget_percent is None

    def test_a_cap_with_nothing_spent_yet_reads_as_zero(self):
        assert _report(budget_usd=Decimal("100")).budget_percent == 0


class TestWhenAChannelSaysIt:
    def test_off_never_speaks(self):
        assert should_report({"mode": "off"}, _report(), turn=1) is False

    def test_always_speaks_every_turn(self):
        assert should_report({"mode": "always"}, _report(), turn=1) is True

    def test_a_bot_that_predates_the_column_gets_the_default(self):
        """Which is `near_limit`, not `off`: defaulting to silence would leave
        every already-registered bot in the state this exists to prevent."""
        near = _report(period_spend_usd=Decimal("90"), budget_usd=Decimal("100"))

        assert should_report(None, near, turn=1) is True
        assert should_report(None, _report(), turn=1) is False

    def test_near_limit_speaks_once_the_budget_is_close(self):
        near = _report(period_spend_usd=Decimal("85"), budget_usd=Decimal("100"))

        assert should_report({"mode": "near_limit"}, near, turn=1) is True

    def test_near_limit_stays_quiet_below_the_threshold(self):
        report = _report(period_spend_usd=Decimal("40"), budget_usd=Decimal("100"))

        assert should_report({"mode": "near_limit"}, report, turn=1) is False

    def test_near_limit_watches_the_workspace_too(self):
        """A workspace about to refuse a write makes a bot go quiet the same way a
        budget does, and one that only watched the money would say nothing."""
        report = _report(sandbox=SandboxUsage(kind="state", bytes_used=90, bytes_limit=100))

        assert should_report({"mode": "near_limit"}, report, turn=1) is True

    def test_the_threshold_is_configurable(self):
        report = _report(period_spend_usd=Decimal("50"), budget_usd=Decimal("100"))

        assert should_report({"mode": "near_limit", "near_limit_percent": 40}, report, turn=1)

    def test_near_limit_with_nothing_measurable_stays_quiet(self):
        """No cap and no workspace is not "near" anything."""
        assert should_report({"mode": "near_limit"}, _report(), turn=1) is False

    @pytest.mark.parametrize(("turn", "expected"), [(1, False), (9, False), (10, True), (20, True)])
    def test_every_n_speaks_on_the_nth_turn_of_the_chat(self, turn: int, expected: bool):
        assert should_report({"mode": "every_n", "every_n": 10}, _report(), turn=turn) is expected

    def test_the_first_turn_is_not_the_nth(self):
        """`turn=0` is a chat nothing has counted yet - a modulo that fired there
        would put a footer under the very first reply of every conversation."""
        assert should_report({"mode": "every_n", "every_n": 10}, _report(), turn=0) is False

    def test_a_zero_interval_is_read_as_every_turn_rather_than_dividing_by_it(self):
        assert should_report({"mode": "every_n", "every_n": 0}, _report(), turn=3) is True


class TestWhatItCostsToMeasure:
    def test_a_bot_that_never_speaks_never_pays_for_a_sample(self):
        """A container's memory is a daemon round trip."""
        assert needs_sandbox_sample({"mode": "off"}) is False

    @pytest.mark.parametrize("mode", ["always", "near_limit", "every_n"])
    def test_every_other_mode_may_need_the_number(self, mode: str):
        assert needs_sandbox_sample({"mode": mode}) is True

    def test_an_unconfigured_bot_may_need_it_too(self):
        assert needs_sandbox_sample(None) is True


class TestTheLineAChannelCarries:
    def test_tokens_and_cost_are_always_there(self):
        assert "1,500 tokens" in format_footer(_report())
        assert "$0.0125" in format_footer(_report())

    def test_the_budget_share_is_named_when_there_is_a_cap(self):
        report = _report(period_spend_usd=Decimal("40"), budget_usd=Decimal("100"))

        assert "40% of this month's budget" in format_footer(report)

    def test_no_cap_means_no_budget_clause_rather_than_a_zero(self):
        assert "budget" not in format_footer(_report())

    def test_a_stored_workspace_is_called_a_workspace(self):
        report = _report(sandbox=SandboxUsage(kind="state", bytes_used=25, bytes_limit=100))

        assert "workspace 25% full" in format_footer(report)

    def test_a_container_is_called_sandbox_memory(self):
        """Two different limits with two different meanings; calling both "the
        workspace" would tell somebody they are near a limit that is not theirs."""
        report = _report(
            sandbox=SandboxUsage(kind="service", memory_bytes=25, memory_limit_bytes=100)
        )

        assert "sandbox memory 25% full" in format_footer(report)

    def test_an_unsampled_sandbox_is_reported_as_in_use_rather_than_as_empty(self):
        report = _report(sandbox=SandboxUsage(kind="service"))

        assert "sandbox memory in use" in format_footer(report)


class TestAssemblingIt:
    async def test_the_token_half_is_read_off_the_run_row(self, monkeypatch, mock_db_session):
        """Already written by the runner, so it costs nothing and cannot disagree
        with what the ledger recorded."""
        service = UsageReportService(mock_db_session)

        report = await service.for_run(_ctx(), _run())

        assert report.input_tokens == 1200
        assert report.cost_usd == Decimal("0.0125")
        assert report.sandbox is None

    async def test_the_workspace_is_not_read_unless_it_was_asked_for(
        self, monkeypatch, mock_db_session
    ):
        listed = AsyncMock(return_value=[])
        monkeypatch.setattr(agent_workspace_repo, "list_for_conversation", listed)
        service = UsageReportService(mock_db_session)

        await service.for_run(_ctx(), _run(), include_sandbox=False)

        listed.assert_not_called()

    async def test_a_stored_workspace_is_measured_from_its_row(self, monkeypatch, mock_db_session):
        row = MagicMock(backend="state", bytes_total=2048)
        monkeypatch.setattr(
            agent_workspace_repo, "list_for_conversation", AsyncMock(return_value=[row])
        )
        service = UsageReportService(mock_db_session)

        report = await service.for_run(_ctx(), _run(), include_sandbox=True)

        assert report.sandbox is not None
        assert report.sandbox.kind == "state"
        assert report.sandbox.bytes_used == 2048

    async def test_a_run_with_no_conversation_has_no_workspace_to_measure(
        self, monkeypatch, mock_db_session
    ):
        """A scheduled or API run has no chat, and there is nothing to look up."""
        listed = AsyncMock(return_value=[])
        monkeypatch.setattr(agent_workspace_repo, "list_for_conversation", listed)
        service = UsageReportService(mock_db_session)

        report = await service.for_run(_ctx(), _run(conversation_id=None), include_sandbox=True)

        assert report.sandbox is None
        listed.assert_not_called()

    async def test_a_conversation_with_no_workspace_reports_none(
        self, monkeypatch, mock_db_session
    ):
        monkeypatch.setattr(
            agent_workspace_repo, "list_for_conversation", AsyncMock(return_value=[])
        )
        service = UsageReportService(mock_db_session)

        report = await service.for_run(_ctx(), _run(), include_sandbox=True)

        assert report.sandbox is None

    async def test_a_container_is_sampled_one_session_at_a_time(self, monkeypatch, mock_db_session):
        """Asking for the whole listing would cost a round trip per sandbox the
        organization has open, to find the one this turn used."""
        row = MagicMock(backend="service", connection_id=uuid.uuid4(), session_id="xc-1")
        monkeypatch.setattr(
            agent_workspace_repo, "list_for_conversation", AsyncMock(return_value=[row])
        )
        service = UsageReportService(mock_db_session)
        sampled = AsyncMock(return_value={"memory_bytes": 512, "memory_limit_bytes": 2048})
        service.connections = MagicMock(session_usage=sampled)

        report = await service.for_run(_ctx(), _run(), include_sandbox=True)

        assert report.sandbox is not None
        assert report.sandbox.percent == 25
        assert sampled.await_args.args[2] == "xc-1"

    async def test_a_host_that_cannot_be_asked_still_reports_the_turn(
        self, monkeypatch, mock_db_session
    ):
        """The sandbox is demonstrably there - the turn just used it - and a
        number nobody could read is not worth losing an answer over."""
        row = MagicMock(backend="service", connection_id=uuid.uuid4(), session_id="xc-1")
        monkeypatch.setattr(
            agent_workspace_repo, "list_for_conversation", AsyncMock(return_value=[row])
        )
        service = UsageReportService(mock_db_session)
        service.connections = MagicMock(
            session_usage=AsyncMock(side_effect=RuntimeError("service is down"))
        )

        report = await service.for_run(_ctx(), _run(), include_sandbox=True)

        assert report.sandbox is not None
        assert report.sandbox.percent is None
        assert report.cost_usd == Decimal("0.0125")

    async def test_a_workspace_whose_host_was_forgotten_is_not_asked_about(
        self, monkeypatch, mock_db_session
    ):
        row = MagicMock(backend="service", connection_id=None, session_id="xc-1")
        monkeypatch.setattr(
            agent_workspace_repo, "list_for_conversation", AsyncMock(return_value=[row])
        )
        service = UsageReportService(mock_db_session)
        sampled = AsyncMock()
        service.connections = MagicMock(session_usage=sampled)

        report = await service.for_run(_ctx(), _run(), include_sandbox=True)

        assert report.sandbox is not None
        assert report.sandbox.percent is None
        sampled.assert_not_called()


class TestTheFrameAChatReads:
    """Numbers, not the sentence a channel gets: a chat draws a bar and a tooltip,
    and a pre-formatted string would force it to parse ours back apart."""

    def test_nothing_measured_stays_nothing(self):
        """Distinct from zero, which is a different thing to draw."""
        assert usage_frame(None) is None

    def test_the_tokens_and_the_cost_are_numbers(self):
        frame = usage_frame(_report())

        assert frame is not None
        assert frame["input_tokens"] == 1200
        assert frame["cost_usd"] == 0.0125
        assert frame["sandbox"] is None

    def test_the_budget_share_travels_with_it(self):
        frame = usage_frame(_report(period_spend_usd=Decimal("40"), budget_usd=Decimal("100")))

        assert frame is not None
        assert frame["budget_percent"] == 40

    def test_a_stored_workspace_carries_its_bytes_as_well_as_its_percentage(self):
        """The percentage is what a bar needs; the bytes are what a tooltip says,
        and recomputing one from the other in the client would be a second place
        for the ceiling to be wrong."""
        frame = usage_frame(
            _report(sandbox=SandboxUsage(kind="state", bytes_used=1024, bytes_limit=4096))
        )

        assert frame is not None
        assert frame["sandbox"] == {
            "kind": "state",
            "percent": 25,
            "bytes_used": 1024,
            "bytes_limit": 4096,
            "memory_bytes": None,
            "memory_limit_bytes": None,
        }

    def test_a_container_carries_its_memory(self):
        frame = usage_frame(
            _report(sandbox=SandboxUsage(kind="service", memory_bytes=512, memory_limit_bytes=2048))
        )

        assert frame is not None
        assert frame["sandbox"]["kind"] == "service"
        assert frame["sandbox"]["percent"] == 25
