"""The arithmetic the load suite reports its verdict from.

The harness is not application code and carries no coverage gate, but the
numbers it prints are quoted in a delivery conversation - so the parts that turn
samples into a claim are held shut here. What is tested is exactly that: the
percentile rule, what latency is measured over, the mix's proportions, and that a
scenario which produced nothing reads as unmeasured rather than as a pass.

Imported by path, the way `test_check_comments.py` reaches the repository's guard
scripts: `loadtest/` is a console tool outside the backend package.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS = REPO_ROOT / "loadtest"


def _load(name: str) -> ModuleType:
    """Import one harness module, with its siblings importable by bare name."""
    if str(HARNESS) not in sys.path:
        sys.path.insert(0, str(HARNESS))
    spec = importlib.util.spec_from_file_location(name, HARNESS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


metrics = _load("metrics")
scenario = _load("scenario")
thresholds = _load("thresholds")
probes = _load("probes")
seed = _load("seed")


def _sample(**overrides: object) -> object:
    fields: dict[str, object] = {
        "workload": "api_read",
        "phase": "sustain",
        "started_at": 0.0,
        "duration_ms": 10.0,
        "ok": True,
    }
    return metrics.Sample(**{**fields, **overrides})


class TestThePercentileRule:
    def test_a_percentile_is_a_measurement_and_not_a_point_between_two(self) -> None:
        """Nearest rank: an interpolated p99 is a number nothing observed."""
        values = [float(number) for number in range(1, 101)]

        assert metrics.percentile(values, 0.99) == 99.0
        assert metrics.percentile(values, 0.50) == 50.0
        assert metrics.percentile(values, 1.0) == 100.0

    def test_the_smallest_sample_is_its_own_every_percentile(self) -> None:
        assert metrics.percentile([7.0], 0.99) == 7.0

    def test_no_samples_is_zero_rather_than_an_error(self) -> None:
        assert metrics.percentile([], 0.95) == 0.0

    @pytest.mark.parametrize("fraction", [0.0, 1.5, -0.1])
    def test_a_fraction_outside_the_range_is_refused(self, fraction: float) -> None:
        with pytest.raises(ValueError, match="fraction"):
            metrics.percentile([1.0], fraction)


class TestWhatLatencyIsMeasuredOver:
    def test_a_refusal_never_enters_the_distribution(self) -> None:
        """A request refused in 3ms is not a fast request.

        Letting it in is how a run that fell over reports its best percentiles.
        """
        samples = [
            _sample(duration_ms=400.0),
            _sample(duration_ms=3.0, ok=False, status=503),
            _sample(duration_ms=3.0, ok=False, status=503),
        ]

        summary = metrics.summarize(samples, label="x", seconds=10.0)
        entry = summary.workload("api_read")

        assert entry.latency.count == 1
        assert entry.latency.p95 == 400.0
        assert entry.failed == 2

    def test_a_failure_is_counted_and_named(self) -> None:
        samples = [_sample(ok=False, status=429), _sample(ok=False, detail="timed out")]

        entry = metrics.summarize(samples, label="x", seconds=1.0).workload("api_read")

        assert entry.error_rate == 1.0
        assert dict(entry.failures) == {"HTTP 429": 1, "timed out": 1}

    def test_a_socket_that_produced_no_status_still_has_a_reason(self) -> None:
        entry = metrics.summarize([_sample(ok=False)], label="x", seconds=1.0).workload("api_read")

        assert dict(entry.failures) == {"no response": 1}

    def test_throughput_is_completed_requests_over_the_window(self) -> None:
        summary = metrics.summarize([_sample() for _ in range(60)], label="x", seconds=30.0)

        assert summary.throughput == 2.0

    def test_a_window_of_no_time_reports_no_throughput_rather_than_dividing_by_it(self) -> None:
        assert metrics.summarize([], label="x", seconds=0.0).throughput == 0.0


class TestTheMix:
    def test_the_shares_are_the_stated_proportions_over_a_window(self) -> None:
        shares = scenario.normalized(scenario.MIX)
        picked = [scenario.pick(index, shares) for index in range(2000)]

        for entry in shares:
            assert abs(picked.count(entry.name) / 2000 - entry.share) < 0.01

    def test_the_workloads_are_interleaved_rather_than_taken_in_blocks(self) -> None:
        """A mix walked in order is four workloads in sequence, not one mixed load."""
        shares = scenario.normalized(scenario.MIX)
        first = [scenario.pick(index, shares) for index in range(12)]

        assert len(set(first)) >= 4

    def test_shares_that_do_not_sum_to_one_are_scaled_rather_than_refused(self) -> None:
        mix = (
            scenario.WorkloadShare(name="a", share=3.0, description=""),
            scenario.WorkloadShare(name="b", share=1.0, description=""),
        )

        scaled = scenario.normalized(mix)

        assert [entry.share for entry in scaled] == [0.75, 0.25]

    def test_a_mix_with_nothing_in_it_is_refused(self) -> None:
        with pytest.raises(ValueError, match="positive share"):
            scenario.normalized(())

    def test_the_phases_lay_out_end_to_end(self) -> None:
        marks = scenario.schedule(scenario.PHASES)

        assert marks[0][1] == 0.0
        for earlier, later in itertools.pairwise(marks):
            assert earlier[2] == later[1]

    def test_a_moment_resolves_to_the_phase_it_falls_in(self) -> None:
        assert scenario.phase_at(0.0).name == "ramp"
        assert scenario.phase_at(61.0).name == "sustain"
        assert scenario.phase_at(10_000.0) is None


class TestTheVerdict:
    def test_a_measurement_inside_the_limit_passes(self) -> None:
        summary = metrics.summarize(
            [_sample(duration_ms=50.0) for _ in range(100)], label="x", seconds=10.0
        )

        verdict = thresholds.measure(summary, _threshold("api_read", "p95", 300.0))

        assert verdict.met
        assert verdict.counted == 100

    def test_a_measurement_over_the_limit_fails(self) -> None:
        summary = metrics.summarize(
            [_sample(duration_ms=900.0) for _ in range(100)], label="x", seconds=10.0
        )

        assert not thresholds.measure(summary, _threshold("api_read", "p95", 300.0)).met

    def test_a_workload_that_produced_nothing_is_not_a_pass(self) -> None:
        """A run that skipped a scenario and reported green for it is the whole point."""
        summary = metrics.summarize([], label="x", seconds=10.0)

        verdict = thresholds.measure(summary, _threshold("api_read", "p95", 300.0))

        assert not verdict.met
        assert verdict.counted == 0

    def test_a_workload_with_no_successful_sample_is_not_a_pass_either(self) -> None:
        summary = metrics.summarize(
            [_sample(ok=False, status=500) for _ in range(10)], label="x", seconds=10.0
        )

        verdict = thresholds.measure(summary, _threshold("api_read", "p95", 300.0))

        assert not verdict.met
        assert verdict.counted == 0

    def test_an_error_rate_threshold_reads_the_rate_and_not_a_latency(self) -> None:
        samples = [_sample() for _ in range(99)] + [_sample(ok=False, status=500)]
        summary = metrics.summarize(samples, label="x", seconds=10.0)

        verdict = thresholds.measure(summary, _threshold("api_read", "error_rate", 0.001))

        assert verdict.measured == pytest.approx(0.01)
        assert not verdict.met

    def test_a_first_token_threshold_reads_the_streams_and_not_the_whole_turn(self) -> None:
        samples = [
            metrics.Sample(
                workload="chat_stream",
                phase="sustain",
                started_at=0.0,
                duration_ms=4000.0,
                ok=True,
                first_token_ms=400.0,
            )
        ]
        summary = metrics.summarize(samples, label="x", seconds=10.0)

        verdict = thresholds.measure(summary, _threshold("chat_stream", "first_token_p95", 1500.0))

        assert verdict.measured == 400.0
        assert verdict.met

    def test_every_proposed_threshold_names_a_workload_the_mix_issues(self) -> None:
        """A threshold on a workload nothing runs is a threshold that passes by absence."""
        issued = {entry.name for entry in scenario.MIX}

        assert {row.workload for row in thresholds.PROPOSED} <= issued

    def test_every_proposed_threshold_says_why_it_is_where_it_is(self) -> None:
        for row in thresholds.PROPOSED:
            assert len(row.rationale) > 60, row.workload

    def test_judging_a_run_answers_for_every_threshold(self) -> None:
        summary = metrics.summarize([_sample()], label="x", seconds=1.0)

        assert len(thresholds.judge(summary)) == len(thresholds.PROPOSED)


def _threshold(workload: str, metric: str, limit: float) -> object:
    return thresholds.Threshold(
        workload=workload,
        metric=metric,
        limit=limit,
        unit="ms" if metric != "error_rate" else "fraction",
        rationale="x" * 61,
    )


class TestWhenARequestFinished:
    def test_a_sample_knows_when_it_came_back(self) -> None:
        sample = _sample(started_at=10.0, duration_ms=2500.0)

        assert sample.finished_at == 12.5

    def test_completions_are_counted_in_the_window_they_landed_in(self) -> None:
        """A request issued inside a phase can finish well outside it.

        Which is exactly what happens when the server is behind - so dividing a
        phase's issued count by the phase's length reproduces the offered
        schedule and calls it throughput.
        """
        inside = _sample(started_at=59.0, duration_ms=500.0)
        spilled = _sample(started_at=59.0, duration_ms=30_000.0)

        landed = metrics.completed_between([inside, spilled], 0.0, 60.0)

        assert landed == [inside]


class TestReadingCpuTime:
    @pytest.mark.parametrize(
        ("printed", "seconds"),
        [
            ("01:02:03", 3723.0),
            ("12:34.56", 754.56),
            ("1-02:03:04", 93784.0),
            ("0:00.00", 0.0),
        ],
    )
    def test_both_spellings_of_cpu_time_parse(self, printed: str, seconds: float) -> None:
        """procps prints `[[DD-]HH:]MM:SS` and BSD `ps` prints `MM:SS.ss`."""
        assert probes.cpu_seconds(printed) == pytest.approx(seconds)

    @pytest.mark.parametrize("printed", ["", "  ", "nonsense", "x-01:02"])
    def test_anything_unreadable_answers_none_rather_than_a_number(self, printed: str) -> None:
        assert probes.cpu_seconds(printed) is None

    def test_the_first_reading_is_not_counted_as_an_idle_moment(self) -> None:
        """It has nothing to difference against, so it carries memory only."""
        samples = [
            probes.ResourceSample(at=0.0, cpu_percent=-1.0, rss_mb=120.0),
            probes.ResourceSample(at=2.0, cpu_percent=64.0, rss_mb=180.0),
        ]

        cpu, peak_rss, final_rss = probes.summarize(samples)

        assert (cpu, peak_rss, final_rss) == (64.0, 180.0, 180.0)

    def test_nothing_sampled_reports_zeros_rather_than_raising(self) -> None:
        assert probes.summarize([]) == (0.0, 0.0, 0.0)

    def test_the_peak_pool_is_the_most_it_ever_held(self) -> None:
        held = [
            probes.PoolSample(at=0.0, connections=4, active=1),
            probes.PoolSample(at=2.0, connections=27, active=7),
        ]

        assert probes.peak_pool(held) == (27, 7)
        assert probes.peak_pool([]) == (0, 0)


class TestTheDriverSizesItselfToTheScenario:
    def test_the_connection_ceiling_follows_the_peak_rate(self) -> None:
        """Capped below this, the client queues and the run measures itself."""
        assert scenario.peak_concurrency(scenario.PHASES, slowest_request_seconds=90.0) == 36 * 90


class TestSeedingRefusesAPartialCorpus:
    def test_a_failure_the_command_printed_is_not_a_success(self) -> None:
        """`rag-ingest` counts a per-file failure, prints it, and exits zero."""
        output = "  x record-00003.txt: no embedding credential\nDone: 39 ingested\nFailed: 1 files"

        with pytest.raises(RuntimeError, match="failed to index"):
            seed._accounted(output, expected=40)

    def test_files_the_command_never_mentioned_are_refused_too(self) -> None:
        with pytest.raises(RuntimeError, match="accounted for neither"):
            seed._accounted("Done: 12 ingested", expected=40)

    def test_a_complete_corpus_is_accepted(self) -> None:
        assert seed._accounted("Done: 40 ingested", expected=40) == 40

    def test_documents_already_present_count_as_accounted_for(self) -> None:
        """`new_only` skips what is unchanged, which is still a complete index."""
        assert seed._accounted("Done: 5 ingested, 35 skipped", expected=40) == 40
