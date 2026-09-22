"""A blocked deploy queue has to be noticed by something that is not a person.

`deploy.yml` serializes on `deploy-production` and never cancels a run in
flight, which is right: half a deploy is a stack whose API has been rebuilt and
whose migrations have not. The cost is that a run parked at the `production`
environment's approval gate counts as in flight and holds that group, so every
later run sits `pending` with no jobs and is cancelled by the next one. Thirteen
days of merges went that way with no failed run, no notification and a
production host a fortnight behind `main` (#1832).

`deploy-queue.yml` is the mechanism that breaks the silence. What it must not
become is another thing that deploys: it cancels and it reports, and the
properties below are the ones whose loss would put it back where it started -
joining the group it watches, or being able to approve what it found.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _workflow(name: str) -> dict[str, Any]:
    with (WORKFLOWS / name).open() as handle:
        loaded: dict[str, Any] = yaml.safe_load(handle)
    return loaded


@pytest.fixture(scope="module")
def watcher() -> dict[str, Any]:
    return _workflow("deploy-queue.yml")


@pytest.fixture(scope="module")
def deploy() -> dict[str, Any]:
    return _workflow("deploy.yml")


@pytest.fixture(scope="module")
def triggers(watcher: dict[str, Any]) -> dict[str, Any]:
    """The `on:` block - keyed by `True`, because PyYAML reads a bare `on` as a boolean."""
    block: dict[str, Any] = watcher[True]
    return block


class TestTheQueueIsWatchedFromOutsideIt:
    def test_the_watcher_does_not_join_the_group_it_watches(
        self, watcher: dict[str, Any], deploy: dict[str, Any]
    ) -> None:
        """Sharing the group would make the watcher queue behind the run it exists
        to cancel, which is the deadlock it was written to break."""
        assert deploy["concurrency"]["group"] == "deploy-production"
        assert watcher["concurrency"]["group"] != deploy["concurrency"]["group"]

    def test_the_deploy_still_refuses_to_cancel_one_in_flight(self, deploy: dict[str, Any]) -> None:
        """The serialization is correct and is not what #1832 asks to change."""
        assert deploy["concurrency"]["cancel-in-progress"] is False

    def test_it_runs_on_a_schedule_and_by_hand(self, triggers: dict[str, Any]) -> None:
        assert "schedule" in triggers
        assert "workflow_dispatch" in triggers
        assert "push" not in triggers


class TestItCancelsAndReportsAndNothingElse:
    def test_it_may_cancel_a_run_and_open_an_issue(self, watcher: dict[str, Any]) -> None:
        job = watcher["jobs"]["queue"]
        assert job["permissions"]["actions"] == "write"
        assert job["permissions"]["issues"] == "write"

    def test_it_cannot_write_to_the_repository(self, watcher: dict[str, Any]) -> None:
        """An approval is a person deciding to change a server."""
        assert watcher["permissions"]["contents"] == "read"
        assert watcher["jobs"]["queue"]["permissions"]["contents"] == "read"

    def test_it_bounds_its_own_runtime(self, watcher: dict[str, Any]) -> None:
        """The default is six hours, and this one runs every six (#364)."""
        assert watcher["jobs"]["queue"]["timeout-minutes"] <= 30

    def test_it_acts_only_on_a_run_that_is_waiting_for_an_approval(
        self, watcher: dict[str, Any]
    ) -> None:
        """`queued` and `pending` are the runs *behind* the block: they hold
        nothing, have no jobs, and clear themselves once the group is free."""
        script = watcher["jobs"]["queue"]["steps"][0]["with"]["script"]
        assert "runsOf('waiting')" in script
        assert "cancelWorkflowRun" in script
        # It neither answers the gate nor starts a deploy of its own.
        assert "reviewPendingDeploymentsForRun" not in script
        assert "createWorkflowDispatch" not in script

    def test_the_threshold_comes_from_the_environment(self, watcher: dict[str, Any]) -> None:
        """A `${{ }}` is substituted into the source before Node parses it."""
        step = watcher["jobs"]["queue"]["steps"][0]
        assert "STALE_AFTER_HOURS" in step["env"]
        assert "${{" not in step["with"]["script"]
