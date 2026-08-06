"""The two things about `ci.yml` whose failure mode is a build that reads green.

Both were added by #317, both to spend fewer Actions minutes, and both fail
quietly rather than loudly:

  - **The path gate.** `scripts/ci_changed_scope.py` decides which of `test`,
    `test-frontend` and `e2e` a pull request can skip. Get it wrong in the
    permissive direction and a suite stops running - which is not a red build, it
    is a green one with a gate missing from it. That is #143 and #165 exactly, and
    the reason the script is written to skip only what it can prove irrelevant.
  - **The concurrency group.** Nothing checks that it exists, so deleting it costs
    ~1,800 billed minutes per six days and produces no signal at all. Its `main`
    exemption is load-bearing in the other direction: cancel a merge's run and the
    commit's CI never finishes.

The same shape as `test_ci_parity.py` and `test_coverage_gate.py` - a gate whose
failure mode is a green build needs something checking the checker.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
_SCRIPT = REPO_ROOT / "scripts" / "ci_changed_scope.py"

_spec = importlib.util.spec_from_file_location("ci_changed_scope_under_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
ci_changed_scope = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci_changed_scope)

# Job name in the workflow -> the `changes` output that gates it.
GATED_JOBS = {"test": "backend", "test-frontend": "frontend", "e2e": "e2e"}


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    with WORKFLOW.open() as handle:
        loaded: dict[str, Any] = yaml.safe_load(handle)
    return loaded


class TestNothingUnrecognisedIsEverSkipped:
    """The direction that matters. A path nobody classified must run everything."""

    @pytest.mark.parametrize(
        "path",
        [
            ".github/workflows/ci.yml",
            "Makefile",
            "scripts/ci_changed_scope.py",
            ".pre-commit-config.yaml",
            "compose.yml",
            "a-directory-nobody-has-invented-yet/thing.py",
        ],
    )
    def test_an_unclassified_path_requires_every_suite(self, path: str) -> None:
        assert ci_changed_scope.scope([path]) == {"backend": True, "frontend": True, "e2e": True}

    def test_one_unclassified_path_among_documentation_is_enough(self) -> None:
        """All of them have to be irrelevant, not most of them."""
        decided = ci_changed_scope.scope(["docs/testing.md", "README.md", "Makefile"])
        assert decided == {"backend": True, "frontend": True, "e2e": True}

    def test_an_empty_change_set_requires_every_suite(self) -> None:
        """`all()` over nothing is `True`, which would have skipped all three."""
        assert ci_changed_scope.scope([]) == {"backend": True, "frontend": True, "e2e": True}

    def test_a_workflow_edit_is_not_documentation(self) -> None:
        """`tests/test_ci_parity.py` reads `ci.yml`, so the backend suite cares."""
        assert ci_changed_scope.scope([".github/workflows/ci.yml"])["backend"] is True


class TestWhatMayBeSkipped:
    def test_a_documentation_only_change_skips_all_three(self) -> None:
        decided = ci_changed_scope.scope(
            ["docs/testing.md", "docs/reference/spec.md", "mkdocs.yml", "CHANGELOG.md"]
        )
        assert decided == {"backend": False, "frontend": False, "e2e": False}

    def test_a_backend_only_change_skips_the_frontend_suite_and_nothing_else(self) -> None:
        decided = ci_changed_scope.scope(["backend/app/services/access.py"])
        assert decided == {"backend": True, "frontend": False, "e2e": True}

    def test_a_frontend_only_change_skips_the_backend_suite_and_nothing_else(self) -> None:
        decided = ci_changed_scope.scope(["frontend/src/lib/api-client.ts"])
        assert decided == {"backend": False, "frontend": True, "e2e": True}

    def test_a_change_to_both_halves_skips_nothing(self) -> None:
        decided = ci_changed_scope.scope(
            ["backend/app/api/routes/v1/agents.py", "frontend/src/hooks/use-agents.ts"]
        )
        assert decided == {"backend": True, "frontend": True, "e2e": True}

    def test_e2e_is_exempted_from_neither_half(self) -> None:
        """It drives the frontend against the backend, so either half affects it."""
        assert ci_changed_scope.scope(["backend/app/main.py"])["e2e"] is True
        assert ci_changed_scope.scope(["frontend/src/app/page.tsx"])["e2e"] is True

    def test_a_release_bump_runs_everything(self) -> None:
        """Worth stating: `chore: cut 0.0.x` touches both halves, so it skips nothing.

        #317 originally claimed a release pull request would stop paying for the
        whole matrix. It does not - the version lives in `backend/pyproject.toml`,
        `backend/uv.lock` and `frontend/package.json`, so every filter matches.
        """
        decided = ci_changed_scope.scope(
            [
                "CHANGELOG.md",
                "backend/pyproject.toml",
                "backend/uv.lock",
                "frontend/package.json",
            ]
        )
        assert decided == {"backend": True, "frontend": True, "e2e": True}

    def test_a_nested_markdown_file_is_not_documentation(self) -> None:
        """Only a *top-level* `*.md` is exempt; `backend/app/README.md` is not."""
        assert ci_changed_scope.scope(["backend/app/agents/NOTES.md"])["backend"] is True


class TestTheWorkflowActuallyUsesIt:
    """A perfect classifier wired to nothing skips nothing, and saves nothing."""

    def test_the_changes_job_runs_the_script(self, workflow: dict[str, Any]) -> None:
        commands = [step.get("run", "") for step in workflow["jobs"]["changes"]["steps"]]
        assert any("scripts/ci_changed_scope.py" in command for command in commands), (
            "the `changes` job no longer runs the classifier, so its outputs are empty "
            "and every gated job runs - expensive, but at least not silent"
        )

    @pytest.mark.parametrize(("job", "output"), sorted(GATED_JOBS.items()))
    def test_each_gated_job_reads_its_own_output(
        self, workflow: dict[str, Any], job: str, output: str
    ) -> None:
        definition = workflow["jobs"][job]
        assert "changes" in definition["needs"], f"`{job}` does not depend on `changes`"
        assert definition["if"] == f"needs.changes.outputs.{output} != 'false'", (
            f"`{job}` must gate on `needs.changes.outputs.{output} != 'false'`. "
            "`== 'true'` would skip it on a push to `main`, where the classifier does "
            "not run and the output is empty."
        )

    def test_every_output_the_script_emits_is_declared(self, workflow: dict[str, Any]) -> None:
        """A job gating on an output nothing sets is a job that always runs."""
        declared = set(workflow["jobs"]["changes"]["outputs"])
        assert declared == set(ci_changed_scope.JOBS)

    def test_lint_is_never_gated(self, workflow: dict[str, Any]) -> None:
        """`make lint-spelling` reads every tracked file, so something must always.

        It is also one billed minute, so gating it would buy nothing worth the
        argument.
        """
        assert "if" not in workflow["jobs"]["lint"]


class TestTheConcurrencyGroup:
    def test_the_workflow_declares_one(self, workflow: dict[str, Any]) -> None:
        assert "concurrency" in workflow, (
            "without a concurrency group nothing cancels a superseded run: 75 of 369 "
            "runs in six days, about 1,800 billed minutes (#317)"
        )

    def test_it_is_keyed_per_ref(self, workflow: dict[str, Any]) -> None:
        """A shared group would have one branch cancelling another's run."""
        assert "github.ref" in workflow["concurrency"]["group"]

    def test_a_push_to_main_is_never_cancelled(self, workflow: dict[str, Any]) -> None:
        """The merge's own run is what makes the history and the badge mean anything."""
        assert (
            workflow["concurrency"]["cancel-in-progress"]
            == "${{ github.event_name == 'pull_request' }}"
        )
