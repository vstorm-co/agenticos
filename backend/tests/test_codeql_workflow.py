"""Properties of `codeql.yml`, whose failure mode is an analysis nobody notices.

CodeQL ran here through GitHub's **default setup** on a weekly schedule until
#1415: the finding arrived on `main`, after the merge that introduced it, up to
a week late. `codeql.yml` replaces that with an analysis on the pull request,
and everything below is a way for the replacement to be silently less than what
it replaced.

  - **The trigger.** Without `pull_request` this is the weekly report again
    under a different file name, and nothing about a green pull request would
    say so.
  - **The languages.** Default setup analysed six names, four of them distinct -
    `javascript` and `typescript` are aliases GitHub resolves to
    `javascript-typescript`. A language dropped from the matrix is a tree that
    stops being analysed, which no run reports because no run for it exists.
  - **The permission.** `security-events: write` is what the upload needs. A
    matrix that builds the database and cannot upload it fails loudly, which is
    the good case; this asserts the permission is scoped to the one job that
    needs it rather than granted at the top of the file.
  - **The bound**, for the reason `test_ci_workflow.py` gives (#364): a job with
    no `timeout-minutes` inherits six hours.
  - **The pins.** Every third-party action in this repository is pinned by
    commit SHA, and `zizmor` in pre-commit reads the other files. A tag here
    would be the one action in the tree that a repository rename could move.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "codeql.yml"

# The distinct languages GitHub's default setup was configured with, after
# resolving its aliases. Recorded here so dropping one is a failing test rather
# than a quiet reduction in what is scanned.
EXPECTED_LANGUAGES = frozenset({"actions", "javascript-typescript", "python", "rust"})

# The same ceiling `test_ci_workflow.py` applies, and for the same reason: a
# bound much beyond the job's worst case is the 360-minute default with extra
# steps.
MAX_TIMEOUT_MINUTES = 30

_PINNED = re.compile(r"^[^@]+@[0-9a-f]{40}$")


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    with WORKFLOW.open() as handle:
        loaded: dict[str, Any] = yaml.safe_load(handle)
    return loaded


@pytest.fixture(scope="module")
def triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    """The `on:` block - keyed by `True`, because PyYAML reads a bare `on` as a boolean."""
    block: dict[str, Any] = workflow[True]
    return block


@pytest.fixture(scope="module")
def analyze(workflow: dict[str, Any]) -> dict[str, Any]:
    job: dict[str, Any] = workflow["jobs"]["analyze"]
    return job


def test_the_analysis_runs_on_a_pull_request(triggers: dict[str, Any]) -> None:
    assert "pull_request" in triggers


def test_the_analysis_still_runs_weekly(triggers: dict[str, Any]) -> None:
    """The scheduled run is not redundant: a query pack updated after a merge
    finds things the pull request could not have."""
    assert triggers["schedule"], "the weekly run default setup did is not replaced"


def test_every_language_default_setup_covered_is_still_analysed(
    analyze: dict[str, Any],
) -> None:
    assert set(analyze["strategy"]["matrix"]["language"]) == EXPECTED_LANGUAGES


def test_the_upload_permission_is_scoped_to_the_analysing_job(
    workflow: dict[str, Any], analyze: dict[str, Any]
) -> None:
    assert workflow["permissions"] == {"contents": "read"}
    assert analyze["permissions"]["security-events"] == "write"


def test_the_job_bounds_its_own_runtime(analyze: dict[str, Any]) -> None:
    bound = analyze["timeout-minutes"]
    assert 0 < bound <= MAX_TIMEOUT_MINUTES


def test_a_failing_language_does_not_cancel_the_others(analyze: dict[str, Any]) -> None:
    """Four independent analyses. One tree failing to build a database says
    nothing about the other three, and cancelling them hides whatever they
    would have found."""
    assert analyze["strategy"]["fail-fast"] is False


def test_every_action_is_pinned_by_commit_sha(analyze: dict[str, Any]) -> None:
    used = [step["uses"] for step in analyze["steps"] if "uses" in step]
    assert used, "the job uses no actions, so this test is asserting nothing"
    unpinned = [ref for ref in used if not _PINNED.match(ref)]
    assert not unpinned, f"pinned by tag rather than SHA: {unpinned}"
