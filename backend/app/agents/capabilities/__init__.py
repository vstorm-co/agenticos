"""Capabilities - the units an agent is assembled from.

A capability is what gets plugged into an agent: knowledge search, web research,
a budget guard, a set of skills. It is the right unit to switch on and off,
because that is the decision people actually make - "knowledge search" is one
switch, not one per tool it exposes. And unlike a tool, a capability covers
things that are not tools at all - enforcement, compaction, guardrails - so one
concept covers the whole assembly instead of two that overlap awkwardly.

Two decisions are *not* per capability, and both are keyed on a tool's stable
id. Approval: a capability declares its tools so an agent can be allowed to read
files without being allowed to write them (see `approval/README.md`).
Presentation: a binding may rename a tool and reword its description, because
that description is the prompt the model reads before deciding to act.

Each capability lives in its own folder with a `_capability.py`, an optional
`_toolset.py` and a README explaining the decisions behind it.
"""

from app.agents.capabilities._overrides import ToolOverrides
from app.agents.capabilities._registry import (
    REGISTRY,
    TOOL_NAME_PATTERN,
    CapabilityBinding,
    CapabilityBuildContext,
    CapabilityDef,
    CapabilityToolInfo,
    ProviderExecuted,
    ToolOverride,
    all_capabilities,
    build,
    get,
    load_builtins,
    register,
)

__all__ = [
    "REGISTRY",
    "TOOL_NAME_PATTERN",
    "CapabilityBinding",
    "CapabilityBuildContext",
    "CapabilityDef",
    "CapabilityToolInfo",
    "ProviderExecuted",
    "ToolOverride",
    "ToolOverrides",
    "all_capabilities",
    "build",
    "get",
    "load_builtins",
    "register",
]
