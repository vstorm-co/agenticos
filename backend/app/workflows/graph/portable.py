"""A graph as it travels between deployments: with nothing that names this one.

A step's config can pin a resource - an agent, a table, a vault secret, a
member, a bot, a sandbox host, another workflow - by its id, and a binding can
carry a table or a file reference. None of those ids means anything on another
deployment, and a secret's is not for handing around at all, so a portable
graph has every one of them taken out and listed, for whoever imports it to
choose again. Pinned test data goes too: it is a real run's output.

What counts as a resource is what the step's own config schema marks with
`x-resource`, the same keyword the editor draws a picker for, so a new picker
is covered here without a second list.

An agent configured in a step (`x-agent-spec`) travels, since its instructions
and capabilities are the point of exporting it - but every id in it is this
deployment's: its model, its collections, skills and context files, a delegate,
an MCP server, a secret in a capability's settings. Those go, each listed, and
the rest of the spec stays.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.exceptions import BadRequestError
from app.workflows import _registry
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import WorkflowGraph

_MISSING = object()
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Unresolved:
    """One pin taken out: on which step - by id and by the name it shows - in
    which field, and what it chose."""

    node_id: UUID
    step: str
    field: str
    kind: str


def _resolve(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """`schema` with its `$ref` followed, and an optional field's non-null branch
    taken - what the value, when there is one, has to match."""
    ref = schema.get("$ref")
    if isinstance(ref, str):
        rest = {key: item for key, item in schema.items() if key != "$ref"}
        return _resolve({**defs[ref.removeprefix("#/$defs/")], **rest}, defs)
    branch = next(
        (branch for branch in schema.get("anyOf", ()) if branch.get("type") != "null"), None
    )
    if branch is not None:
        rest = {key: item for key, item in schema.items() if key != "anyOf"}
        return _resolve({**branch, **rest}, defs)
    return schema


def _strip(
    value: Any,
    schema: dict[str, Any],
    defs: dict[str, Any],
    path: str,
    found: list[tuple[str, str]],
) -> Any:
    """`value` with every pinned resource under it taken out, each noted in `found`."""
    resolved = _resolve(schema, defs)
    kind = resolved.get("x-resource")
    if isinstance(kind, str):
        found.append((path, kind))
        return _MISSING
    if resolved.get("x-agent-spec") is True and isinstance(value, dict):
        return _without_ids(value, path, found)
    if isinstance(value, dict):
        properties = resolved.get("properties", {})
        kept: dict[str, Any] = {}
        for key, item in value.items():
            stripped = _strip(
                item, properties.get(key, {}), defs, f"{path}.{key}" if path else key, found
            )
            if stripped is not _MISSING:
                kept[key] = stripped
        return kept
    if isinstance(value, list):
        items = resolved.get("items", {})
        return [
            stripped
            for index, item in enumerate(value)
            if (stripped := _strip(item, items, defs, f"{path}.{index}", found)) is not _MISSING
        ]
    return value


def _names_a_row(value: Any) -> bool:
    return isinstance(value, str) and _UUID.fullmatch(value) is not None


def _without_ids(value: Any, path: str, found: list[tuple[str, str]]) -> Any:
    """An agent spec's value with every id of this deployment taken out.

    By value rather than by schema, because a capability's settings are a free
    dictionary its own schema describes, and a secret's id is in there. An id
    goes, and so does the object that would be nothing without it - a list entry
    naming a server or a delegate - rather than leave a reference half made.
    """
    if _names_a_row(value):
        found.append((path, "agent_spec"))
        return _MISSING
    if isinstance(value, dict):
        kept: dict[str, Any] = {}
        for key, item in value.items():
            stripped = _without_ids(item, f"{path}.{key}", found)
            if stripped is not _MISSING:
                kept[key] = stripped
        return kept
    if isinstance(value, list):
        kept_items = []
        for index, item in enumerate(value):
            if isinstance(item, dict) and any(_names_a_row(field) for field in item.values()):
                found.append((f"{path}.{index}", "agent_spec"))
                continue
            stripped = _without_ids(item, f"{path}.{index}", found)
            if stripped is not _MISSING:
                kept_items.append(stripped)
        return kept_items
    return value


def portable(graph: WorkflowGraph) -> tuple[WorkflowGraph, list[Unresolved]]:
    """`graph` with no resource ids and no pinned data, and what was taken out.

    Raises:
        GraphValidationError: A step is of a kind or version this deployment
            does not have - every such step named.
    """
    unknown = []
    for node in graph.nodes:
        try:
            _registry.get(node.definition_id, node.definition_version)
        except BadRequestError:
            unknown.append(
                (
                    f"nodes.{node.id}",
                    f"This deployment has no {node.definition_id} step "
                    f"at version {node.definition_version}",
                )
            )
    if unknown:
        raise GraphValidationError(unknown)
    unresolved: list[Unresolved] = []
    names = {
        node.id: node.label or _registry.get(node.definition_id, node.definition_version).name
        for node in graph.nodes
    }
    nodes = []
    for node in graph.nodes:
        definition = _registry.get(node.definition_id, node.definition_version)
        config = node.config
        if definition.config_schema is not None:
            schema = definition.config_schema.model_json_schema()
            found: list[tuple[str, str]] = []
            config = _strip(node.config, schema, schema.get("$defs", {}), "", found)
            unresolved.extend(
                Unresolved(node.id, names[node.id], field, kind) for field, kind in found
            )
        nodes.append(node.model_copy(update={"config": config, "pinned_output": None}))
    bindings = []
    for binding in graph.bindings:
        if binding.source.kind in ("table", "file"):
            step = names.get(binding.target_node_id, str(binding.target_node_id))
            unresolved.append(
                Unresolved(binding.target_node_id, step, binding.target_field, binding.source.kind)
            )
            continue
        bindings.append(binding)
    return graph.model_copy(update={"nodes": tuple(nodes), "bindings": tuple(bindings)}), unresolved
