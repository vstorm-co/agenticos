"""Properties of `ci.yml` itself whose failure mode is a build that looks fine.

`test_ci_parity.py` next door asks whether `make check` runs what CI runs. This
file asks a different question about the same file: whether CI *runs at all*.

`pull_request: branches: [main, master]` matches on the **base**, so a pull request
stacked on a feature branch matched no trigger and executed nothing. The checks list
was then empty rather than red - "no checks reported", which reads as *starting*
rather than *absent* - and four pull requests merged that way in one day (#359).

That is not testable by running CI, which is the whole difficulty: a workflow that
does not trigger produces no evidence at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


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

    def test_the_whole_workflow_is_not_filtered_by_path(self, workflow: dict[str, Any]) -> None:
        """A job-level `if:` skips and satisfies a required check; a `paths:` filter never reports.

        `docs/branching.md` records why the change-scope gate had to be written as
        the former. This is the assertion that keeps it written that way.
        """
        assert "paths" not in workflow, (
            "a workflow-level `paths:` filter stops the required contexts being posted, so "
            "`main`'s ruleset waits for checks that will never arrive - see "
            "docs/branching.md. Gate the individual jobs instead."
        )
