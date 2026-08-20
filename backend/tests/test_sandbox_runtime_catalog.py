"""The runtime catalogue, and the compose files generated from it.

The value in a compose file is a copy - `SANDBOXD_RUNTIMES` is the only channel
the service accepts runtimes on, and a compose file cannot call a command - so the
whole question is whether the copy can drift. These are what says it cannot.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.commands.sandbox_runtimes import COMPOSE_FILES, _repo_root, compose_value
from app.services.sandbox_runtimes import (
    CATALOG,
    SandboxRuntimeDefinition,
    allowlist_value,
    runtime_briefing,
)


def _sandboxd_environment(name: str) -> dict[str, Any]:
    text = (_repo_root() / name).read_text()
    return dict(yaml.safe_load(text)["services"]["sandboxd"]["environment"])


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_a_compose_file_carries_exactly_what_the_catalogue_describes(name: str) -> None:
    """The generated line, asserted rather than trusted.

    `make sandbox-runtimes` writes it and nothing runs that on the way to a
    review, so a hand edit to a compose file - or a package added to the
    catalogue without regenerating - fails here and names the file.
    """
    environment = _sandboxd_environment(name)
    mode = environment["SANDBOXD_NETWORK_MODE"]
    assert environment["SANDBOXD_RUNTIMES"] == compose_value(network_mode=mode), (
        f"{name} has drifted from app/core/catalog/sandbox_runtimes.json. "
        f"Run `make sandbox-runtimes`."
    )


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_a_runtime_that_needs_a_network_is_given_one(name: str) -> None:
    """The trap `needs_network` exists for, checked against the file itself.

    `SANDBOXD_NETWORK_MODE` is service-wide and every shipped file sets it to
    `none`, so an entry whose purpose is installing at run time is only reachable
    if the JSON says `bridge` for itself.
    """
    environment = _sandboxd_environment(name)
    entries = json.loads(environment["SANDBOXD_RUNTIMES"].replace("$$", "$"))
    service_wide = environment["SANDBOXD_NETWORK_MODE"]
    for runtime in CATALOG:
        reachable = (
            service_wide == "bridge" or entries[runtime.alias].get("network_mode") == "bridge"
        )
        assert reachable is runtime.needs_network, runtime.alias


def test_the_catalogue_reaches_the_service_in_the_order_it_is_written() -> None:
    """The order of the file is load-bearing.

    The service takes the first entry of the allowlist for an agent whose spec
    names no runtime, so a `json.dumps` that sorted its keys would silently change
    which image every such agent gets.
    """
    assert list(json.loads(allowlist_value())) == [runtime.alias for runtime in CATALOG]


def test_the_shipped_catalogue_parses_as_the_service_would_read_it() -> None:
    """The library's own parser, on the value this repository generates.

    The one assertion that cannot be made by reading our own code: a `packages`
    list nested under `runtime` is the JSON form of the allowlist, and whether
    that form still accepts what we emit is a question about the dependency.
    """
    from pydantic_ai_backends.remote.env import _parse_runtimes

    parsed = _parse_runtimes(allowlist_value())
    assert sorted(parsed) == sorted(runtime.alias for runtime in CATALOG)
    for runtime in CATALOG:
        entry = parsed[runtime.alias]
        assert entry.mem_limit == runtime.mem_limit
        if runtime.image is not None:
            assert entry.image == runtime.image
        else:
            assert entry.runtime is not None
            assert entry.runtime.base_image == runtime.base_image
            assert entry.runtime.packages == runtime.packages
            assert entry.runtime.setup_commands == runtime.setup_commands


def test_a_runtime_naming_both_an_image_and_a_base_is_refused() -> None:
    with pytest.raises(ValidationError, match="exactly one of image or base_image"):
        SandboxRuntimeDefinition(
            alias="both", description="d", image="python:3.12-slim", base_image="python:3.12-slim"
        )


def test_a_runtime_naming_neither_an_image_nor_a_base_is_refused() -> None:
    with pytest.raises(ValidationError, match="exactly one of image or base_image"):
        SandboxRuntimeDefinition(alias="neither", description="d")


@pytest.mark.parametrize(
    "extra", [{"packages": ["pillow"]}, {"setup_commands": ["apt-get update"]}]
)
def test_a_ready_made_image_cannot_install_anything(extra: dict[str, Any]) -> None:
    """Installing needs a build, and a `image` entry has none.

    Accepted, this would be a runtime whose package list the service silently
    drops - the packages are in the catalogue, in the compose file, and not in
    the container.
    """
    with pytest.raises(ValidationError, match="builds nothing"):
        SandboxRuntimeDefinition(alias="ready", description="d", image="python:3.12-slim", **extra)


@pytest.mark.parametrize("value", ["2", "2G", "2gb", "big"])
def test_a_memory_limit_not_in_dockers_own_syntax_is_refused(value: str) -> None:
    with pytest.raises(ValidationError):
        SandboxRuntimeDefinition(
            alias="mem", description="d", image="python:3.12-slim", mem_limit=value
        )


def test_generating_the_line_leaves_the_prose_around_it_alone() -> None:
    """The regression: `.*?` walked straight through the comments below the key.

    A folded YAML scalar has no terminator, so the replaced span ends at a
    lookahead - and until that lookahead knew about `#`, one run deleted the six
    lines explaining `SANDBOXD_SANDBOX_UID` from all three files while reporting
    only that it had written a runtime.
    """
    from app.commands.sandbox_runtimes import _BLOCK

    text = (
        "    sandboxd:\n"
        "      environment:\n"
        "      SANDBOXD_RUNTIMES: >-\n"
        "        {}\n"
        "      # Why the next value is what it is.\n"
        '      SANDBOXD_SANDBOX_UID: "10001"\n'
    )

    replaced = _BLOCK.sub("      SANDBOXD_RUNTIMES: '{}'\n", text, count=1)

    assert "# Why the next value is what it is." in replaced
    assert 'SANDBOXD_SANDBOX_UID: "10001"' in replaced
    assert ">-" not in replaced


def test_the_catalogue_file_is_what_the_product_offers() -> None:
    """One runtime, and the file is the reason.

    Not a style assertion: `prewarm` builds every entry as the service starts, so
    a catalogue that grew back to eight aliases is eight `pip install`s in a
    start-up nobody is watching. A deployment adding a second runtime is expected
    to change this number deliberately.
    """
    path = Path(__file__).parents[1] / "app" / "core" / "catalog" / "sandbox_runtimes.json"
    assert len(json.loads(path.read_text())) == len(CATALOG) == 1
    assert CATALOG[0].alias == "workbench"


def _definition(**overrides: Any) -> SandboxRuntimeDefinition:
    fields: dict[str, Any] = {
        "alias": "ready",
        "description": "a ready-made image",
        "image": "python:3.12-slim",
    }
    return SandboxRuntimeDefinition(**(fields | overrides))


def test_a_ready_made_entry_names_its_image_and_nothing_to_build(monkeypatch) -> None:
    """The other shape, which the shipped catalogue happens not to use.

    Worth holding: `image` is the cheap runtime - no build, no wait on a cold
    host - and the entry the service reads has to name it at the top level rather
    than nested under `runtime`, which is where a built one goes.
    """
    monkeypatch.setattr("app.services.sandbox_runtimes.CATALOG", (_definition(),))

    entry = json.loads(allowlist_value())["ready"]

    assert entry == {"description": "a ready-made image", "image": "python:3.12-slim"}


def test_a_runtime_needing_a_network_says_nothing_when_the_service_gives_it_one(
    monkeypatch,
) -> None:
    """`network_mode` is emitted against the service-wide default, not absolutely.

    A deployment running its sandboxes on `bridge` service-wide would otherwise be
    handed a `network_mode` on every entry that needs one - true, but saying the
    opposite of what the service-wide setting already says.
    """
    monkeypatch.setattr("app.services.sandbox_runtimes.CATALOG", (_definition(needs_network=True),))

    assert "network_mode" not in json.loads(allowlist_value(network_mode="bridge"))["ready"]
    assert json.loads(allowlist_value())["ready"]["network_mode"] == "bridge"


class TestWritingTheComposeFiles:
    """The command, against a tree of its own rather than the repository's."""

    _BODY = (
        "services:\n"
        "  sandboxd:\n"
        "    environment:\n"
        "      SANDBOXD_RUNTIMES: >-\n"
        "        {}\n"
        "      SANDBOXD_NETWORK_MODE: none\n"
    )

    @classmethod
    def _tree(cls, tmp_path: Path, monkeypatch, *, body: str | None = None) -> Path:
        for name in COMPOSE_FILES:
            (tmp_path / name).write_text(body if body is not None else cls._BODY)
        monkeypatch.setattr("app.commands.sandbox_runtimes._repo_root", lambda: tmp_path)
        return tmp_path

    def test_printing_it_touches_nothing(self, tmp_path, monkeypatch, capsys) -> None:
        from app.commands.sandbox_runtimes import sandbox_runtimes

        self._tree(tmp_path, monkeypatch)

        sandbox_runtimes.callback(write=False)

        assert allowlist_value() in capsys.readouterr().out
        assert (tmp_path / COMPOSE_FILES[0]).read_text() == self._BODY

    def test_writing_replaces_the_folded_value_with_one_line(self, tmp_path, monkeypatch) -> None:
        from app.commands.sandbox_runtimes import sandbox_runtimes

        self._tree(tmp_path, monkeypatch)

        sandbox_runtimes.callback(write=True)

        written = (tmp_path / COMPOSE_FILES[0]).read_text()
        assert f"      SANDBOXD_RUNTIMES: '{compose_value()}'\n" in written
        assert ">-" not in written

    def test_a_file_already_carrying_it_is_left_alone(self, tmp_path, monkeypatch) -> None:
        """Idempotent, and it has to be: the command is what a test tells somebody
        to run, so a second run reporting a change would read as a failing gate."""
        from app.commands.sandbox_runtimes import sandbox_runtimes

        self._tree(tmp_path, monkeypatch)
        sandbox_runtimes.callback(write=True)
        before = {name: (tmp_path / name).read_text() for name in COMPOSE_FILES}

        sandbox_runtimes.callback(write=True)

        assert {name: (tmp_path / name).read_text() for name in COMPOSE_FILES} == before

    def test_a_service_wide_bridge_is_read_from_the_file_being_written(
        self, tmp_path, monkeypatch
    ) -> None:
        from app.commands.sandbox_runtimes import sandbox_runtimes

        self._tree(
            tmp_path,
            monkeypatch,
            body=self._BODY.replace("NETWORK_MODE: none", "NETWORK_MODE: bridge"),
        )

        sandbox_runtimes.callback(write=True)

        assert "network_mode" not in (tmp_path / COMPOSE_FILES[0]).read_text()

    def test_a_file_with_no_such_key_is_refused_rather_than_appended_to(
        self, tmp_path, monkeypatch
    ) -> None:
        """A missing key means the file was restructured, and guessing where the
        value belongs is how a generator writes a compose file nothing can start."""
        from app.commands.sandbox_runtimes import sandbox_runtimes

        self._tree(tmp_path, monkeypatch, body="services:\n  sandboxd:\n    image: sandboxd\n")

        with pytest.raises(SystemExit):
            sandbox_runtimes.callback(write=True)


class TestWhatTheModelIsTold:
    """The briefing a run appends to its instructions.

    Composed from the definition rather than written beside it, so a package
    added to the catalogue reaches the prompt in the same edit that reaches the
    image - which is the whole reason this is not a paragraph in
    `DEFAULT_INSTRUCTIONS`.
    """

    def test_it_names_every_package_the_image_already_carries(self) -> None:
        briefing = runtime_briefing("workbench")

        assert briefing is not None
        for package in CATALOG[0].packages:
            assert package in briefing

    def test_it_says_what_cannot_be_derived_from_the_fields(self) -> None:
        """`lit`, and the two gaps an agent otherwise finds by failing."""
        briefing = runtime_briefing("workbench")

        assert briefing is not None
        assert "lit parse" in briefing
        assert "LibreOffice" in briefing
        assert "no C compiler" in briefing

    def test_a_runtime_nothing_named_is_the_one_the_service_defaults_to(self) -> None:
        """The spec deferring to the connection, which defers to the host, is the
        common case rather than an edge one - and this repository generates the
        allowlist that makes the first entry the host's own default."""
        assert runtime_briefing(None) == runtime_briefing(CATALOG[0].alias)

    def test_an_alias_this_deployment_does_not_ship_is_not_described(self) -> None:
        assert runtime_briefing("somebody-elses-image") is None

    def test_a_ready_made_image_is_briefed_without_a_package_list(self, monkeypatch) -> None:
        """An `image` entry installs nothing, so there is nothing to list - and a
        sentence saying "already installed:" with nothing after it reads as a bug."""
        bare = SandboxRuntimeDefinition(
            alias="bare",
            description="d",
            image="python:3.12-slim",
            briefing=["Nothing but Python."],
        )
        monkeypatch.setattr("app.services.sandbox_runtimes.CATALOG", (bare,))

        briefing = runtime_briefing("bare")

        assert briefing is not None
        assert "already installed" not in briefing
        assert "Nothing but Python." in briefing

    def test_a_runtime_without_a_network_says_so_rather_than_omitting_it(self, monkeypatch) -> None:
        """An agent that believes it can install something cannot tell a refused
        network from a package that does not exist."""
        offline = SandboxRuntimeDefinition(
            alias="offline", description="d", base_image="python:3.12-slim", packages=["pandas"]
        )
        monkeypatch.setattr("app.services.sandbox_runtimes.CATALOG", (offline,))

        briefing = runtime_briefing("offline")

        assert briefing is not None
        assert "no network" in briefing
        assert "uv pip install" not in briefing


def test_the_environment_a_runtime_declares_reaches_the_service() -> None:
    """`MPLBACKEND=Agg` is a property of the image, and the service is the only
    thing that can set it - a run that has to remember it is a run that will not."""
    entry = json.loads(allowlist_value())["workbench"]

    assert entry["runtime"]["env_vars"]["MPLBACKEND"] == "Agg"


class TestTheRunsInstructions:
    """Appended per run, like a binding's prompt, and for the same reason.

    Which runtime a run gets is resolved from the spec, the connection and the
    host as it starts, so this is true of the run rather than of the published
    version - and the published version is what an approval was given for.
    """

    @staticmethod
    def _spec() -> Any:
        from app.agents.spec import AgentSpec

        return AgentSpec(name="Analyst", instructions="You are an analyst.")

    @staticmethod
    def _workspace(briefing: str | None) -> Any:
        from app.services.sandbox_workspace import OpenWorkspace

        return OpenWorkspace(
            backend=object(),
            kind="service",
            scope="conversation",
            scope_key="xc-1234",
            row_id=None,
            briefing=briefing,
        )

    def test_a_workspace_it_cannot_describe_leaves_the_spec_alone(self) -> None:
        from app.services.agent_runner import _with_workspace_briefing

        spec = self._spec()

        assert _with_workspace_briefing(spec, self._workspace(None)) is spec

    def test_the_briefing_is_appended_and_the_published_spec_is_untouched(self) -> None:
        from app.services.agent_runner import _with_workspace_briefing

        spec = self._spec()

        result = _with_workspace_briefing(spec, self._workspace("## Your workspace\n\n- pandas"))

        assert result.instructions.startswith("You are an analyst.")
        assert result.instructions.endswith("- pandas")
        assert spec.instructions == "You are an analyst."


def test_a_shell_variable_survives_composes_interpolation() -> None:
    """The defect that made every session a 502, and the only reason `$$` exists.

    Compose interpolates its own values, so `$arch` in a setup command is an
    undefined variable to it and the service is handed `case "" in amd64) ...` -
    a build that fails with `no Node build for `, quoted back through a 502, with
    nothing in the chain naming compose as the cause.
    """
    from app.commands.sandbox_runtimes import _repo_root as root

    written = (root() / COMPOSE_FILES[0]).read_text()
    line = next(one for one in written.splitlines() if "SANDBOXD_RUNTIMES:" in one)

    assert "$$(dpkg" in line or "$${node_arch}" in line, "a `$` reached compose unescaped"
    assert "$arch" not in line.replace("$$arch", "")
