"""The AI reviewer's configuration guard, run as the workflow runs it.

The guard is eight lines of bash inside `.github/workflows/ai-review.yml`, and
it exists because every consumer of those three variables treats an empty value
as "use your default" - Codex's default reasoning effort being `none`, which is
how the first live run reviewed a deliberate cross-tenant leak and reported
nothing in three seconds.

Nothing in CI could catch a regression in it. `actionlint` checks the YAML,
`zizmor` checks the permissions, and neither runs the script; a change that let
an empty effort through would be green everywhere and silently restore the
rubber stamp. So the step is extracted from the workflow and executed here,
against the same shell, rather than asserted about in prose.

Extracting by step name rather than copying the script keeps one copy: rename
the step and this fails loudly instead of testing a stale fork of it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ai-review.yml"
STEP_NAME = "Check the configuration"

# Resolved rather than named: the runner and a developer's machine disagree
# about whether bash is /bin or /usr/bin, and a partial path in a subprocess
# call is a finding of its own (ruff S607).
BASH = shutil.which("bash") or "/bin/bash"

VALID = {
    "REVIEW_MODEL": "gpt-5.6-sol",
    "REVIEW_EFFORT": "high",
    "MAX_CHANGED_LINES": "2000",
}

# The workflow reads a repository variable into a shorter step env name; a
# problem has to name the variable an operator can actually go and set.
REPOSITORY_VARIABLE = {
    "REVIEW_MODEL": "AI_REVIEW_MODEL",
    "REVIEW_EFFORT": "AI_REVIEW_EFFORT",
    "MAX_CHANGED_LINES": "AI_REVIEW_MAX_CHANGED_LINES",
}


def guard_script() -> str:
    """The guard step's shell body, read out of the workflow itself."""
    workflow = yaml.safe_load(WORKFLOW.read_text())
    for step in workflow["jobs"]["review"]["steps"]:
        if step.get("name") == STEP_NAME:
            return str(step["run"])
    raise AssertionError(f"No step named {STEP_NAME!r} in {WORKFLOW}")


def run_guard(tmp_path: Path, **overrides: str) -> tuple[str, str]:
    """Run the guard and return its `(status, problems)` step outputs."""
    output = tmp_path / "github_output"
    output.touch()
    script = tmp_path / "guard.sh"
    script.write_text(guard_script())

    subprocess.run(
        [BASH, str(script)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **VALID,
            **overrides,
            "GITHUB_OUTPUT": str(output),
            "GITHUB_REPOSITORY": "vstorm-co/agenticos",
            "PATH": "/usr/bin:/bin",
        },
    )

    written = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)
    return written.get("status", ""), written.get("problems", "")


def test_a_complete_configuration_is_accepted(tmp_path: Path) -> None:
    status, problems = run_guard(tmp_path)
    assert status == "ok"
    assert problems == ""


@pytest.mark.parametrize("variable", sorted(VALID))
def test_an_unset_variable_is_named(tmp_path: Path, variable: str) -> None:
    status, problems = run_guard(tmp_path, **{variable: ""})
    assert status == "unconfigured"
    assert problems == f"{REPOSITORY_VARIABLE[variable]} is unset"


def test_effort_none_is_refused(tmp_path: Path) -> None:
    """The value the guard exists for.

    `none` is non-empty, so an is-it-set check passes it - and it asks Codex for
    exactly the no-reasoning mode that made the first live run worthless.
    """
    status, problems = run_guard(tmp_path, REVIEW_EFFORT="none")
    assert status == "unconfigured"
    assert "AI_REVIEW_EFFORT is 'none'" in problems


def test_a_non_numeric_line_cap_is_refused(tmp_path: Path) -> None:
    """Otherwise the cap stops existing rather than failing.

    `[ "$changed" -gt abc ]` is an error, and bash scores an errored condition
    as a false `elif` - so an oversized diff falls through to `status=ok` and a
    truncated, expensive pass runs anyway.
    """
    status, problems = run_guard(tmp_path, MAX_CHANGED_LINES="abc")
    assert status == "unconfigured"
    assert "expected a positive integer" in problems


def test_a_zero_line_cap_is_refused(tmp_path: Path) -> None:
    """Numeric, but it would decline every pull request as too large."""
    status, _ = run_guard(tmp_path, MAX_CHANGED_LINES="0")
    assert status == "unconfigured"


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh"])
def test_every_effort_codex_accepts_is_allowed(tmp_path: Path, effort: str) -> None:
    status, _ = run_guard(tmp_path, REVIEW_EFFORT=effort)
    assert status == "ok"


def test_all_three_problems_are_reported_at_once(tmp_path: Path) -> None:
    """One run, one fix. Reporting the first would cost three round trips."""
    status, problems = run_guard(
        tmp_path, REVIEW_MODEL="", REVIEW_EFFORT="none", MAX_CHANGED_LINES="abc"
    )
    assert status == "unconfigured"
    assert problems.count(";") == 2
