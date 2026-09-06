"""What the model is actually told about each tool.

The catalog declares a tool's id and a one-line description, which is what the
Builder needs to offer approval and to name it. It is not what the *model*
reads. A model reads the whole docstring - for `create_chart` that is nine
hundred characters explaining scatter series and telling it not to narrate the
returned JSON - plus a JSON Schema of the arguments. An author deciding whether
to reword a tool for their agent is deciding about that text, and until now the
Builder showed them the first sentence of it.

None of it is restated here. It is read off the built toolset, the same way
`tests/test_capability_registry.py` reads it to prove the declarations are
honest: the code is the source of truth, and a second copy in a decorator is a
copy that goes stale on the first edit nobody mirrors.

Building a capability to read its documentation needs the resources a real run
would resolve from the database. The stub below stands in for them. It is
deliberately minimal - enough that a capability which only builds when it has
something to work with does build, and nothing more, because what is read back
is the shape of the tools and never a result.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage

from app.agents.capabilities import all_capabilities
from app.agents.capabilities._registry import (
    CapabilityBinding,
    CapabilityBuildContext,
    get,
)
from app.agents.capabilities.channel_tools import CHANNEL_DIRECTORY_RESOURCE
from app.agents.deps import AgentDeps
from app.agents.subagent_runtime import (
    SUBAGENT_RUNTIME_RESOURCE,
    DynamicSpecialists,
    ResolvedSubagent,
    SubagentRuntime,
)
from app.core.secret_kinds import ApiKeySecret, SecretKind

logger = logging.getLogger(__name__)

# Enough for a builder that refuses to build with nothing to work with. The
# names are never shown and never searched; only the tools' own shape is read.
_DOCUMENTATION_STUB: dict[str, Any] = {
    "kb_collection_names": ["documentation-probe"],
    # A `link`-mode file, because that is the arrangement that offers tools at
    # all: `context` contributes nothing without files, so without this the
    # Builder falls back to the catalog's one-liner for `list_context` and
    # `read_context` - the two tools whose text somebody wrote and nobody sees.
    "context_files": [
        SimpleNamespace(
            name="documentation_probe",
            description="Stands in for a context file so the context toolset builds.",
            content="",
            mode="link",
            format="markdown",
        )
    ],
    "skills": [
        SimpleNamespace(
            name="documentation_probe",
            description="Stands in for a skill so the skills toolset builds.",
            content="",
            resources=[],
        )
    ],
    # A channel directory and a delegate, so the two capabilities that offer tools
    # only when a run has something to reach do build. Neither is called: what is
    # read back is the shape of the tools, never a result - the directory answers
    # nothing and the delegate is never delegated to.
    CHANNEL_DIRECTORY_RESOURCE: SimpleNamespace(),
    SUBAGENT_RUNTIME_RESOURCE: SubagentRuntime(
        subagents=(
            ResolvedSubagent(
                name="documentation_probe",
                description="Stands in for a delegate so the delegation toolset builds.",
                build=lambda: PydanticAgent(TestModel()),
            ),
        ),
        record=None,
        depth_remaining=1,
        # The widest configuration, because `subagents` is the one capability whose
        # tool list is not fixed: `create_agent` and `delegate` are offered only to
        # an agent whose author asked for them, and a tool nobody can describe is
        # exactly the one somebody reaching for this page needs described.
        dynamic=DynamicSpecialists(
            build=lambda **_: PydanticAgent(TestModel()),
            allowed_models=(),
        ),
    ),
}


# A capability whose *tools* are configuration builds nothing from an empty blob,
# so the widest setting is the one worth documenting: a tool nobody can describe
# is exactly the one somebody reaching for this page needs described.
_DOCUMENTATION_CONFIGS: dict[str, dict[str, Any]] = {
    "channel_tools": {"tools": sorted(get("channel_tools").tool_ids)},
}


def _documentation_secret(definition: Any) -> ApiKeySecret | None:
    """A stand-in credential for a capability that will not build without one.

    Read for its *shape* and never used: nothing here calls the service, so the
    value only has to satisfy the builder that a key exists. Without it a
    capability whose key is unconditional builds as `None`, has no toolset, and
    falls back to the catalog's one-line summary - which is how `memory_mem0`
    showed the Builder a sentence while the model was reading six (#1473).

    Only `API_KEY`, because it is the only kind any capability requires
    unconditionally; another kind arriving that way should show up as a missing
    contract rather than be quietly stubbed with the wrong shape.
    """
    requirement = definition.secret
    if requirement is None or not definition.needs_secret(definition.validate_config({})):
        return None
    if requirement.kind is not SecretKind.API_KEY:
        return None
    return ApiKeySecret(api_key="documentation-probe")


def _probe_context() -> RunContext[AgentDeps]:
    """A run context that reaches nothing.

    `get_tools` takes one because a capability may vary its list by the run - and
    none of them varies it by anything this carries. Deps are empty, so a
    capability reading them for a tenant or an audience sees the same "nothing" a
    run outside a conversation would.
    """
    return RunContext(deps=AgentDeps(), model=TestModel(), usage=RunUsage(), retry=0, max_retries=1)


@dataclass(frozen=True, slots=True)
class ToolContract:
    """A tool exactly as the model meets it."""

    description: str
    """The whole docstring, not the summary line the catalog carries."""

    parameters: dict[str, Any]
    """JSON Schema of the arguments, as the model is given them."""


async def tool_contracts() -> dict[str, dict[str, ToolContract]]:
    """Every capability's tools, keyed by capability id then tool id.

    Cached for the process: capabilities are registered at import and the answer
    changes on redeploy, not between requests. A capability that fails to build is
    logged and skipped rather than failing the catalog - the Builder can still
    offer it, with one fewer thing to read.

    Async because the tools have to be *asked for* rather than read off the
    toolset: a capability that filters or wraps its tools - `subagents` offers
    `create_agent` only where the binding allows it - answers `get_tools`, and
    reading the `tools` attribute reaches only a plain `FunctionToolset`. Doing
    that raised for the one capability whose tool list is not fixed, which the
    catalog swallowed into an empty contract set and the Builder rendered as a
    one-liner (#1473).
    """
    global _CACHED
    if _CACHED is not None:
        return _CACHED
    contracts: dict[str, dict[str, ToolContract]] = {}
    for definition in all_capabilities():
        try:
            contracts[definition.id] = await _contracts_for(definition)
        except Exception:
            logger.exception("Could not read the tool contracts for capability %s", definition.id)
            contracts[definition.id] = {}
    _CACHED = contracts
    return contracts


_CACHED: dict[str, dict[str, ToolContract]] | None = None


async def _contracts_for(definition: Any) -> dict[str, ToolContract]:
    blob = _DOCUMENTATION_CONFIGS.get(definition.id, {})
    built = definition.builder(
        CapabilityBuildContext(
            binding=CapabilityBinding(capability_id=definition.id, config=blob),
            config=definition.validate_config(blob),
            resources=_DOCUMENTATION_STUB,
            secret=_documentation_secret(definition),
        )
    )
    toolset = built.get_toolset() if built is not None else None
    if toolset is None:
        return {}

    # Asked for, not read off: `get_tools` is what a run calls, so this is the
    # list after any filtering or wrapping the capability does - which is the
    # list the model is actually sent.
    contracts: dict[str, ToolContract] = {}
    for tool_id, tool in (await toolset.get_tools(_probe_context())).items():
        definition_for_model = getattr(tool, "tool_def", tool)
        contracts[tool_id] = ToolContract(
            description=getattr(definition_for_model, "description", "") or "",
            parameters=getattr(definition_for_model, "parameters_json_schema", None) or {},
        )
    return contracts
