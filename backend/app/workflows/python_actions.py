"""Author-selected workflow actions callable by name from a Python actions step."""

import builtins
import keyword
import re
from copy import copy
from functools import cache
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationInfo,
    field_validator,
)
from pydantic.fields import FieldInfo
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.workflows import _registry
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition
from app.workflows.contracts.script import MAX_ACTION_CALLS
from app.workflows.nodes.code_python_simple._handler import PythonSimpleConfig

PYTHON_ACTIONS = "code.python.actions"


def python_callable(definition: NodeDefinition) -> bool:
    """Expose work and decisions with their own result, not entry, graph wiring or response."""
    return (
        (definition.kind == "action" or definition.exclusive_branches)
        and definition.handler is not None
        and definition.category not in {TRIGGER_CATEGORY, "logic"}
        and not definition.loop_body_only
        and definition.id
        not in {
            PYTHON_ACTIONS,
            "core.output",
            "webhook.respond",
            "error.handle",  # Reads an arriving graph error rather than its own input.
        }
    )


_ALIAS_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*$"
_RESERVED_NAMES = frozenset(
    [*keyword.kwlist, "args", *(n for n in dir(builtins) if not n.startswith("_"))]
)


def _alias(name: str) -> str:
    if not re.fullmatch(_ALIAS_PATTERN, name) or name in _RESERVED_NAMES:
        raise ValueError("Choose a Python function name that is not reserved or a builtin")
    return name


ActionAlias = Annotated[str, Field(min_length=1, max_length=64), AfterValidator(_alias)]


def action_definition(action_type: str, version: int) -> NodeDefinition:
    """Resolve a registered action version that can be called outside graph wiring."""
    try:
        definition = _registry.get(action_type, version)
    except BadRequestError as exc:
        raise ValueError(exc.message) from exc
    if not python_callable(definition):
        raise ValueError(f"'{action_type}' is not callable from a Python step")
    return definition


def _bindable(field: FieldInfo | None) -> bool:
    metadata = field.json_schema_extra if field is not None else None
    return (
        isinstance(metadata, dict)
        and metadata.get("x-bindable") is True
        and "x-resource" not in metadata
    )


@cache
def _binding_schema(
    schema: type[BaseModel], input_schema: type[BaseModel] | None
) -> type[BaseModel]:
    """Validate every fixed setting without requiring data supplied by the script.

    The subclass retains the node's field and model validators, and its type for
    the node's resource checker. Only omission gets a default: an explicit bad
    value (including null) is checked just as in the native schema. This model
    is never handed to the handler; resolve_call validates the original schema.
    """
    overrides: dict[str, FieldInfo] = {}
    for name, field in schema.model_fields.items():
        if (
            field.is_required()
            and _bindable(field)
            and not (input_schema and name in input_schema.model_fields)
        ):
            optional = copy(field)
            optional.default = None
            optional.validate_default = False
            overrides[name] = optional
    if not overrides:
        return schema
    namespace = {
        "__annotations__": {name: field.annotation for name, field in overrides.items()},
        "__module__": schema.__module__,
        **overrides,
    }
    return type(f"{schema.__name__}Binding", (schema,), namespace)


def _typed_config(
    definition: NodeDefinition, values: dict[str, JsonValue], *, for_binding: bool = False
) -> BaseModel | None:
    schema = definition.config_schema
    if schema is None:
        if values:
            raise ValueError(f"'{definition.id}' declares no configuration")
        return None
    if for_binding:
        schema = _binding_schema(schema, definition.input_schema)
    return schema.model_validate(values)


class ActionBinding(BaseModel):
    """A fixed action version and default config; only declared data fields vary per call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str = Field(min_length=1)
    version: int = Field(default=1, ge=1, strict=True)
    config: dict[str, JsonValue] = Field(default_factory=dict, validate_default=True)

    @field_validator("config")
    @classmethod
    def _check_config(
        cls, values: dict[str, JsonValue], info: ValidationInfo
    ) -> dict[str, JsonValue]:
        # Invalid type or version has its own field error. Put action-specific
        # errors under config, so the editor highlights the bound action's field.
        if "type" in info.data and "version" in info.data:
            _typed_config(
                action_definition(info.data["type"], info.data["version"]),
                values,
                for_binding=True,
            )
        return values

    def definition(self) -> NodeDefinition:
        return action_definition(self.type, self.version)

    def binding_config(self) -> BaseModel | None:
        return _typed_config(self.definition(), self.config, for_binding=True)

    def resolve_call(
        self, arguments: dict[str, JsonValue]
    ) -> tuple[BaseModel | None, BaseModel | None]:
        """Validate script keywords as native inputs or explicitly bindable config data."""
        definition = self.definition()
        input_schema, config_schema = definition.input_schema, definition.config_schema
        values: dict[str, JsonValue] = {}
        config = self.config.copy()
        for name, value in arguments.items():
            if input_schema is not None and name in input_schema.model_fields:
                values[name] = value
                continue
            field = config_schema.model_fields.get(name) if config_schema is not None else None
            if not _bindable(field):
                raise ValueError(f"'{self.type}' has no callable data field '{name}'")
            config[name] = value
        inputs = None
        if input_schema is not None and (values or input_schema is not config_schema):
            # debug.echo uses the same defaultable schema for config and input.
            # With no explicit input its handler reads the configured default.
            inputs = input_schema.model_validate(values)
        return _typed_config(definition, config), inputs


class PythonActionsConfig(PythonSimpleConfig):
    actions: dict[ActionAlias, ActionBinding] = Field(
        default_factory=dict,
        max_length=MAX_ACTION_CALLS,
        description="Python function names and the versioned workflow actions they call.",
        json_schema_extra={
            "x-python-actions": True,
            "propertyNames": {
                "pattern": _ALIAS_PATTERN,
                "maxLength": 64,
                "not": {"enum": [*sorted(_RESERVED_NAMES)]},
            },
        },
    )


async def action_resource_problems(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Apply the same deployment scopes and publisher access checks as a direct step."""
    # Lazy as in graph.validate: the agent registry indirectly imports workflow validation.
    from app.services.agent_registry import DEFAULT_GRANTED_SCOPES

    assert isinstance(config, PythonActionsConfig)
    problems: list[tuple[str, str]] = []
    for alias, action in config.actions.items():
        definition = action.definition()
        path = f"actions.{alias}"
        missing = definition.scopes - DEFAULT_GRANTED_SCOPES
        if missing:
            problems.append(
                (path, f"This deployment has not granted: {', '.join(sorted(missing))}")
            )
        validated = action.binding_config()
        if definition.resource_check is not None and validated is not None:
            for field, message in await definition.resource_check(db, ctx, validated):
                problems.append((f"{path}.config.{field}", message))
    return problems
