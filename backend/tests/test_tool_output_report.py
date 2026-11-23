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
        assert bindings_of(None) == ("none", "none")
        assert bindings_of([{"id": "web_search"}]) == ("none", "none")

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


def _run(agent: str, *, run_id: UUID | None = None, capabilities=None) -> ReportRun:
    return ReportRun(run_id or uuid4(), uuid4(), agent, None, None, capabilities)


def _assemble(runs, calls, requests, *, turns=None, versions=None, top=20):
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

        assert (report.runs, report.runs_with_manifest, report.tool_calls) == (1, 0, 1)
        assert report.matching.without_manifest == 1
        assert report.by_tool[0].sizes.max == 700
        row = report.resend[0]
        assert (row.runs, row.runs_with_manifest, row.share) == (1, 0, None)

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
        published = ReportRun(uuid4(), uuid4(), "Support", version, None, None)
        tested = _run("Support", capabilities=[{"id": "tool_output_limits"}])
        report = _assemble(
            [published, tested],
            {},
            {},
            versions={version: [{"id": "compaction", "config": {"strategy": "tiered"}}]},
        )

        assert {(row.tool_output_limits, row.compaction) for row in report.resend} == {
            ("none", "tiered"),
            ("spill", "none"),
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


class TestBuild:
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
