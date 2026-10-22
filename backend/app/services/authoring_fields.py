"""The fields of an agent's spec the authoring assistant may propose a change to.

Pure functions over specs, like :mod:`app.services.authoring_hunks`, so the rules
can be read and tested apart from the database.

**An allow-list, not a schema walk.** `TARGETS` names every field a `spec_field`
hunk may address; anything else - suites, thresholds, datasets, budgets,
observability, a delegate's pin - is not a path at all, and
`tests/test_authoring_targets.py` pins the list. A path is `/`-separated:
`model_settings/temperature`, `capabilities/<id>/config`,
`mcp_servers/<ref>/allowed_tools`.

**A hunk compares the draft with what it read.** `set` holds the value the draft
had (`base`); `add` holds the item it adds and `remove` the item it removes, so
Undo can put it back. A draft that moved since - the value edited by hand, the
item already added or already gone - makes the hunk stale, and it is never
written over that edit. Undo refuses the same way once the accepted value was
edited.

**Approval only tightens.** Loosening a gate widens what runs unattended, which
is a governance decision rather than a quality one, so a proposal may move a
capability or a tool from `never` towards `required` and not back. A capability
the proposal adds arrives with every tool that writes gated. A safeguard - a
capability the registry marks `protective` - may be added, and never removed or
reconfigured, for the same reason.

**A configuration is a target only where the capability opts in.** A capability
the registry marks `tunable` has a configuration about quality alone; any other
- one that reaches a URL, a domain, a connection, a provider or personal data -
is neither reconfigured nor added configured, and a new capability is not a
target until somebody decides it should be. Subagents are never added at all:
their configuration holds whole agents - instructions, models, capabilities and
their approval - which the checks on one binding never see, so a specialist's
description is the one part of them a proposal may change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.agents.capabilities import REGISTRY, load_builtins
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import AppException
from app.db.models.authoring import FieldOp

_SUBAGENTS = "subagents"
_MODEL_SETTINGS = ("temperature", "top_p", "max_tokens", "timeout", "parallel_tool_calls")
_STRICTNESS = {"never": 0, "default": 1, "required": 2}

TARGETS: tuple[tuple[str, tuple[FieldOp, ...]], ...] = (
    ("description", (FieldOp.SET,)),
    ("model_profile_id", (FieldOp.SET,)),
    *((f"model_settings/{name}", (FieldOp.SET,)) for name in _MODEL_SETTINGS),
    ("max_steps", (FieldOp.SET,)),
    ("capabilities", (FieldOp.ADD, FieldOp.REMOVE)),
    ("capabilities/{capability}/config", (FieldOp.SET,)),
    ("capabilities/{capability}/approval", (FieldOp.SET,)),
    ("capabilities/{capability}/tool_approval/{tool}", (FieldOp.SET,)),
    ("capabilities/subagents/inline/{specialist}/description", (FieldOp.SET,)),
    ("collection_ids", (FieldOp.ADD, FieldOp.REMOVE)),
    ("context_ids", (FieldOp.ADD, FieldOp.REMOVE)),
    ("mcp_servers/{server}/allowed_tools", (FieldOp.SET,)),
)
"""Every field a proposal may change, with what it may do there."""


class _Missing:
    """The value at a path that does not resolve in this spec."""


MISSING = _Missing()


@dataclass(frozen=True)
class Address:
    """A parsed path: which target pattern, and the names it was filled with."""

    pattern: str
    capability: str | None = None
    tool: str | None = None
    specialist: str | None = None
    server: str | None = None
    setting: str | None = None


def parse(path: str) -> Address | None:
    """The address `path` names, or `None` when it is not a target."""
    parts = path.split("/")
    if path in ("description", "model_profile_id", "max_steps", "capabilities"):
        return Address(pattern=path)
    if path in ("collection_ids", "context_ids"):
        return Address(pattern=path)
    if len(parts) == 2 and parts[0] == "model_settings" and parts[1] in _MODEL_SETTINGS:
        return Address(pattern=path, setting=parts[1])
    if len(parts) == 3 and parts[0] == "capabilities" and parts[2] in ("config", "approval"):
        if parts[2] == "config" and not _tunable(parts[1]):
            return None
        return Address(pattern=f"capabilities/{{capability}}/{parts[2]}", capability=parts[1])
    if len(parts) == 4 and parts[0] == "capabilities" and parts[2] == "tool_approval":
        return Address(
            pattern="capabilities/{capability}/tool_approval/{tool}",
            capability=parts[1],
            tool=parts[3],
        )
    if (
        len(parts) == 5
        and parts[:3] == ["capabilities", _SUBAGENTS, "inline"]
        and parts[4] == "description"
    ):
        return Address(
            pattern="capabilities/subagents/inline/{specialist}/description",
            capability=_SUBAGENTS,
            specialist=parts[3],
        )
    if len(parts) == 3 and parts[0] == "mcp_servers" and parts[2] == "allowed_tools":
        return Address(pattern="mcp_servers/{server}/allowed_tools", server=parts[1])
    return None


def ops(address: Address) -> tuple[FieldOp, ...]:
    """What a hunk may do at this address."""
    return dict(TARGETS)[address.pattern]


def server_key(ref: dict[str, Any]) -> str:
    """How a path names one MCP binding: its connection, or its account and catalog key."""
    if ref.get("account", "organization") == "organization":
        return str(ref["connection_id"])
    return f"{ref['account']}:{ref.get('catalog_key') or ''}"


def _binding(document: dict[str, Any], capability: str | None) -> dict[str, Any] | None:
    return next(
        (item for item in document.get("capabilities", []) if item.get("id") == capability),
        None,
    )


def _specialist(document: dict[str, Any], name: str | None) -> dict[str, Any] | None:
    binding = _binding(document, _SUBAGENTS)
    inline = [] if binding is None else (binding.get("config") or {}).get("inline", [])
    return next((item for item in inline if item.get("name") == name), None)


def _server(document: dict[str, Any], key: str | None) -> dict[str, Any] | None:
    return next((ref for ref in document.get("mcp_servers", []) if server_key(ref) == key), None)


def read(document: dict[str, Any], address: Address) -> Any:
    """The value at a `set` address in a dumped spec, or `MISSING`."""
    pattern = address.pattern
    if pattern in ("description", "model_profile_id", "max_steps"):
        return document.get(pattern)
    if address.setting is not None:
        return (document.get("model_settings") or {}).get(address.setting)
    if pattern == "mcp_servers/{server}/allowed_tools":
        server = _server(document, address.server)
        return MISSING if server is None else server.get("allowed_tools")
    if pattern == "capabilities/subagents/inline/{specialist}/description":
        specialist = _specialist(document, address.specialist)
        return MISSING if specialist is None else specialist.get("description", "")
    binding = _binding(document, address.capability)
    if binding is None:
        return MISSING
    if pattern == "capabilities/{capability}/config":
        return binding.get("config") or {}
    if pattern == "capabilities/{capability}/approval":
        return binding.get("approval", "default")
    return (binding.get("tool_approval") or {}).get(address.tool)


def _write(document: dict[str, Any], address: Address, value: Any) -> None:
    pattern = address.pattern
    if pattern in ("description", "model_profile_id", "max_steps"):
        document[pattern] = value
    elif address.setting is not None:
        document.setdefault("model_settings", {})[address.setting] = value
    elif pattern == "mcp_servers/{server}/allowed_tools":
        _server_or_fail(document, address)["allowed_tools"] = value
    elif pattern == "capabilities/subagents/inline/{specialist}/description":
        specialist = _specialist(document, address.specialist)
        assert specialist is not None, "read() resolved it before the write"
        specialist["description"] = value
    else:
        binding = _binding(document, address.capability)
        assert binding is not None, "read() resolved it before the write"
        if pattern == "capabilities/{capability}/config":
            binding["config"] = value
        elif pattern == "capabilities/{capability}/approval":
            binding["approval"] = value
        else:
            approvals = binding.setdefault("tool_approval", {})
            if value is None:
                approvals.pop(address.tool, None)
            else:
                approvals[address.tool] = value


def _server_or_fail(document: dict[str, Any], address: Address) -> dict[str, Any]:
    server = _server(document, address.server)
    assert server is not None, "read() resolved it before the write"
    return server


def _members(document: dict[str, Any], address: Address) -> list[Any]:
    return document.setdefault(address.pattern, [])


def _identity(address: Address, item: Any) -> Any:
    """What makes two items of a list the same item: a capability is its id."""
    if address.pattern == "capabilities":
        return item.get("id") if isinstance(item, dict) else item
    return str(item)


def _index(document: dict[str, Any], address: Address, item: Any) -> int | None:
    wanted = _identity(address, item)
    for index, member in enumerate(_members(document, address)):
        if _identity(address, member) == wanted:
            return index
    return None


def _validated(document: dict[str, Any]) -> AgentSpec | None:
    try:
        return AgentSpec.model_validate(document)
    except ValidationError:
        return None


def apply(spec: AgentSpec, path: str, op: str, base: Any, new: Any) -> AgentSpec | None:
    """The spec with the change made, or `None` when it no longer fits the draft."""
    address = parse(path)
    if address is None:
        return None
    document = spec.model_dump(mode="json")
    if op == FieldOp.SET.value:
        if read(document, address) != base:
            return None
        _write(document, address, new)
    elif op == FieldOp.ADD.value:
        if _index(document, address, new) is not None:
            return None
        _members(document, address).append(new)
    else:
        index = _index(document, address, base)
        if index is None or _members(document, address)[index] != base:
            return None
        del _members(document, address)[index]
    return _validated(document)


def undo(spec: AgentSpec, path: str, op: str, base: Any, accepted: Any) -> AgentSpec | None:
    """The spec with an accepted change reversed, or `None` when it was edited since."""
    address = parse(path)
    if address is None:
        return None
    document = spec.model_dump(mode="json")
    if op == FieldOp.SET.value:
        if read(document, address) != accepted:
            return None
        _write(document, address, base)
    elif op == FieldOp.ADD.value:
        index = _index(document, address, accepted)
        if index is None or _members(document, address)[index] != accepted:
            return None
        del _members(document, address)[index]
    else:
        if _index(document, address, base) is not None:
            return None
        _members(document, address).append(base)
    return _validated(document)


def writing_tools(capability: str) -> list[str]:
    """The tools a capability contributes that change something outside the run."""
    load_builtins()
    definition = REGISTRY.get(capability)
    if definition is None:
        return []
    return [tool.id for tool in definition.tools if not definition.tool_is_read_only(tool)]


def gated(binding: dict[str, Any]) -> dict[str, Any]:
    """A binding the proposal adds, with every tool that writes waiting for a person."""
    if binding.get("approval") == "required":
        return binding
    approvals = dict(binding.get("tool_approval") or {})
    for tool in writing_tools(str(binding.get("id"))):
        approvals[tool] = "required"
    return {**binding, "tool_approval": approvals} if approvals else binding


def _tightens(address: Address, document: dict[str, Any], base: Any, new: Any) -> bool:
    if new not in _STRICTNESS:
        return False
    if base is None and address.tool is not None:
        binding = _binding(document, address.capability) or {}
        base = binding.get("approval", "default")
    return base in _STRICTNESS and _STRICTNESS[new] > _STRICTNESS[base]


def standing_refusal(path: str, op: str, base: Any, new: Any) -> str | None:
    """Why a stored change may never be accepted, whatever the draft holds now.

    What staging refuses from the spec's shape alone, asked again of a row that
    may have been written before the rule, or since.
    """
    if weakens_protection(path, op, base):
        return "weakens_protection"
    if parse(path) is None or _adds_untunable_config(path, op, new):
        return "not_a_target"
    return None


def _tunable(capability: str) -> bool:
    load_builtins()
    definition = REGISTRY.get(capability)
    return definition is not None and definition.tunable


def _adds_untunable_config(path: str, op: str, value: Any) -> bool:
    """An added capability carrying a configuration the assistant may not write.

    Adding one with its default configuration is only switching it on; a
    safeguard may arrive configured, since configuring one only adds to it.
    """
    if path != "capabilities" or op != FieldOp.ADD.value or not isinstance(value, dict):
        return False
    capability = str(value.get("id"))
    definition = REGISTRY.get(capability)
    if definition is None or definition.protective or _tunable(capability):
        return False
    return capability == _SUBAGENTS or bool(value.get("config"))


def weakens_protection(path: str, op: str, base: Any) -> bool:
    """Whether a change removes a safeguard or changes its configuration."""
    load_builtins()
    parts = path.split("/")
    if path == "capabilities" and op == FieldOp.REMOVE.value:
        capability = base.get("id") if isinstance(base, dict) else None
    elif len(parts) == 3 and parts[0] == "capabilities" and parts[2] == "config":
        capability = parts[1]
    else:
        return False
    definition = REGISTRY.get(str(capability))
    return definition is not None and definition.protective


def stage(spec: AgentSpec, path: str, op: str, value: Any) -> tuple[Any, Any] | str:
    """The `(base, new)` a proposed change is stored with, or why it may not be staged.

    `set` keeps the draft's value as `base`; `remove` keeps the whole item it
    takes out, so Undo can put it back; an added capability arrives gated, in the
    form the spec stores it. Refused is everything that can be told from the spec
    alone: a path that is not a target, an operation it does not allow, approval
    that does not tighten, a safeguard removed or reconfigured, a capability that
    does not exist, a configuration that does not validate, a change that does
    not apply. Whether the person may grant
    what it adds is the registry's question, asked separately.
    """
    load_builtins()
    if weakens_protection(path, op, value):
        return "weakens_protection"
    address = parse(path)
    if address is None:
        return "not_a_target"
    if op not in {allowed.value for allowed in ops(address)}:
        return "operation"
    if _adds_untunable_config(path, op, value):
        return "not_a_target"
    document = spec.model_dump(mode="json")
    adds_capability = address.pattern == "capabilities" and op == FieldOp.ADD.value
    if adds_capability and (not isinstance(value, dict) or str(value.get("id")) not in REGISTRY):
        return "unknown_capability"
    if op == FieldOp.SET.value:
        current = read(document, address)
        if current is MISSING:
            return "does_not_apply"
        base, new = current, value
    elif adds_capability:
        base, new = None, _binding_as_stored(value)
        if isinstance(new, str):
            return "invalid_config"
    elif op == FieldOp.ADD.value:
        base, new = None, _plain(value)
    else:
        index = _index(document, address, value)
        if index is None:
            return "does_not_apply"
        base, new = _members(document, address)[index], None
    approval = address.pattern.endswith(("approval", "{tool}"))
    if approval and not _tightens(address, document, base, new):
        return "loosens_approval"
    if _config_refused(address, new, adds_capability=adds_capability):
        return "invalid_config"
    if apply(spec, path, op, base, new) is None:
        return "does_not_apply"
    return base, new


def _binding_as_stored(value: dict[str, Any]) -> dict[str, Any] | str:
    """The binding gated and as the spec stores it, so Undo finds the very binding it added."""
    try:
        return CapabilityBindingSpec.model_validate(gated(value)).model_dump(mode="json")
    except ValidationError:
        return "invalid"


def _config_refused(address: Address, new: Any, *, adds_capability: bool) -> bool:
    if adds_capability:
        definition, raw = REGISTRY[new["id"]], new.get("config")
    elif address.pattern == "capabilities/{capability}/config":
        definition, raw = REGISTRY[str(address.capability)], new
    else:
        return False
    try:
        definition.validate_config(raw if isinstance(raw, dict) else {})
    except AppException:
        return True
    return False


def _plain(value: Any) -> Any:
    return str(value) if isinstance(value, UUID) else value
