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
    inherited GitHub's default of 360 minutes. Nothing has been observed to stall;
    the point is that if one did, its required check would be held for six hours
    and nothing in this repository would end it sooner (#364).

Neither is testable by running CI, which is the whole difficulty: a workflow that
does not trigger produces no evidence at all, and a bound is only exercised by the
incident it exists to shorten.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# The ceiling on any one job's `timeout-minutes`. Set against the slowest job this
# workflow has ever run - `e2e` at 8m01s on run 31116003994, a full matrix on `main` -
# with room for a cold cache on top. A bound much beyond that is the 360-minute
# default with extra steps.
MAX_TIMEOUT_MINUTES = 30


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


class TestEveryPullRequestIsChecked:
    """A pull request that runs nothing must not be possible to open."""

    def test_the_pull_request_trigger_matches_whatever_the_base_is(
        self, triggers: dict[str, Any]
    ) -> None:
        assert "pull_request" in triggers, "CI no longer runs on pull requests at all"
        event = triggers["pull_request"]
        filters = sorted(set(event or {}) & {"branches", "branches-ignore", "paths"})
        assert not filters, (
            f"the `pull_request` trigger filters on {filters}. A `branches` filter matches "
            "the base, so a pull request stacked on a feature branch would run no jobs and "
            "report an empty checks list rather than a red one - #359. A `paths` filter is "
            "worse: the required checks never report and the merge button stays grey."
        )

    def test_no_trigger_is_filtered_by_path(self, triggers: dict[str, Any]) -> None:
        """A job-level `if:` skips and satisfies a required check; a `paths:` filter never reports.

        `docs/branching.md` records why the change-scope gate had to be written as
        the former. This is the assertion that keeps it written that way.

        It reads the `on:` block, because that is the only place GitHub looks for a
        path filter. The first spelling of this asserted `"paths" not in workflow`
        against the *top level* of the file, where the schema has no `paths` key to
        find - so it passed whatever anybody wrote, a `paths:` under `push`
        included, and guarded nothing.
        """
        filtered = sorted(
            event
            for event, config in triggers.items()
            if {"paths", "paths-ignore"} & set(config or {})
        )
        assert not filtered, (
            f"the {filtered} trigger(s) filter on a path. A filtered-out workflow never posts "
            "its required contexts at all, so `main`'s ruleset waits for checks that will "
            "never arrive and the merge button stays grey forever - see docs/branching.md. "
            "Gate the individual jobs on `changes` instead, where a skip still satisfies the "
            "check."
        )


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
