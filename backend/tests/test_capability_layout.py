"""The shape every capability package has, enforced rather than described.

Ten packages under `app/agents/capabilities/` had four different layouts: some
built their toolset inside the capability class, one kept everything in
`__init__.py`, and finding "what does this capability actually offer the model"
meant opening three files to learn which one it was in this time.

The layout is now:

- `__init__.py`   - registration and the public surface: the config model, one
                    `@register`, `__all__`. Nothing else.
- `_capability.py`- the `AbstractCapability` implementation.
- `_toolset.py`   - the tools, where the capability has any. A tool's name and
                    docstring are *prompt* - the model reads them before
                    deciding to call - so they live in one predictable place.
- anything else   - internals (`_search.py`, `_sandbox.py`, `_policy.py`).

These tests are the thing that keeps that true. A convention only a document
knows about is a convention that is already drifting.
"""

from pathlib import Path

import pytest

from app.agents.capabilities._registry import all_capabilities, load_builtins

CAPABILITY_ROOT = Path(__file__).resolve().parents[1] / "app" / "agents" / "capabilities"

# Capabilities offering no tools at all, and why. Each is a decision, not an
# omission: a `_toolset.py` here would be an empty module standing in for one.
TOOLLESS = {
    # Goes into the instructions - a model that has to *decide* to look up the
    # date mostly does not, and answers from its training data instead.
    "clock",
    # Changes how the model runs, not what it can do.
    "thinking",
    # Enforcement wrapped around every model request; never a tool.
    "budget",
    # Gates other capabilities' tools. Owning one of its own would mean an
    # approval that could itself be approved.
    "approval",
}

# Capabilities whose tools come from a library rather than this repository.
EXTERNAL_TOOLSET = {
    # `pydantic_ai_skills.SkillsToolset`, filtered to the safe three.
    "skills",
    # `pydantic_ai_backends.ConsoleCapability`. The tool *text* is still this
    # repository's - `_capability.py` declares it once and hands the same
    # descriptions to the library - so the reason `_toolset.py` exists is
    # satisfied without a module that would only re-export somebody else's
    # functions.
    "sandbox",
    # `pydantic_ai_harness.planning.PlanningToolset`. Same bargain as `sandbox`:
    # the nine tool descriptions are declared in `_capability.py` and handed to the
    # library through `descriptions=`, so the text a reader edits still lives here.
    "planning",
}


def packages() -> list[Path]:
    return sorted(
        path
        for path in CAPABILITY_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    )


@pytest.mark.parametrize("package", packages(), ids=lambda path: path.name)
def test_every_capability_has_a_capability_module(package: Path):
    """Where the thing itself lives, uniformly.

    `thinking` returns Pydantic AI's own class and still has one - a package
    shaped like nine others costs one file and saves every reader the question.
    """
    assert (package / "_capability.py").is_file()


@pytest.mark.parametrize("package", packages(), ids=lambda path: path.name)
def test_a_capability_with_tools_keeps_them_in_a_toolset_module(package: Path):
    """Tool text is prompt, and prompt has to be findable.

    An author rewriting what a tool tells the model is editing against this
    file; nested inside a `get_toolset` closure it is somewhere only the author
    of that class knows.
    """
    if package.name in TOOLLESS or package.name in EXTERNAL_TOOLSET:
        pytest.skip(f"{package.name} offers no tools of its own")
    assert (package / "_toolset.py").is_file()


@pytest.mark.parametrize("package", packages(), ids=lambda path: path.name)
def test_registration_happens_in_init_and_nowhere_else(package: Path):
    """One place to look for what the catalog will show.

    A `@register` in a submodule only fires if something imports that module,
    which is how a capability disappears from the Builder without a single test
    failing.
    """
    for module in package.glob("*.py"):
        if module.name == "__init__.py":
            continue
        assert "@register" not in module.read_text(encoding="utf-8"), (
            f"{module} registers a capability outside __init__.py"
        )


def test_every_package_that_registers_is_reachable_from_the_catalog():
    """The other half: a package with a `@register` nobody imports is invisible."""
    load_builtins()
    registered = {definition.id for definition in all_capabilities()}
    on_disk = {
        package.name
        for package in packages()
        if "@register" in (package / "__init__.py").read_text(encoding="utf-8")
    }
    # `code_execution` registers as `run_python`; compare by count and by the
    # packages that deliberately do not register at all.
    unregistered = {package.name for package in packages()} - on_disk
    assert unregistered == {"budget", "approval"}, (
        "budget and approval are built unconditionally by the factory; anything "
        "else missing from the registry is a capability nobody can switch on"
    )
    assert len(registered) == len(on_disk)
