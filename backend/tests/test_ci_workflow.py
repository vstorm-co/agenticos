"""Properties of `ci.yml` itself whose failure mode is a build that looks fine.

`test_ci_parity.py` next door asks whether `make check` runs what CI runs. This
file asks a different question about the same file: whether CI *runs at all*, and
whether it is bounded when it does.

  - `pull_request: branches: [main, master]` matches on the **base**, so a pull
    request stacked on a feature branch matched no trigger and executed nothing.
    The checks list was then empty rather than red - "no checks reported", which
    reads as *starting* rather than *absent* - and four pull requests merged that
    way in one day (#359).
  - `changes` was the only job declaring `timeout-minutes`, so every other job
    inherited GitHub's default of 360 minutes, and a stalled required check would
    have been held for six hours with nothing in this repository ending it sooner
    (#364). That bound was written against a stall nobody had seen yet; fourteen
    e2e runs then hit it in four days (#879).
  - Which is how the third property arrived. A job ended by its own bound reports
    `cancelled`, indistinguishable at a glance from a run somebody superseded - so
    a step reaching a third-party apt mirror on every run is a step that can put a
    green diff behind a conclusion that reads as somebody else's doing.

None is testable by running CI, which is the whole difficulty: a workflow that does
not trigger produces no evidence at all, and a bound is only exercised by the
incident it exists to shorten.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# The ceiling on any one job's `timeout-minutes`. Set against the slowest job this
# workflow runs - `test`, which runs the suite twice. The 18,711-test native-client
# branch reached only 72% of its first pass within 45 minutes on two workers;
# four workers and 90 minutes leave room for both passes without an unbounded job.
MAX_TIMEOUT_MINUTES = 90


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    with WORKFLOW.open() as handle:
        loaded: dict[str, Any] = yaml.safe_load(handle)
    return loaded


@pytest.fixture(scope="module")
def triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    """The `on:` block.

    Keyed by `True`, not by `"on"`. YAML 1.1 resolves a bare `on` to a boolean and
    PyYAML implements 1.1, so the obvious spelling of this lookup raises `KeyError`
    against a workflow that is perfectly valid to GitHub.
    """
    block: dict[str, Any] = workflow[True]
    return block


class TestPullRequestsRunNoCI:
    """The PR quick check runs in the T3 session and is pasted into the PR (2026-11-16)."""

    def test_pull_requests_trigger_nothing(self, triggers: dict[str, Any]) -> None:
        assert "pull_request" not in triggers, (
            "CI runs after merge and on release tags only; the lead reads the quick "
            "check output pasted into each pull request before merging."
        )

    def test_no_trigger_is_filtered_by_path(self, triggers: dict[str, Any]) -> None:
        """No trigger may carry a path filter.

        A path filter on pull requests hides their required contexts, including stacked
        PRs. On pushes, docs-only merges are classified by the `changes` job instead,
        against the last successful `t3` run, so a cancelled run's commits stay covered.
        """
        filtered = {
            event: config
            for event, config in triggers.items()
            if {"paths", "paths-ignore"} & set(config or {})
        }
        assert not filtered, f"path filters appear on {sorted(filtered)}."

    def test_heavy_suites_run_after_every_merge_and_release(
        self, triggers: dict[str, Any], workflow: dict[str, Any]
    ) -> None:
        """Every `t3` push and `v*` tag runs the full suite."""
        assert triggers["push"]["branches"] == ["t3"]
        assert triggers["push"]["tags"] == ["v*"]
        assert workflow["jobs"]["changes"]["outputs"]["full"] == (
            "${{ github.event_name == 'push' }}"
        ), "The heavy suites run on pushes (merges and tags), never on pull requests."

    def test_a_push_classifies_against_the_last_successful_t3_run(
        self, workflow: dict[str, Any]
    ) -> None:
        """With cancel-in-progress, `github.event.before` may be a commit never tested."""
        step = next(
            step for step in workflow["jobs"]["changes"]["steps"] if step.get("id") == "pushed"
        )
        assert "status=success" in step["run"]
        assert "github.event.before" not in step["run"]
        assert "merge-base --is-ancestor" in step["run"]


class TestWorkerBackedJourneys:
    """A started worker must enable the journeys' durable-completion assertions."""

    def test_the_started_worker_enables_completion_assertions(
        self, workflow: dict[str, Any]
    ) -> None:
        job = workflow["jobs"]["e2e-shards"]
        steps = job["steps"]
        worker = next(i for i, step in enumerate(steps) if "-m app.worker" in step.get("run", ""))
        run = next(i for i, step in enumerate(steps) if "test:e2e" in step.get("run", ""))
        assert worker < run
        environment = {**workflow.get("env", {}), **job.get("env", {}), **steps[run].get("env", {})}
        assert environment.get("E2E_WORKER") == "1", (
            "The CI worker is running, but E2E_WORKER=1 is absent: workflow journeys skip "
            "their completion assertions and teardown can cancel work still being settled."
        )


class TestNativeBrowserAcceptance:
    """Full backend CI must execute the native credential and teaching cases."""

    def test_backend_cases_receive_a_verified_browser(self, workflow: dict[str, Any]) -> None:
        job = workflow["jobs"]["test-shard"]
        steps = job["steps"]
        run = next(i for i, step in enumerate(steps) if step.get("run", "").strip() == "make test")
        assert steps[run]["env"]["BACKEND_SHARD"] == "${{ matrix.shard }}/3"
        environment = {**workflow.get("env", {}), **job.get("env", {}), **steps[run].get("env", {})}
        assert environment.get("T3OS_TEST_CHROMIUM_EXECUTABLE") == "/usr/bin/google-chrome"
        verified = [
            i
            for i, step in enumerate(steps)
            if 'test -x "$T3OS_TEST_CHROMIUM_EXECUTABLE"' in step.get("run", "")
            and '"$T3OS_TEST_CHROMIUM_EXECUTABLE" --version' in step.get("run", "")
        ]
        assert len(verified) == 1 and verified[0] < run
        assert not steps[verified[0]].get("continue-on-error", False)


class TestEveryJobBoundsItsOwnRuntime:
    """Six hours of a hung job is a required check nothing in this repository ends."""

    def test_every_job_declares_a_timeout(self, workflow: dict[str, Any]) -> None:
        missing = sorted(
            name for name, job in workflow["jobs"].items() if "timeout-minutes" not in job
        )
        assert not missing, (
            f"{missing} declare no `timeout-minutes`, so each inherits GitHub's default of "
            "360 minutes - #364. Give the job a bound several times its observed worst case."
        )

    def test_no_timeout_is_so_generous_it_bounds_nothing(self, workflow: dict[str, Any]) -> None:
        excessive = sorted(
            name
            for name, job in workflow["jobs"].items()
            if job.get("timeout-minutes", 0) > MAX_TIMEOUT_MINUTES
        )
        assert not excessive, (
            f"{excessive} allow more than {MAX_TIMEOUT_MINUTES} minutes, which is several "
            "times the slowest job this workflow has ever run."
        )


class TestNoStepInstallsSystemPackages:
    """The one stall this workflow has actually had, and the shape of it.

    `playwright install --with-deps` runs `apt-get` against the runner's Azure
    mirror. When that mirror is unreachable apt falls back to the public archive
    and stalls with no bound of its own - fourteen `e2e` runs between 14 and 18
    August, every one in that step, every one ended at 25 minutes by the job's
    `timeout-minutes` and reported as `cancelled` (#879).

    It is worth a test rather than a comment because re-adding the flag is the
    obvious thing to do: it is what Playwright's own documentation recommends, it
    is what the step said for months, and on a runner whose mirror answers it
    costs seconds and looks harmless.
    """

    def test_no_step_shells_out_to_apt(self, workflow: dict[str, Any]) -> None:
        offenders = [
            f"{job_name}/{step.get('name', step['run'].splitlines()[0])}"
            for job_name, job in workflow["jobs"].items()
            for step in job.get("steps", [])
            if "run" in step and ("--with-deps" in step["run"] or "apt-get" in step["run"])
        ]
        assert not offenders, (
            f"{offenders} install system packages during the run. apt reaches a mirror this "
            "repository does not control and stalls unbounded when it is unavailable, which "
            "ends the job at its `timeout-minutes` and reports `cancelled` rather than a "
            "failure naming the step - #879. The runner image already carries every library "
            "Chromium links against."
        )


class TestTyDiagnosticsAreVisibleOnGitHub:
    """A `ty` diagnostic's default output is plain text on stdout, so a run
    carrying 61 of them looked identical to one with zero: green check, no
    annotation, nothing pointing a reader at the log - true whether or not the
    diagnostic failed the run.

    `ty` switches to GitHub's own `::warning file=…,line=…::` annotation syntax
    when `TY_OUTPUT_FORMAT=github` is set in its environment - the `lint` job sets
    it, so the exact same `make lint-backend` call surfaces every diagnostic as an
    inline annotation on the run and the diff. This is what stops that setting
    silently reverting; `test_coverage_gate.py::TestTypeGateMatchesCoverageGate`
    is the matching guard for `error-on-warning`, which now decides whether that
    same diagnostic also fails the run.
    """

    def test_the_lint_job_asks_ty_for_github_annotations(self, workflow: dict[str, Any]) -> None:
        env = workflow["jobs"]["lint"].get("env", {})
        assert env.get("TY_OUTPUT_FORMAT") == "github", (
            "the `lint` job no longer sets TY_OUTPUT_FORMAT=github, so a ty diagnostic "
            "goes back to being plain text on stdout - a green check with nothing on the "
            "run or the diff pointing anyone at it."
        )
