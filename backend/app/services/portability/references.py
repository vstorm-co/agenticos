"""Discover references from owned schema metadata, including capability configs."""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, JsonValue, TypeAdapter

from app.agents.capabilities import get as get_capability
from app.agents.spec import AgentSpec
from app.schemas.resource_bundle import BundlePath, BundleResourceKind

_OBJECT = TypeAdapter(dict[str, JsonValue])


@dataclass(frozen=True, slots=True)
class ResourcePin:
    path: BundlePath
    kind: BundleResourceKind
    source_id: UUID | None
    is_key: bool = False
    parent_id: UUID | None = None
    source_number: int | None = None

    @property
    def bundle_key(self) -> str:
        if self.source_id is not None:
            return f"{self.kind.value}/{self.source_id}"
        if self.parent_id is None or self.source_number is None:
            raise ValueError("A numbered reference requires its owner and version")
        return f"{self.kind.value}/{self.parent_id}-v{self.source_number}"


def _object(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _resolved(
    schema: dict[str, JsonValue], definitions: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        if not reference.startswith("#/$defs/") or reference[8:] not in definitions:
            raise ValueError("A resource schema must use a declared local definition")
        return {
            **_resolved(_object(definitions[reference[8:]]), definitions),
            **{k: v for k, v in schema.items() if k != "$ref"},
        }
    return schema


def _shape(
    schema: dict[str, JsonValue], definitions: Mapping[str, JsonValue], value: JsonValue
) -> dict[str, JsonValue]:
    schema = _resolved(schema, definitions)
    branches = schema.get("oneOf", schema.get("anyOf"))
    if not isinstance(branches, list):
        return schema
    for branch in branches:
        candidate = _resolved(_object(branch), definitions)
        if candidate.get("type") == "null":
            continue
        properties = _object(candidate.get("properties"))
        if isinstance(value, dict) and any(
            "const" in _object(prop) and value.get(name) != _object(prop)["const"]
            for name, prop in properties.items()
        ):
            continue
        return _shape(
            {
                **candidate,
                **{k: v for k, v in schema.items() if k not in ("oneOf", "anyOf", "$ref")},
            },
            definitions,
            value,
        )
    raise ValueError("A resource value does not match any declared schema branch")


def _kind(value: str) -> BundleResourceKind:
    return BundleResourceKind.KNOWLEDGE_BASE if value == "collection" else BundleResourceKind(value)


def resource_pins(model: BaseModel) -> tuple[ResourcePin, ...]:
    """Find schema-declared UUID bindings without inspecting prose or arbitrary JSON.

    An unmarked UUID field is an authoring error, not permission to guess its
    resource type from its spelling. Capability configs contribute their owned
    schemas even though AgentSpec stores them as an open JSON object.
    """
    schema = _OBJECT.validate_python(type(model).model_json_schema())
    data = _OBJECT.validate_python(model.model_dump(mode="json"))
    found: list[ResourcePin] = []

    def walk(
        value: JsonValue,
        declaration: dict[str, JsonValue],
        definitions: Mapping[str, JsonValue],
        path: BundlePath,
        parent: Mapping[str, JsonValue] | None = None,
    ) -> None:
        if value is None:
            return
        declaration = _shape(declaration, definitions, value)
        resource = declaration.get("x-resource")
        if isinstance(resource, str):
            parent_field = declaration.get("x-resource-parent")
            parent_id: UUID | None = None
            if isinstance(parent_field, str):
                parent_value = None if parent is None else parent.get(parent_field)
                if not isinstance(parent_value, str):
                    raise TypeError(
                        "A versioned resource reference must identify its owning resource"
                    )
                parent_id = UUID(parent_value)
            values: list[tuple[str | int | None, JsonValue]]
            if isinstance(value, list):
                values = list(enumerate(value))
            elif isinstance(value, dict):
                values = list(value.items())
            else:
                values = [(None, value)]
            for index, item in values:
                if _kind(resource) == BundleResourceKind.SKILL_VERSION and type(item) is int:
                    if parent_id is None or item < 1:
                        raise ValueError("A skill version requires its owner and a positive number")
                    found.append(
                        ResourcePin(
                            path if index is None else (*path, index),
                            _kind(resource),
                            None,
                            parent_id=parent_id,
                            source_number=item,
                        )
                    )
                    continue
                if not isinstance(item, str):
                    raise TypeError("A resource binding must contain UUID strings")
                found.append(
                    ResourcePin(
                        path if index is None else (*path, index),
                        _kind(resource),
                        UUID(item),
                        parent_id=parent_id,
                    )
                )
            return
        if declaration.get("format") == "uuid":
            raise ValueError(f"UUID field {path!r} must declare x-resource metadata")
        if isinstance(value, dict):
            properties = dict(_object(declaration.get("properties")))
            if declaration.get("title") == "CapabilityBindingSpec":
                capability_id = value.get("id")
                if not isinstance(capability_id, str):
                    raise TypeError("A capability binding must declare its id")
                capability = get_capability(capability_id)
                if capability.config_schema is not None:
                    config = _OBJECT.validate_python(capability.config_schema.model_json_schema())
                    properties["config"] = config
                    definitions = {**definitions, **_object(config.get("$defs"))}
            key_schema = _object(declaration.get("propertyNames"))
            key_resource = key_schema.get("x-resource")
            if key_schema.get("format") == "uuid" and not isinstance(key_resource, str):
                raise ValueError("UUID dictionary keys must declare x-resource metadata")
            additional = _object(declaration.get("additionalProperties"))
            for name, item in value.items():
                if isinstance(key_resource, str):
                    found.append(
                        ResourcePin((*path, name), _kind(key_resource), UUID(name), is_key=True)
                    )
                walk(
                    item,
                    _object(properties.get(name, additional)),
                    definitions,
                    (*path, name),
                    value,
                )
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, _object(declaration.get("items")), definitions, (*path, index))

    walk(data, schema, _object(schema.get("$defs")), ())
    return tuple(found)


def agent_pins(spec: AgentSpec) -> tuple[ResourcePin, ...]:
    """The canonical reference inventory of an agent's effective spec."""
    return resource_pins(spec)
