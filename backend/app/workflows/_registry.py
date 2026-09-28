"""Node registry - the workflow-side twin of `app.agents.capabilities._registry`.

Same shape, same reasons: nodes are written in typed, tested Python while an
organization composes graphs without writing any, so code registers what a
graph may reference and configuration (the graph itself) can only reach what
was registered.

Keyed by id **and** version, unlike the capability registry: a published graph
pins `(id, version)`, and an old graph may still reference a version this
deployment has since superseded by a breaking one. `register()` never lets a
later import silently replace an earlier one at the same key - almost always a
copy-paste in a new module, and letting the second win would make a workflow's
behaviour depend on import order.
"""

from __future__ import annotations

import logging

from app.core.exceptions import BadRequestError
from app.workflows.contracts.definition import NodeDefinition

logger = logging.getLogger(__name__)

REGISTRY: dict[str, dict[int, NodeDefinition]] = {}

# Whether the builtin node modules have been imported. Not a cache of the
# registry itself - tests add and remove entries around it - only of the import.
_builtins_loaded = False


def register(definition: NodeDefinition) -> NodeDefinition:
    """Register a node definition.

    Raises:
        RuntimeError: A `(id, version)` pair is already registered by a
            different definition. Ids and versions are part of every stored
            graph, so two definitions claiming one silently would make a
            workflow's behaviour depend on import order.
    """
    versions = REGISTRY.setdefault(definition.id, {})
    existing = versions.get(definition.version)
    if existing is not None and existing is not definition:
        raise RuntimeError(
            f"Node '{definition.id}' version {definition.version} is already registered "
            f"by {existing.name!r}. Ids and versions are part of every stored graph and "
            "must be unique."
        )
    versions[definition.version] = definition
    return definition


def get(node_id: str, version: int) -> NodeDefinition:
    """Look up one node definition by its pinned identity.

    Raises:
        BadRequestError: No such id, or no such version of it - naming what
            versions are available for that id, if any.
    """
    load_builtins()
    versions = REGISTRY.get(node_id)
    if versions is None:
        raise BadRequestError(
            message=f"Unknown workflow node: {node_id}",
            details={"node_id": node_id, "available": sorted(REGISTRY)},
        )
    definition = versions.get(version)
    if definition is None:
        raise BadRequestError(
            message=f"Unknown version of workflow node '{node_id}': {version}",
            details={
                "node_id": node_id,
                "version": version,
                "available_versions": sorted(versions),
            },
        )
    return definition


def all_node_definitions() -> list[NodeDefinition]:
    """Every registered node, every version, ordered for a stable catalog."""
    load_builtins()
    return sorted(
        (definition for versions in REGISTRY.values() for definition in versions.values()),
        key=lambda d: (d.category, d.name, d.version),
    )


def load_builtins() -> None:
    """Import node packages so their `register()` calls run.

    A package nobody imports does not exist as far as the catalog is
    concerned. Every lookup calls this first, so the CLI, a worker and a
    migration script all see the same registry the API does; the flag keeps
    that free after the first call.
    """
    global _builtins_loaded
    if _builtins_loaded:
        return

    from app.workflows.nodes import debug_echo  # noqa: F401 - imported for side effects

    _builtins_loaded = True
    logger.debug("Workflow node registry loaded with %d entries", len(REGISTRY))
