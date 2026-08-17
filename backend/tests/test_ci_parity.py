"""A test that `make check` is what CI runs, because the claim is load-bearing.

`make check` is documented in four places as "what CI runs", and people believe
it: a green `check` is what a branch is pushed on. When it runs less than CI, the
failure mode is the expensive one - green locally, red after the push, and half
an hour spent trusting the wrong answer. #143 found four separate divergences at
once, none of them visible to anybody reading either file alone:

  - `check` ran `test-frontend` (no coverage) where CI runs `test:coverage` and
    its 100% gate. Every run on `feat/sandbox` after 832d647 was red while the
    pull request reported `make check` green.
  - `make lint` ran neither eslint, prettier nor tsc; CI's `test-frontend` job
    runs all three.
  - `check` ran neither `next build`, the docs build nor the dependency audit -
    three entire CI jobs with no local equivalent at all.
  - And in the other direction, CI never ran the i18n guard, which `make lint`
    did: a hardcoded string failed locally and passed the build. It was
    `scripts/check_i18n.py` then; #395 replaced it with
    `frontend/scripts/check-i18n.ts`, run by `lint-frontend`.

The fix is structural rather than clerical - the workflow calls the Makefile's
targets instead of repeating their commands, so there is one definition of each
check. This test guards the part that structure cannot: that a future step added
to a gating job is added as a target `check` also runs, rather than as a raw
command only CI knows about.

The same shape as `test_coverage_gate.py`, and for the same reason: a gate whose
failure mode is a green build needs something checking the checker.

Comparing the *steps* is not the whole claim, though, which is #227: `check` ran
every command CI runs and still could not run at all in a fresh checkout, because
nothing in the documented setup path installed `frontend/node_modules` and every
frontend step then answered `eslint: command not found`. So the setup commands
are held to the mirror-image rule - a gating job may prepare its runner however
it likes, as long as `make install` prepares a laptop the same way.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
MAKEFILE = REPO_ROOT / "Makefile"

# The jobs `make check` claims to reproduce. `e2e` and `docker` are out of scope
# on purpose and the reasons are in the `check` target: e2e needs a migrated
# database, a seeded organization and a running backend, and the image build runs
# only on a push to `main`.
GATING_JOBS = ("lint", "test", "test-frontend", "docs", "security")

# Commands that prepare a runner rather than check anything. They have no place in
# `check` - it checks a checkout, it does not build one - so they answer to
# `install` instead, which is what INSTALL_EXEMPT below is about.
ENVIRONMENT_SETUP = frozenset(
    {
        "uv python install 3.12",
        "uv sync --directory backend --dev",
        "uv sync --directory backend --group docs",
        "bun install --frozen-lockfile",
    }
)

# The setup commands `make install` does not owe, each with the reason nothing is
# missing without it. Everything else CI installs, `install` installs too.
INSTALL_EXEMPT = frozenset(
    {
        # `uv sync` reads `backend/.python-version` and fetches the interpreter
        # itself; the runner needs it named because it starts with none.
        "uv python install 3.12",
        # `docs` and `docs-build` pass `--group docs` to `uv run`, which resolves
        # the group at the point of use rather than into a synced virtualenv.
        "uv sync --directory backend --group docs",
    }
)

# Targets CI runs that `check` deliberately does not, each with the reason it is
# not drift. Anything else appearing in a gating job has to be reachable from
# `check`.
CI_ONLY_TARGETS = {
    # `downgrade base` against CI's throwaway `test_db` is a rollback test;
    # against a laptop's `backend/.env` it is somebody's afternoon.
    "test-migrations",
    # Informational, `if: always()`, and reported at `--cov-fail-under=0`. It
    # gates nothing, so requiring it locally would only cost a second suite run.
    "coverage-all",
}

_MAKE_INVOCATION = re.compile(r"^make\s+([a-z][a-z0-9-]*)((?:\s+[A-Z_]+=\S+)*)$")
# A Makefile rule: a target list, a colon, prerequisites. Recipe lines start with
# a tab and variable assignments carry an `=` before the colon, so both are out.
_MAKE_RULE = re.compile(r"^(?!\t)([^\t=#:]+):(?!=)([^=]*)$")


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    with WORKFLOW.open() as handle:
        loaded: dict[str, Any] = yaml.safe_load(handle)
    return loaded


@pytest.fixture(scope="module")
def prerequisites() -> dict[str, list[str]]:
    """Every Makefile target mapped to the targets it depends on."""
    graph: dict[str, list[str]] = {}
    for line in MAKEFILE.read_text().splitlines():
        match = _MAKE_RULE.match(line)
        if not match:
            continue
        targets, deps = match.groups()
        for target in targets.split():
            if target.startswith("."):
                continue
            graph.setdefault(target, []).extend(deps.split())
    return graph


@pytest.fixture(scope="module")
def recipes() -> dict[str, str]:
    """Every Makefile target mapped to its recipe as one string.

    Joined rather than kept as lines because the questions asked of it are about
    whether a command is in there at all - `cd frontend && bun install …` is the
    same setup step as CI's bare `bun install …`, run from the directory the
    lockfile is in.
    """
    bodies: dict[str, list[str]] = {}
    current: list[str] = []
    for line in MAKEFILE.read_text().splitlines():
        if line.startswith("\t"):
            for target in current:
                bodies.setdefault(target, []).append(line.lstrip("\t").removeprefix("@"))
        elif match := _MAKE_RULE.match(line):
            current = [target for target in match.group(1).split() if not target.startswith(".")]
        elif line.strip():
            current = []
    return {target: "\n".join(lines) for target, lines in bodies.items()}


@pytest.fixture(scope="module")
def check_closure(prerequisites: dict[str, list[str]]) -> set[str]:
    """Every target `make check` reaches, transitively."""
    seen: set[str] = set()
    pending = ["check"]
    while pending:
        target = pending.pop()
        if target in seen:
            continue
        seen.add(target)
        pending.extend(prerequisites.get(target, []))
    return seen


def _run_steps(workflow: dict[str, Any], job: str) -> list[str]:
    """Every shell command a job runs, one entry per `run:` line."""
    steps: list[str] = []
    for step in workflow["jobs"][job]["steps"]:
        command = step.get("run")
        if command is not None:
            steps.append(command.strip())
    return steps


def _invoked_target(command: str) -> str | None:
    """The target a `make …` command runs, or None if it is not one."""
    match = _MAKE_INVOCATION.match(command)
    return match.group(1) if match else None


class TestEveryGatingStepIsAMakeTarget:
    """CI must not hold a check that has no name a developer can type."""

    @pytest.mark.parametrize("job", GATING_JOBS)
    def test_no_gating_job_runs_a_bare_command(self, workflow: dict[str, Any], job: str) -> None:
        strays = [
            command
            for command in _run_steps(workflow, job)
            if command not in ENVIRONMENT_SETUP and _invoked_target(command) is None
        ]
        assert not strays, (
            f"the `{job}` job runs commands with no Makefile target, so `make check` "
            f"cannot reproduce them: {strays}"
        )

    @pytest.mark.parametrize("job", GATING_JOBS)
    def test_every_target_a_gating_job_runs_exists(
        self, workflow: dict[str, Any], job: str, prerequisites: dict[str, list[str]]
    ) -> None:
        """A renamed target would otherwise fail only once the workflow ran."""
        missing = [
            target
            for command in _run_steps(workflow, job)
            if (target := _invoked_target(command)) is not None and target not in prerequisites
        ]
        assert not missing, f"the `{job}` job runs targets the Makefile does not define: {missing}"

    @pytest.mark.parametrize("job", GATING_JOBS)
    def test_every_target_a_gating_job_runs_is_reachable_from_check(
        self, workflow: dict[str, Any], job: str, check_closure: set[str]
    ) -> None:
        unreachable = [
            target
            for command in _run_steps(workflow, job)
            if (target := _invoked_target(command)) is not None
            and target not in check_closure
            and target not in CI_ONLY_TARGETS
        ]
        assert not unreachable, (
            f"the `{job}` job runs {unreachable}, which `make check` does not - the "
            "exact shape of #143. Add it to `check`, or to CI_ONLY_TARGETS with the "
            "reason it belongs only in CI."
        )


class TestInstallPreparesWhatTheChecksNeed:
    """A check nothing can run is a check `make check` reports as an error.

    `make install` is the whole documented setup path - `docs/install.md` names it
    and nothing else - so a toolchain it does not install is one the next command
    fails on, with `command not found` rather than anything actionable.
    """

    def test_every_setup_command_a_gating_job_runs_is_part_of_install(
        self, workflow: dict[str, Any], recipes: dict[str, str]
    ) -> None:
        missing = sorted(
            {
                command
                for job in GATING_JOBS
                for command in _run_steps(workflow, job)
                if command in ENVIRONMENT_SETUP
                and command not in INSTALL_EXEMPT
                and command not in recipes["install"]
            }
        )
        assert not missing, (
            f"CI runs {missing} to prepare a runner and `make install` does not, so a "
            "fresh checkout cannot run the checks that need it - the shape of #227. Add "
            "it to `install`, or to INSTALL_EXEMPT with the reason a laptop is fine "
            "without it."
        )

    def test_install_creates_the_env_file_the_host_checks_read(
        self, recipes: dict[str, str]
    ) -> None:
        """CI needs no `backend/.env`; a laptop cannot run `db-check` without one.

        The runner sets `POSTGRES_*` on the job, so nothing in the workflow says
        this out loud and the parity rule above cannot see it. On a laptop the
        settings come from the file, `POSTGRES_PASSWORD` defaults to empty, and
        `alembic check` is refused with `fe_sendauth: no password supplied` (#299).
        """
        recipe = recipes["install"]
        assert "backend/.env.example" in recipe and "backend/.env" in recipe, (
            "`make install` does not create `backend/.env`, so `make check` stops at "
            "`db-check` in a fresh checkout with a psycopg2 traceback."
        )

    def test_install_does_not_overwrite_an_env_file_that_exists(
        self, recipes: dict[str, str]
    ) -> None:
        """The file that exists holds somebody's keys, and `install` is re-run often.

        `docs/install.md` calls every step idempotent, and this is the one where
        idempotent and destructive are one character apart.
        """
        assert "[ -f backend/.env ]" in recipes["install"], (
            "the copy has to be guarded on the file's absence - `cp` over an existing "
            "`backend/.env` destroys the credentials in it"
        )


class TestCheckRunsNothingCIDoesNot:
    """The reverse direction, which is how the i18n guard was missed for months.

    A local-only check is the milder failure - it costs a developer time rather
    than shipping a defect - but it still means the two commands disagree, and
    the one people trust is the one that runs in CI.
    """

    def test_every_target_check_depends_on_runs_in_a_gating_job(
        self, workflow: dict[str, Any], prerequisites: dict[str, list[str]]
    ) -> None:
        invoked = {
            target
            for job in GATING_JOBS
            for command in _run_steps(workflow, job)
            if (target := _invoked_target(command)) is not None
        }
        # Only the targets that do work. A grouping target like `lint` is
        # satisfied by CI running both of its halves.
        leaves = {target for target in prerequisites["check"] if not prerequisites.get(target)} | {
            leaf for target in prerequisites["check"] for leaf in prerequisites.get(target, [])
        }
        missing = sorted(leaves - invoked)
        assert not missing, (
            f"`make check` runs {missing} and no CI job does. Either CI is missing a "
            "gate a branch will pass locally, or the target does not belong in `check`."
        )
