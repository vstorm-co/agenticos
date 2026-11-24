"""The re-sent tool output estimate, computed from rows rather than read from a database."""

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.repositories.tool_output_report import CallSize, RecordedRequest, ReportRun
from app.services.tool_output_report import (
    Distribution,
    LeftOut,
    ToolOutputReportService,
    as_json,
    bindings_of,
    distribution,
    estimate_run,
    render_text,
)

pytestmark = pytest.mark.anyio

RUN = uuid4()


def _call(name: str, size: int, *, tool_id: str | None = None, mcp: bool = False) -> CallSize:
    return CallSize(RUN, name, tool_id, mcp, size)


def _request(index: int, *calls: str, input_tokens: int = 100) -> RecordedRequest:
    return RecordedRequest(RUN, index, input_tokens, 0, 0, list(calls))


class TestDistribution:
    def test_nothing_is_all_zero(self) -> None:
        assert distribution([]) == Distribution(0, 0, 0, 0, 0)

    def test_nearest_rank_percentiles(self) -> None:
        assert distribution(range(1, 101)) == Distribution(100, 50, 90, 99, 100)


class TestEstimateRun:
    def test_a_result_is_carried_by_every_request_after_the_one_that_called_it(self) -> None:
        estimate = estimate_run(
            [_call("search", 4000)],
            [_request(0, "search"), _request(1), _request(2), _request(3)],
        )

        assert estimate.resent_chars == 4000 * 3
        assert (estimate.exact, estimate.averaged, estimate.unmatched) == (1, 0, 0)

    def test_parallel_calls_of_one_tool_in_one_request_are_placed_exactly(self) -> None:
        estimate = estimate_run(
            [_call("search", 100), _call("search", 300)],
            [_request(0, "search", "search"), _request(1)],
        )

        assert estimate.resent_chars == 400
        assert (estimate.exact, estimate.averaged) == (2, 0)

    def test_one_tool_called_in_several_requests_is_averaged_over_them(self) -> None:
        estimate = estimate_run(
            [_call("search", 100), _call("search", 300)],
            [_request(0, "search"), _request(1, "search"), _request(2)],
        )

        # Later requests are 2 and 1; which result came first is unknown.
        assert estimate.resent_chars == 400 * 1.5
        assert (estimate.exact, estimate.averaged) == (0, 2)

    def test_a_call_its_manifest_does_not_name_is_left_out(self) -> None:
        estimate = estimate_run([_call("search", 900)], [_request(0, "fetch"), _request(1)])

        assert estimate.resent_chars == 0
        assert estimate.unmatched == 1

    def test_packing_saves_only_on_large_results_after_two_full_sends(self) -> None:
        requests = [_request(0, "read", "small")] + [_request(i) for i in range(1, 6)]
        estimate = estimate_run([_call("read", 20_000), _call("small", 9_000)], requests)

        # Five later requests: two in full, three as a placeholder.
        assert estimate.saving_chars == {
            "1.3 KB": (20_000 - 1_300) * 3,
            "3.5 KB": (20_000 - 3_500) * 3,
        }

    def test_nothing_is_saved_when_the_run_ends_within_two_sends(self) -> None:
        estimate = estimate_run(
            [_call("read", 50_000)], [_request(0, "read"), _request(1), _request(2)]
        )

        assert estimate.saving_chars == {"1.3 KB": 0, "3.5 KB": 0}

    def test_requests_are_read_in_their_recorded_order(self) -> None:
        estimate = estimate_run(
            [_call("search", 10)], [_request(2), _request(0, "search"), _request(1)]
        )

        assert estimate.resent_chars == 20


class TestBindings:
    def test_an_agent_binding_neither(self) -> None:
        assert bindings_of([]) == ("none", "none")
        assert bindings_of([{"id": "web_search"}]) == ("none", "none")

    def test_no_spec_at_all_is_unknown_not_none(self) -> None:
        assert bindings_of(None) == ("unknown", "unknown")

    def test_a_bare_binding_reads_as_its_default(self) -> None:
        assert bindings_of([{"id": "tool_output_limits"}, {"id": "compaction"}]) == (
            "spill",
            "summarize",
        )

    def test_the_configured_action_and_strategy(self) -> None:
        capabilities = [
            {"id": "tool_output_limits", "config": {"action": "truncate"}},
            {"id": "compaction", "config": {"strategy": "tiered"}},
        ]
        assert bindings_of(capabilities) == ("truncate", "tiered")

    def test_a_switched_off_binding_or_a_malformed_one_counts_as_none(self) -> None:
        capabilities = [{"id": "compaction", "enabled": False}, "tool_output_limits"]
        assert bindings_of(capabilities) == ("none", "none")


def _run(
    agent: str,
    *,
    agent_id: UUID | None = None,
    version: UUID | None = None,
    capabilities=(),
    conversation: bool = True,
    system_role: str | None = None,
) -> ReportRun:
    return ReportRun(
        uuid4(),
        agent_id or uuid4(),
        agent,
        version,
        None,
        uuid4() if conversation else None,
        system_role,
        None if capabilities is None else list(capabilities),
    )


def _assemble(
    runs, calls, requests, *, turns=None, versions=None, top=20, inherited=None, parked=None
):
    return ToolOutputReportService._assemble(
        uuid4(),
        started_from=date(2026, 11, 1),
        ended=date(2026, 11, 22),
        include_eval=False,
        include_tests=False,
        top=top,
        runs=runs,
        calls=calls,
        requests=requests,
        turns=turns or {},
        versions=versions or {},
        inherited=inherited or {},
        parked=parked or set(),
    )


class TestAssemble:
    def test_figures_split_by_agent_and_bindings_and_flag_clearing_compaction(self) -> None:
        clearing = _run(
            "Coder",
            capabilities=[{"id": "compaction", "config": {"strategy": "clear_tool_results"}}],
        )
        plain = _run("Support")
        calls = {
            clearing.id: [CallSize(clearing.id, "read", None, False, 40_000)],
            plain.id: [CallSize(plain.id, "search", None, True, 400)],
        }
        requests = {
            clearing.id: [
                RecordedRequest(clearing.id, 0, 1_000, 10, 5, ["read"]),
                *[RecordedRequest(clearing.id, i, 20_000, 0, 0, []) for i in range(1, 5)],
            ],
            plain.id: [
                RecordedRequest(plain.id, 0, 300, 0, 0, ["search"]),
                RecordedRequest(plain.id, 1, 500, 0, 0, []),
            ],
        }

        report = _assemble([clearing, plain], calls, requests, turns={plain.id: 2})

        rows = {row.agent: row for row in report.resend}
        coder = rows["Coder"]
        assert (coder.tool_output_limits, coder.compaction, coder.overstated) == (
            "none",
            "clear_tool_results",
            True,
        )
        assert coder.resent_tokens == 40_000 * 4 // 4
        assert coder.own_input_tokens == 81_000
        assert (coder.cache_read_tokens, coder.cache_write_tokens) == (10, 5)
        assert coder.saving_tokens["1.3 KB"] == round((40_000 - 1_300) * 2 / 4)
        assert report.resend[0].agent == "Coder"
        assert rows["Support"].share == round(400 / 4 / 800, 4)
        assert [row.name for row in report.by_capability] == ["(other)", "mcp"]
        assert report.turns_per_run.max == 2
        assert report.requests_per_run == Distribution(2, 2, 5, 5, 5)

    def test_a_run_without_a_manifest_counts_in_sizes_but_not_in_the_estimate(self) -> None:
        run = _run("Support")
        report = _assemble([run], {run.id: [CallSize(run.id, "search", None, False, 700)]}, {})

        assert (report.runs, report.runs_estimated, report.tool_calls) == (1, 0, 1)
        assert report.left_out == LeftOut(0, 1, 0)
        assert report.matching.left_out == 1
        assert report.by_tool[0].sizes.max == 700
        row = report.resend[0]
        assert (row.runs, row.runs_estimated, row.share) == (1, 0, None)

    def test_a_run_outside_a_conversation_adds_no_input_it_has_no_results_for(self) -> None:
        chat = _run("Support")
        evaluated = _run("Support", agent_id=chat.agent_id, conversation=False)
        calls = {chat.id: [CallSize(chat.id, "search", None, False, 400)]}
        requests = {
            run.id: [
                RecordedRequest(run.id, 0, 300, 0, 0, ["search"]),
                RecordedRequest(run.id, 1, 500, 0, 0, []),
            ]
            for run in (chat, evaluated)
        }

        report = _assemble([chat, evaluated], calls, requests)

        row = report.resend[0]
        assert (row.runs, row.runs_estimated, row.own_input_tokens) == (2, 1, 800)
        assert row.share == round(400 / 4 / 800, 4)
        assert report.left_out == LeftOut(1, 0, 0)

    def test_a_run_that_waited_on_a_person_is_left_out_of_the_estimate(self) -> None:
        run = _run("Support")
        report = _assemble(
            [run],
            {run.id: [CallSize(run.id, "send_email", None, False, 50)]},
            {run.id: [RecordedRequest(run.id, 0, 100, 0, 0, [])]},
            parked={run.id},
        )

        assert report.left_out == LeftOut(0, 0, 1)
        assert (report.matching.unmatched, report.matching.left_out) == (0, 1)
        assert report.resend[0].own_input_tokens == 0

    def test_earlier_turns_results_count_apart_on_every_request_of_a_follow_up(self) -> None:
        run = _run("Support")
        requests = {
            run.id: [
                RecordedRequest(run.id, 0, 1_000, 0, 0, ["search"]),
                RecordedRequest(run.id, 1, 1_000, 0, 0, []),
            ]
        }
        calls = {run.id: [CallSize(run.id, "search", None, False, 400)]}

        row = _assemble([run], calls, requests, inherited={run.id: 2_000}).resend[0]
        assert (row.resent_tokens, row.inherited_tokens) == (100, 1_000)
        assert (row.share, row.share_with_inherited) == (0.05, 0.55)

        capped = _assemble([run], calls, requests, inherited={run.id: 9_000}).resend[0]
        assert capped.share_with_inherited == 1.0

    def test_two_agents_sharing_a_name_stay_apart(self) -> None:
        first, second = _run("Support"), _run("Support")
        calls = {run.id: [CallSize(run.id, "search", None, False, 10)] for run in (first, second)}

        report = _assemble([first, second], calls, {})

        assert {row.agent_id for row in report.resend} == {
            str(first.agent_id),
            str(second.agent_id),
        }
        labels = {row.agent for row in report.resend}
        assert labels == {
            f"Support [{str(first.agent_id)[:8]}]",
            f"Support [{str(second.agent_id)[:8]}]",
        }
        assert {row.name for row in report.by_agent} == labels

    def test_platform_work_is_not_the_starter_agents(self) -> None:
        own = _run("Support")
        maintenance = _run("Support", agent_id=own.agent_id, system_role="memory_maintenance")

        report = _assemble([own, maintenance], {}, {})

        rows = {row.agent: row for row in report.resend}
        assert set(rows) == {"Support", "platform: memory_maintenance"}
        platform = rows["platform: memory_maintenance"]
        assert (platform.agent_id, platform.system_role) == (None, "memory_maintenance")

    def test_a_registered_tool_is_counted_under_its_capability(self) -> None:
        run = _run("Support")
        with patch(
            "app.services.tool_output_report._capability_of_tool",
            return_value={"web_search": "web_search_capability"},
        ):
            report = _assemble(
                [run], {run.id: [CallSize(run.id, "search", "web_search", False, 10)]}, {}
            )

        assert report.by_capability[0].name == "web_search_capability"

    def test_the_size_tables_list_the_largest_first_up_to_top(self) -> None:
        run = _run("Support")
        calls = {
            run.id: [
                CallSize(run.id, "small", None, False, 10),
                CallSize(run.id, "large", None, False, 10_500),
            ]
        }
        report = _assemble([run], calls, {}, top=1)

        assert [(row.name, row.over_threshold) for row in report.by_tool] == [("large", 1)]

    def test_a_test_run_uses_its_own_spec_and_a_published_run_its_versions(self) -> None:
        version = uuid4()
        published = _run("Support", version=version, capabilities=None)
        orphaned = _run("Support", capabilities=None)
        tested = _run("Support", capabilities=[{"id": "tool_output_limits"}])
        report = _assemble(
            [published, orphaned, tested],
            {},
            {},
            versions={version: [{"id": "compaction", "config": {"strategy": "tiered"}}]},
        )

        assert {
            (row.tool_output_limits, row.compaction, row.overstated) for row in report.resend
        } == {
            ("none", "tiered", True),
            ("unknown", "unknown", True),
            ("spill", "none", False),
        }


class TestRendering:
    def test_no_runs_says_so(self) -> None:
        text = render_text(_assemble([], {}, {}))
        assert "No runs in this window." in text
        assert "Assumptions" not in text

    def test_the_text_states_its_assumptions_and_marks_overstated_rows(self) -> None:
        run = _run("Coder", capabilities=[{"id": "compaction", "config": {"strategy": "tiered"}}])
        report = _assemble(
            [run],
            {run.id: [CallSize(run.id, "read", None, False, 12_000)]},
            {run.id: [RecordedRequest(run.id, 0, 100, 0, 0, ["read"])]},
        )

        text = render_text(report)

        assert "characters / 4" in text
        assert "Not measured: how replacing results would change prompt caching" in text
        assert "Coder !" in text
        assert "Calls placed exactly: 100.0%" in text

    def test_names_cannot_forge_rows_or_drive_the_terminal(self) -> None:
        run = _run(
            "Evil\n  Forged  none/none  1/1\x1b]0;owned\x07",
            capabilities=[{"id": "compaction", "config": {"strategy": "x\x1b[2J"}}],
        )
        report = _assemble(
            [run],
            {run.id: [CallSize(run.id, "read\r\u202eexe", None, False, 10)]},
            {run.id: [RecordedRequest(run.id, 0, 100, 0, 0, ["read\r\u202eexe"])]},
        )

        text = render_text(report)

        assert not any(char in text for char in "\x1b\x07\r\u202e")
        assert not any(line.startswith("  Forged") for line in text.splitlines())
        assert "Evil\\n  Forged" in text
        assert "x\\x1b[2J" in text
        assert "read\\r\\u202eexe" in text

    def test_the_json_carries_the_same_figures_and_assumptions(self) -> None:
        run = _run("Support")
        report = _assemble(
            [run],
            {run.id: [CallSize(run.id, "search", None, False, 10)]},
            {run.id: [RecordedRequest(run.id, 0, 0, 0, 0, ["search"])]},
        )

        data = json.loads(json.dumps(as_json(report)))

        assert data["started_from"] == "2026-11-01"
        assert data["resend"][0]["share"] is None
        assert any("characters / 4" in line for line in data["assumptions"])


class TestLegacyBindingValues:
    @pytest.mark.parametrize("config", [[], "invalid", 3, {"action": False}, {"action": []}])
    def test_malformed_legacy_settings_are_unknown_instead_of_coerced(self, config: object) -> None:
        assert bindings_of([{"id": "tool_output_limits", "config": config}]) == ("unknown", "none")

    def test_empty_legacy_setting_uses_the_default(self) -> None:
        assert bindings_of([{"id": "compaction", "config": {"strategy": ""}}]) == (
            "none",
            "summarize",
        )


class TestBuild:
    async def test_the_largest_date_is_refused_without_overflowing(self) -> None:
        with pytest.raises(ValidationError):
            await ToolOutputReportService(MagicMock()).build(
                uuid4(), started_from=date(2026, 11, 1), ended=date.max
            )

    async def test_a_window_ending_before_it_starts_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            await ToolOutputReportService(MagicMock()).build(
                uuid4(), started_from=date(2026, 11, 2), ended=date(2026, 11, 1)
            )

    async def test_an_unknown_organization_is_refused(self) -> None:
        with (
            patch(
                "app.services.tool_output_report.organization_repo.get_by_id",
                AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError),
        ):
            await ToolOutputReportService(MagicMock()).build(
                uuid4(), started_from=date(2026, 11, 1), ended=date(2026, 11, 1)
            )

    async def test_version_lookups_are_bounded_for_a_large_report(self) -> None:
        runs = [_run("Support", version=uuid4()) for _ in range(501)]
        versions = AsyncMock(return_value={})
        with (
            patch(
                "app.services.tool_output_report.organization_repo.get_by_id",
                AsyncMock(return_value=object()),
            ),
            patch(
                "app.services.tool_output_report.report_repo.list_runs",
                AsyncMock(return_value=runs),
            ),
            patch(
                "app.services.tool_output_report.report_repo.list_call_sizes",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.tool_output_report.report_repo.list_requests",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.tool_output_report.report_repo.count_turns",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.tool_output_report.report_repo.list_inherited_sizes",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.tool_output_report.report_repo.list_parked",
                AsyncMock(return_value=set()),
            ),
            patch(
                "app.services.tool_output_report.report_repo.list_version_capabilities", versions
            ),
        ):
            await ToolOutputReportService(MagicMock()).build(
                uuid4(), started_from=date(2026, 11, 1), ended=date(2026, 11, 1)
            )
        batches = [call.kwargs["version_ids"] for call in versions.await_args_list]
        assert [len(batch) for batch in batches] == [500, 1]
        assert {version for batch in batches for version in batch} == {
            run.agent_version_id for run in runs
        }
