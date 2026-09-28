"""The shape every workflow node package has, enforced rather than described.

Sibling of `tests/test_capability_layout.py`: a node package that drifts from
this shape is a node whose logic and whose registration nobody can find in the
same place twice.

- `__init__.py`   - registration and the public surface: `@register`/`register(...)`
                    and nothing else.
- `_handler.py`   - the `NodeHandler` implementation.
- `README.md`     - why this node exists and what it deliberately does not do.
"""

from pathlib import Path

import pytest

from app.workflows._registry import all_node_definitions, load_builtins

NODES_ROOT = Path(__file__).resolve().parents[1] / "app" / "workflows" / "nodes"


def packages() -> list[Path]:
    return sorted(
        path for path in NODES_ROOT.iterdir() if path.is_dir() and not path.name.startswith("__")
    )


@pytest.mark.parametrize("package", packages(), ids=lambda path: path.name)
def test_every_node_has_a_handler_module(package: Path):
    assert (package / "_handler.py").is_file()


@pytest.mark.parametrize("package", packages(), ids=lambda path: path.name)
def test_every_node_has_a_readme(package: Path):
    assert (package / "README.md").is_file()


@pytest.mark.parametrize("package", packages(), ids=lambda path: path.name)
def test_registration_happens_in_init_and_nowhere_else(package: Path):
    for module in package.glob("*.py"):
        if module.name == "__init__.py":
            continue
        assert "register(" not in module.read_text(encoding="utf-8"), (
            f"{module} registers a node outside __init__.py"
        )


def test_every_package_on_disk_is_reachable_from_the_catalog():
    """A package nobody imports from `load_builtins` does not exist as far as
    the catalog is concerned - the same drift `load_builtins` documents.

    Compares by count rather than by id prefix: a node id need not share its
    package's directory name (`debug.echo` lives in `nodes/debug_echo/`).
    """
    load_builtins()
    registered_packages = {definition.id.split(".")[0] for definition in all_node_definitions()}
    on_disk = {package.name for package in packages()}
    assert len(registered_packages) == len(on_disk)
