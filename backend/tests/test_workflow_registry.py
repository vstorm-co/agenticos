"""Tests for the workflow node registry - the code/configuration boundary.

What is guarded: a graph may reference only what code registered, a lookup
names what is actually available when it does not, and two definitions
claiming the same `(id, version)` never let the second one win silently.
"""

import subprocess
import sys

import pytest

from app.core.exceptions import BadRequestError
from app.workflows._registry import REGISTRY, all_node_definitions, get, load_builtins, register
from app.workflows.contracts.definition import NodeDefinition, Port


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


def _definition(
    node_id: str = "test.node", version: int = 1, **overrides: object
) -> NodeDefinition:
    defaults: dict[str, object] = {
        "id": node_id,
        "version": version,
        "name": "Test node",
        "category": "test",
        "description": "A node registered only for this test.",
        "kind": "action",
        "config_schema": None,
        "input_schema": None,
        "output_schema": None,
        "ports": (Port(id="in", label="In", kind="input"),),
        "effect_kind": "pure",
        "retry_guarantee": "idempotent",
    }
    defaults.update(overrides)
    return NodeDefinition(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def clean_registry():
    """A registry key nothing else has claimed, cleaned up either way."""
    node_id = "test.registry_fixture"
    yield node_id
    REGISTRY.pop(node_id, None)


def test_register_makes_a_definition_reachable_by_get(clean_registry: str):
    definition = _definition(clean_registry)
    register(definition)
    assert get(clean_registry, 1) is definition


def test_register_keys_by_id_and_version_independently(clean_registry: str):
    v1 = _definition(clean_registry, version=1)
    v2 = _definition(clean_registry, version=2)
    register(v1)
    register(v2)
    assert get(clean_registry, 1) is v1
    assert get(clean_registry, 2) is v2


def test_registering_the_same_id_and_version_twice_is_refused(clean_registry: str):
    register(_definition(clean_registry))
    with pytest.raises(RuntimeError, match="already registered"):
        register(_definition(clean_registry))


def test_get_names_available_versions_for_a_known_id(clean_registry: str):
    register(_definition(clean_registry, version=1))
    with pytest.raises(BadRequestError) as excinfo:
        get(clean_registry, 99)
    assert excinfo.value.details is not None
    assert excinfo.value.details["available_versions"] == [1]


def test_get_names_available_ids_for_an_unknown_node():
    with pytest.raises(BadRequestError) as excinfo:
        get("no.such.node", 1)
    assert excinfo.value.details is not None
    assert "no.such.node" not in excinfo.value.details["available"]


def test_all_node_definitions_includes_every_registered_version(clean_registry: str):
    v1 = _definition(clean_registry, version=1)
    v2 = _definition(clean_registry, version=2)
    register(v1)
    register(v2)
    catalog = all_node_definitions()
    assert v1 in catalog
    assert v2 in catalog


class TestSelfLoading:
    """`load_builtins()` must not depend on the caller having warmed it up.

    Mirrors `tests/test_capability_registry.py::TestSelfLoading`: a subprocess
    is the only honest way to prove this, since the modules are already
    imported by the time any in-process test runs.
    """

    @staticmethod
    def _in_a_fresh_process(source: str) -> str:
        result = subprocess.run(
            [sys.executable, "-c", source],
            capture_output=True,
            text=True,
            check=False,
            cwd=__file__.rsplit("/tests/", 1)[0],
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def test_get_loads_builtins_without_an_explicit_call(self):
        output = self._in_a_fresh_process(
            "from app.workflows._registry import get; d = get('debug.echo', 1); print(d.id)"
        )
        assert output == "debug.echo"

    def test_all_node_definitions_loads_builtins_without_an_explicit_call(self):
        output = self._in_a_fresh_process(
            "from app.workflows._registry import all_node_definitions; "
            "print(len(all_node_definitions()) > 0)"
        )
        assert output == "True"
