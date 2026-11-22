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
MAKEFILE = REPO_ROOT / "Makefile"

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


class TestPullRequestsAndMergeQueue:
    """PRs get scoped feedback; the merge queue runs everything before `t3` (2026-11-21)."""

    def test_pull_requests_and_the_merge_queue_trigger_ci(self, triggers: dict[str, Any]) -> None:
        assert set(triggers) == {"pull_request", "merge_group", "push", "workflow_dispatch"}
        assert triggers["push"] == {"tags": ["v*"]}, (
            "Pushes to `t3` arrive through the merge queue."
        )

    def test_only_a_pull_request_run_is_cancelled_by_a_newer_commit(
        self, workflow: dict[str, Any]
    ) -> None:
        assert (
            workflow["concurrency"]["cancel-in-progress"]
            == "${{ github.event_name == 'pull_request' }}"
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

    def test_every_suite_is_gated_by_scope_alone(self, workflow: dict[str, Any]) -> None:
        """A merge-queue, tag or dispatch run emits no scope outputs, so it runs every suite."""
        assert workflow["jobs"]["changes"]["outputs"]["full"] == "true"

    def test_no_step_classifies_a_push_to_t3(self, workflow: dict[str, Any]) -> None:
        """Only the merge queue lands on `t3`, and it runs every suite."""
        steps = workflow["jobs"]["changes"]["steps"]
        assert "pushed" not in {step.get("id") for step in steps}
        outputs = workflow["jobs"]["changes"]["outputs"]
        assert not any("steps.pushed" in str(value) for value in outputs.values())


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
        # CI steps call Makefile targets (`test_ci_parity.py`), so the check is the
        # `ci-browser-runtime-check` target, and its recipe must hold the probe.
        target = "ci-browser-runtime-check"
        verified = [
            i for i, step in enumerate(steps) if step.get("run", "").strip() == f"make {target}"
        ]
        assert len(verified) == 1 and verified[0] < run
        assert not steps[verified[0]].get("continue-on-error", False)
        lines = MAKEFILE.read_text().splitlines()
        start = lines.index(f"{target}:") + 1
        recipe = []
        for line in lines[start:]:
            if not line.startswith("\t"):
                break
            recipe.append(line.strip())
        assert recipe == [
            'test -x "$(T3OS_TEST_CHROMIUM_EXECUTABLE)"',
            '"$(T3OS_TEST_CHROMIUM_EXECUTABLE)" --version',
        ]


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
