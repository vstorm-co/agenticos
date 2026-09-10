"""Properties of `images.yml` and of the compose files that pull what it publishes.

`test_ci_workflow.py` asks whether CI runs at all and is bounded when it does.
This file asks the same of the publish workflow, plus the one question neither
file can be run to answer: whether the image names the workflow pushes are the
names the compose files pull. A rename on either side is a `docker compose up`
that fails with `manifest unknown` on a fresh host - and on no developer's
laptop, where the override file builds the image locally under another name.

  - No `pull_request` trigger. The jobs hold `packages: write`, and a workflow
    with that permission that ran on a fork's pull request would let the fork
    publish under this organization's name.
  - Only a commit already on `main` is published, whatever ref the run was
    started from - a `v*` tag pushed from a branch must not move `latest`.
  - One concurrency group per commit. A group per ref with
    `cancel-in-progress: false` is one running and one *pending* run, so a
    third merge cancels the second's publish and that commit has no `sha-`
    images for `scripts/deploy.sh` to pull (the rule `ci.yml` documents).
  - Every job bounds its own runtime, for the reason `test_ci_workflow.py` gives
    (#364): the default is six hours.
  - Every compose file that pulls an image pulls one of the two the workflow
    publishes, at the `AGENTICOS_VERSION` interpolation and nothing hard-coded.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "images.yml"

PUBLISHED = frozenset(
    {"ghcr.io/vstorm-co/agenticos-backend", "ghcr.io/vstorm-co/agenticos-frontend"}
)

# Every compose file that runs the application from a published image. The
# override file is deliberately absent: it builds from the tree and tags the
# result locally, which is the whole of what it is for.
PULLING_COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose-dev.yml",
    "docker-compose-dev.frontend.yml",
    "docker-compose-prod.yml",
    "docker-compose-prod.frontend.yml",
)

_IMAGE_LINE = re.compile(
    r"^\s+image:\s*(ghcr\.io/vstorm-co/agenticos-[a-z]+)(:\S+)?\s*$", re.MULTILINE
)


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


class TestOnlyThisRepositoryCanPublish:
    def test_no_pull_request_trigger(self, triggers: dict[str, Any]) -> None:
        assert "pull_request" not in triggers and "pull_request_target" not in triggers, (
            "images.yml runs on a pull request. Its jobs hold `packages: write`, so a fork's "
            "pull request would publish under ghcr.io/vstorm-co."
        )

    def test_it_publishes_a_release_and_the_main_branch(self, triggers: dict[str, Any]) -> None:
        push = triggers["push"]
        assert push["branches"] == ["main"]
        assert push["tags"] == ["v*"], (
            "a release is a `v*` tag, and that is what has to publish `<version>` and `latest`"
        )

    def test_the_workflow_itself_grants_read_only(self, workflow: dict[str, Any]) -> None:
        """`packages: write` belongs on the jobs that push, not on the workflow."""
        assert workflow["permissions"] == {"contents": "read"}
        writers = {
            name
            for name, job in workflow["jobs"].items()
            if job.get("permissions", {}).get("packages") == "write"
        }
        assert writers == {"build", "publish"}

    def test_only_a_commit_already_on_main_is_published(self, workflow: dict[str, Any]) -> None:
        """A `v*` tag can be pushed from any branch; the ruleset only forbids moving one.

        So the workflow, not the tag, is what keeps `latest` behind the pull-request
        boundary: `resolve` refuses a commit that is not an ancestor of `main`, and
        every job that pushes runs after it and on the commit it resolved.
        """
        resolve = workflow["jobs"]["resolve"]
        script = "\n".join(step.get("run", "") for step in resolve["steps"])
        assert "git merge-base --is-ancestor" in script and "origin/main" in script
        for name in ("build", "publish"):
            needs = workflow["jobs"][name]["needs"]
            assert "resolve" in ([needs] if isinstance(needs, str) else needs), (
                f"{name} pushes without waiting for the commit to be checked"
            )
        checkout = next(
            step for step in workflow["jobs"]["build"]["steps"] if "checkout" in step["uses"]
        )
        assert checkout["with"]["ref"] == "${{ needs.resolve.outputs.sha }}"

    def test_a_dispatch_can_backfill_a_commit_that_has_no_images(
        self, triggers: dict[str, Any]
    ) -> None:
        """A rollback through `scripts/deploy.sh` pulls `sha-<short>` and builds nothing.

        A commit older than this workflow, or one whose run was lost, has no such
        tag - so the dispatch takes the commit to publish, and the resolve step
        holds it to the same on-`main` rule as everything else.
        """
        assert "sha" in triggers["workflow_dispatch"]["inputs"]


class TestOnePublishPerCommit:
    def test_the_concurrency_group_is_the_commit_and_never_cancels(
        self, workflow: dict[str, Any]
    ) -> None:
        """A group per ref queues one pending run and cancels the one before it.

        Three merges in a row would leave the middle commit with no images, and
        `scripts/deploy.sh` waiting twenty minutes for a tag that will never
        exist. Keyed on the commit, runs neither queue nor cancel each other;
        the group still serialises a push and a dispatch re-run of one commit.
        """
        concurrency = workflow["concurrency"]
        assert "github.sha" in concurrency["group"]
        assert "github.ref" not in concurrency["group"]
        assert concurrency["cancel-in-progress"] is False

    def test_a_release_on_a_built_commit_retags_rather_than_rebuilds(
        self, workflow: dict[str, Any]
    ) -> None:
        """`build` is skipped when the commit's `sha-` manifest exists, and `publish` still runs."""
        assert workflow["jobs"]["build"]["if"] == "needs.resolve.outputs.build == 'true'"
        publish_if = workflow["jobs"]["publish"]["if"]
        assert "needs.build.result == 'skipped'" in publish_if
        assert "needs.build.result == 'success'" in publish_if
        assert "cancelled()" in publish_if


class TestEveryJobBoundsItsOwnRuntime:
    def test_every_job_declares_a_timeout(self, workflow: dict[str, Any]) -> None:
        missing = sorted(
            name for name, job in workflow["jobs"].items() if "timeout-minutes" not in job
        )
        assert not missing, f"{missing} inherit GitHub's default of 360 minutes - #364"

    def test_no_timeout_is_so_generous_it_bounds_nothing(self, workflow: dict[str, Any]) -> None:
        excessive = sorted(
            name for name, job in workflow["jobs"].items() if job["timeout-minutes"] > 30
        )
        assert not excessive


class TestTheComposeFilesPullWhatTheWorkflowPublishes:
    def test_the_workflow_names_both_images(self, workflow: dict[str, Any]) -> None:
        prefix = workflow["env"]["IMAGE_PREFIX"]
        images = workflow["jobs"]["build"]["strategy"]["matrix"]["image"]
        assert {f"{prefix}-{image}" for image in images} == PUBLISHED

    @pytest.mark.parametrize("name", PULLING_COMPOSE_FILES)
    def test_every_pulled_application_image_is_a_published_one(self, name: str) -> None:
        text = (REPO_ROOT / name).read_text()
        pulled = _IMAGE_LINE.findall(text)
        assert pulled, f"{name} pulls no agenticos image at all"
        for image, tag in pulled:
            assert image in PUBLISHED, f"{name} pulls {image}, which images.yml does not publish"
            assert tag.startswith(":${AGENTICOS_VERSION:-"), (
                f"{name} pins {image}{tag}. The tag is `AGENTICOS_VERSION` with a default, so a host "
                "can pin a release in its env file and scripts/deploy.sh can pin the commit it deploys."
            )

    def test_the_base_file_pulls_both_halves_of_the_product(self) -> None:
        """`docker compose up` on the one file has to be the whole product, console included (#1545)."""
        text = (REPO_ROOT / "docker-compose.yml").read_text()
        assert {image for image, _ in _IMAGE_LINE.findall(text)} == PUBLISHED

    def test_the_override_builds_rather_than_pulls(self) -> None:
        override = yaml.safe_load((REPO_ROOT / "docker-compose.override.yml").read_text())
        services = override["services"]
        assert "build" in services["app"] and "build" in services["frontend"]
        for name, service in services.items():
            registry = str(service.get("image", "")).partition("/")[0]
            assert registry != "ghcr.io", (
                f"the override pins {name} to a registry image; it exists to build from the tree"
            )
