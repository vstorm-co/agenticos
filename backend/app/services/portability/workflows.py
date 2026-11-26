"""Workflow definitions and reference ownership in selectable resource bundles."""

from uuid import UUID

from pydantic import ConfigDict, Field, JsonValue, TypeAdapter, model_validator

from app.core.exceptions import BadRequestError
from app.schemas.base import BaseSchema
from app.schemas.resource_bundle import BundlePath
from app.schemas.workflow import MAX_TAGS, WorkflowSettings, WorkflowTag
from app.services.portability.references import ResourcePin, schema_resource_pins
from app.workflows import _registry
from app.workflows.graph.model import WorkflowGraph
from app.workflows.triggers import WEBHOOK

_OBJECT = TypeAdapter(dict[str, JsonValue])


class WorkflowBundleSettings(WorkflowSettings):
    error_workflow_id: UUID | None = Field(
        default=None, json_schema_extra={"x-resource": "workflow"}
    )


class WorkflowContent(BaseSchema):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[WorkflowTag] = Field(default_factory=list, max_length=MAX_TAGS)
    settings: WorkflowBundleSettings = Field(default_factory=WorkflowBundleSettings)
    graph: WorkflowGraph | None = None
    omitted: tuple[BundlePath, ...] = ()

    @model_validator(mode="after")
    def no_run_data(self) -> WorkflowContent:
        if self.graph is not None:
            nodes = []
            omitted = list(self.omitted)
            for index, node in enumerate(self.graph.nodes):
                if node.definition_id == WEBHOOK and node.config.get("source_id") is not None:
                    # A source is live tenant authority, not portable configuration.
                    config = {
                        key: value for key, value in node.config.items() if key != "source_id"
                    }
                    config["require_source"] = True
                    node = node.model_copy(update={"config": config})
                    omitted.append(("graph", "nodes", index, "config", "source_id"))
                nodes.append(node)
            self.graph = self.graph.model_copy(update={"nodes": tuple(nodes)})
            self.omitted = tuple(dict.fromkeys(omitted))
            if any(node.pinned_output is not None for node in self.graph.nodes):
                raise ValueError("Workflow bundles cannot include pinned run output")
            if any(
                binding.source.kind == "table" and binding.source.column_ids is not None
                for binding in self.graph.bindings
            ):
                raise ValueError("Select table columns again at the destination")
            if any(binding.source.kind == "file" for binding in self.graph.bindings):
                raise ValueError("Workflow bundles cannot include uploaded-file bindings")
        return self


def workflow_pins(content: WorkflowContent) -> tuple[ResourcePin, ...]:
    try:
        return _workflow_pins(content)
    except (TypeError, ValueError) as exc:
        raise BadRequestError(message="A workflow resource reference is malformed") from exc


def _workflow_pins(content: WorkflowContent) -> tuple[ResourcePin, ...]:
    found = list(
        schema_resource_pins(
            _OBJECT.validate_python(content.settings.model_dump(mode="json")),
            _OBJECT.validate_python(WorkflowBundleSettings.model_json_schema()),
            prefix=("settings",),
        )
    )
    if content.graph is None:
        return tuple(found)
    for index, node in enumerate(content.graph.nodes):
        definition = _registry.get(node.definition_id, node.definition_version)
        if definition.config_schema is not None:
            found.extend(
                schema_resource_pins(
                    _OBJECT.validate_python(node.config),
                    _OBJECT.validate_python(definition.config_schema.model_json_schema()),
                    prefix=("graph", "nodes", index, "config"),
                )
            )
    for index, binding in enumerate(content.graph.bindings):
        if binding.source.kind == "table":
            from app.schemas.resource_bundle import BundleResourceKind

            found.append(
                ResourcePin(
                    ("graph", "bindings", index, "source", "table_id"),
                    BundleResourceKind.TABLE,
                    binding.source.table_id,
                )
            )
            found.append(
                ResourcePin(
                    ("graph", "bindings", index, "source", "schema_version"),
                    BundleResourceKind.TABLE,
                    binding.source.table_id,
                    source_number=binding.source.schema_version,
                )
            )
    return tuple(found)


def workflow_omissions(content: WorkflowContent) -> dict[BundlePath, BundlePath]:
    """Required resource IDs remove their containing binding, never a dangling ID."""
    from app.workflows.python_actions import PYTHON_ACTIONS

    node_types: dict[str | int, str] = (
        {}
        if content.graph is None
        else {index: node.definition_id for index, node in enumerate(content.graph.nodes)}
    )
    omitted: dict[BundlePath, BundlePath] = {}
    for pin in workflow_pins(content):
        path = pin.path
        if path[:2] == ("graph", "bindings"):
            omitted[path] = path[:3]
        elif path[:2] == ("graph", "nodes"):
            if (
                len(path) >= 7
                and path[4] == "actions"
                and node_types.get(path[2]) == PYTHON_ACTIONS
            ):
                omitted[path] = path[:6]
                continue
            if len(path) >= 6 and path[4] == "table":
                omitted[path] = path[:5]
                continue
            # Config resource fields are removed individually; publish validation
            # reports missing required fields while retaining the node and its wires.
            if len(path) >= 6 and path[4] == "agent" and path[5] in ("agent_id", "version_id"):
                omitted[path] = path[:5]
                continue
            for field in (
                "mcp_servers",
                "skill_bindings",
                "subagents",
                "table_bindings",
                "external_agents",
            ):
                if field in path:
                    offset = path.index(field)
                    omitted[path] = path[: offset + 2]
                    break
    return omitted
