"""A test that guards the coverage gate itself, and the type gate beside it.

This exists because the gate silently stopped measuring most of what it claimed
to cover. `[tool.coverage.run] source` accepts packages and directories only -
a *file path* there is ignored without an error, so eight modules sat in the
config for days while the build reported 100% of a much smaller set.

Switching to `include` fixes that, but trades one silent failure for another:
`include` reports only files that were imported, so a platform module nobody
imports drops out just as quietly. Hence this test. It asserts the two things
the config cannot assert about itself - that every listed pattern matches a real
file, and that every file in the platform layer is actually listed.

The type checker draws the same line for the same reason, with a second copy of
the same file list under `[[tool.ty.overrides]]`. Two copies drift, so the last
class here pins them together: the same files, and every rule the template's
untyped libraries forced down to a warning restored to an error over ours.

The uncomfortable property of a coverage gate is that its failure mode is a
green build. Something has to check the checker.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _matches_glob(path: str, pattern: str) -> bool:
    """Whether a POSIX path matches a coverage-style glob, whole-string.

    `Path.full_match` does exactly this and would be the obvious call, but it
    landed in **Python 3.13** while `requires-python` is `>=3.12` and every CI
    job installs 3.12. Using it made this file raise `AttributeError` on the
    interpreter that actually ships, so the test guarding the gate was itself
    ungated - and it passed locally, where the venv happens to be newer.

    `fnmatch` is not a substitute either: it treats `*` as matching separators,
    so `app/*.py` would match `app/agents/spec.py`. Hence the translation -
    `**` spans directories, a single `*` does not.
    """
    parts = []
    for token in re.split(r"(\*\*/|\*\*|\*|\?)", pattern):
        if token == "**/":
            # Zero or more leading directories, so `a/**/b.py` also matches `a/b.py`.
            parts.append(r"(?:[^/]+/)*")
        elif token == "**":
            parts.append(r".*")
        elif token == "*":
            parts.append(r"[^/]*")
        elif token == "?":
            parts.append(r"[^/]")
        elif token:
            parts.append(re.escape(token))
    return re.fullmatch("".join(parts), path) is not None


# Directories whose contents are entirely platform layer: everything AgenticOS
# adds on top of the generated template. Every file here must be gated.
PLATFORM_PACKAGES = ("app/agents",)

# Individual platform modules living in directories we share with the template.
PLATFORM_MODULES = (
    "app/commands/bootstrap.py",
    "app/core/permissions.py",
    "app/core/secret_kinds.py",
    "app/core/vault.py",
    "app/core/background.py",
    "app/core/field_errors.py",
    "app/db/vector_tables.py",
    "app/services/access.py",
    "app/services/agent_chat.py",
    "app/services/agent_environment.py",
    "app/services/agent_exposure.py",
    "app/services/agent_registry.py",
    "app/services/agent_runner.py",
    "app/services/agent_session.py",
    "app/services/approvals.py",
    "app/services/audit.py",
    "app/services/channels/mentions.py",
    "app/services/collection_access.py",
    "app/services/embed_session.py",
    "app/services/embedding_resolution.py",
    "app/services/rerank_resolution.py",
    "app/services/health.py",
    "app/services/ingestion_config.py",
    "app/services/knowledge_search.py",
    "app/services/mcp_catalog.py",
    "app/services/mcp_connection.py",
    "app/services/model_profile.py",
    "app/services/notifications.py",
    "app/services/organization_secret.py",
    "app/services/rag/remote_names.py",
    "app/services/sharing.py",
    "app/services/skills.py",
    "app/repositories/agent_environment.py",
    "app/repositories/agent_exposure.py",
    "app/repositories/mcp_connection.py",
    "app/repositories/organization_secret.py",
    "app/repositories/resource_grant.py",
    "app/repositories/dashboard_layout.py",
    "app/repositories/dashboard_preset.py",
    "app/api/routes/v1/_sharing_routes.py",
    "app/api/routes/v1/secrets.py",
    "app/api/routes/v1/agent_environments.py",
    "app/api/routes/v1/agent_exposures.py",
    "app/api/routes/v1/sharing.py",
    "app/api/routes/v1/me_dashboard_layout.py",
    "app/services/dashboard_layout.py",
    "app/services/dashboard_preset.py",
    "app/services/generated_media.py",
    "app/api/routes/v1/generated_media.py",
)


@pytest.fixture(scope="module")
def pyproject() -> dict:
    with (BACKEND_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


@pytest.fixture(scope="module")
def coverage_config(pyproject: dict) -> dict:
    return pyproject["tool"]["coverage"]


@pytest.fixture(scope="module")
def platform_type_override(pyproject: dict) -> dict:
    """The `[[tool.ty.overrides]]` entry that holds the platform layer to errors.

    Identified by the package glob rather than by position, so reordering the
    overrides - or adding a third - does not silently point this at the wrong
    one.
    """
    overrides = [
        override
        for override in pyproject["tool"]["ty"]["overrides"]
        if "app/agents/**" in override.get("include", [])
    ]
    assert len(overrides) == 1, "expected exactly one platform-layer ty override"
    return overrides[0]


class TestGateSelection:
    def test_the_gate_uses_include_not_source(self, coverage_config: dict) -> None:
        """`source` would silently drop the file entries this project relies on."""
        run = coverage_config["run"]
        assert "include" in run
        assert "source" not in run, (
            "coverage ignores file paths in `source`; the platform modules would "
            "stop being measured without any error"
        )

    def test_every_pattern_matches_something(self, coverage_config: dict) -> None:
        """A stale pattern is a module quietly leaving the gate."""
        for pattern in coverage_config["run"]["include"]:
            assert list(BACKEND_ROOT.glob(pattern)), f"include pattern matches nothing: {pattern}"

    def test_every_omission_matches_something(self, coverage_config: dict) -> None:
        """An omission for a file that no longer exists is dead configuration."""
        for pattern in coverage_config["run"].get("omit", []):
            assert list(BACKEND_ROOT.glob(pattern)), f"omit pattern matches nothing: {pattern}"

    def test_the_bar_is_still_one_hundred(self, coverage_config: dict) -> None:
        assert coverage_config["report"]["fail_under"] == 100


class TestPlatformLayerIsFullyListed:
    """Every file we wrote is in the gate, or explicitly and visibly excluded."""

    @staticmethod
    def _covered(coverage_config: dict, path: str) -> bool:
        include = coverage_config["run"]["include"]
        omit = coverage_config["run"].get("omit", [])
        matched = any(_matches_glob(path, pattern) for pattern in include)
        excluded = any(_matches_glob(path, pattern) for pattern in omit)
        return matched and not excluded

    def test_no_platform_module_has_fallen_out(self, coverage_config: dict) -> None:
        missing = [
            module for module in PLATFORM_MODULES if not self._covered(coverage_config, module)
        ]
        assert not missing, f"platform modules outside the coverage gate: {missing}"

    def test_every_platform_module_still_exists(self) -> None:
        """A renamed module would otherwise leave the gate without anyone noticing."""
        missing = [module for module in PLATFORM_MODULES if not (BACKEND_ROOT / module).exists()]
        assert not missing, f"listed but not on disk: {missing}"

    def test_every_file_in_a_platform_package_is_gated(self, coverage_config: dict) -> None:
        """Adding a capability must not require remembering to widen the gate.

        The package globs cover new files automatically; this asserts that no
        omission has quietly carved one back out.
        """
        ungated: list[str] = []
        for package in PLATFORM_PACKAGES:
            for path in (BACKEND_ROOT / package).rglob("*.py"):
                relative = path.relative_to(BACKEND_ROOT).as_posix()
                if "__pycache__" in relative:
                    continue
                if not self._covered(coverage_config, relative):
                    ungated.append(relative)

        # The chat was rebuilt on the factory and the general assistant is
        # gone; the one deliberate omission left is the template's OAuth
        # client, documented in pyproject.toml. Anything else is an accident.
        expected_exclusions = {"app/agents/mcp_oauth.py"}
        unexpected = [path for path in ungated if path not in expected_exclusions]
        assert not unexpected, f"new platform files outside the gate: {unexpected}"


class TestTypeGateMatchesCoverageGate:
    """The type checker holds the same files, to the rules the template gave up.

    `ty check` used to report 66 diagnostics and exit 0, because every rule that
    an untyped third-party library tripped was downgraded globally. The reasons
    were real and they are still there for the template's code; what changed is
    that they no longer apply to ours. Both halves of that are only true while
    this passes.
    """

    def test_it_covers_exactly_the_files_the_coverage_gate_does(
        self, coverage_config: dict, platform_type_override: dict
    ) -> None:
        """One definition of "ours", read twice - so a new module joins both gates."""
        assert platform_type_override["include"] == coverage_config["run"]["include"]
        assert platform_type_override.get("exclude", []) == coverage_config["run"].get("omit", [])

    def test_every_globally_downgraded_rule_is_an_error_over_our_code(
        self, pyproject: dict, platform_type_override: dict
    ) -> None:
        """A downgrade added for the template must not quietly widen to us too."""
        downgraded = {
            rule for rule, level in pyproject["tool"]["ty"]["rules"].items() if level == "warn"
        }
        restored = {
            rule for rule, level in platform_type_override["rules"].items() if level == "error"
        }
        assert not downgraded - restored, (
            "rules downgraded globally but not restored for the platform layer: "
            f"{sorted(downgraded - restored)}"
        )

    def test_the_run_still_fails_on_a_platform_error(
        self, pyproject: dict, platform_type_override: dict
    ) -> None:
        """`error-on-warning = false` is what made the old gate decorative.

        It stays false - the template's diagnostics are informational - so the
        only thing that can fail the run is a rule set to `error`, and this
        override is the only place that does it.
        """
        assert pyproject["tool"]["ty"]["terminal"]["error-on-warning"] is False
        assert set(platform_type_override["rules"].values()) == {"error"}
