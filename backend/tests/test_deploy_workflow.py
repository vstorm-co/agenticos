"""Properties of `deploy.yml` that its approval gate does not enforce by itself.

`test_deploy_queue_workflow.py` covers the queue; this covers *what* may be
deployed. A merged commit, or - asked for by name - an open pull request from
this repository, put on the test server before it merges:

  - Never a fork's branch: the job that runs it holds the key to the server.
  - The pull request's head is pinned before the approval gate, so what is
    approved is a commit, not a branch somebody can push to afterwards.
  - Its images are published on the way, since a branch has none until asked.
  - The run says, where the approver reads it, that `main` must not be
    deployed over it until it merges: the database is ahead of `main`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    with WORKFLOW.open() as handle:
        loaded: dict[str, Any] = yaml.safe_load(handle)
    return loaded


@pytest.fixture(scope="module")
def resolve_script(workflow: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in workflow["jobs"]["resolve"]["steps"])


class TestWhatMayBeDeployed:
    def test_a_merged_commit_still_has_to_be_on_main(self, resolve_script: str) -> None:
        assert 'git merge-base --is-ancestor "$sha" origin/main' in resolve_script

    def test_a_pull_request_is_named_and_must_be_open_and_this_repositorys(
        self, workflow: dict[str, Any], resolve_script: str
    ) -> None:
        assert "pr" in workflow[True]["workflow_dispatch"]["inputs"]
        assert ".head.repo.full_name" in resolve_script
        assert '"$head_repo" != "$REPO"' in resolve_script
        assert '"$state" != open' in resolve_script

    def test_the_pull_request_is_pinned_before_the_approval(self, workflow: dict[str, Any]) -> None:
        """The gate is on `deploy`; `resolve` holds no environment and no secrets."""
        resolve = workflow["jobs"]["resolve"]
        assert "environment" not in resolve
        assert workflow["jobs"]["deploy"]["needs"] == "resolve"
        assert workflow["jobs"]["deploy"]["environment"]["name"] == "production"

    def test_its_images_are_published_on_the_way(self, workflow: dict[str, Any]) -> None:
        publish = next(
            step
            for step in workflow["jobs"]["resolve"]["steps"]
            if step.get("name") == "Publish its images"
        )
        assert publish["if"] == "inputs.pr != ''"
        assert "gh workflow run images.yml" in publish["run"]
        assert '-f sha="$SHA"' in publish["run"], "the images must be the pinned commit's"
        assert workflow["jobs"]["resolve"]["permissions"]["actions"] == "write"

    def test_the_approver_is_told_not_to_deploy_main_over_it(self, resolve_script: str) -> None:
        assert "::warning::" in resolve_script and "migrations" in resolve_script
