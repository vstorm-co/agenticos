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
from functools import cache
from types import SimpleNamespace
from typing import Any

from app.agents.capabilities import all_capabilities
from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext

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
}


@dataclass(frozen=True, slots=True)
class ToolContract:
    """A tool exactly as the model meets it."""

    description: str
    """The whole docstring, not the summary line the catalog carries."""

    parameters: dict[str, Any]
    """JSON Schema of the arguments, as the model is given them."""


@cache
def tool_contracts() -> dict[str, dict[str, ToolContract]]:
    """Every capability's tools, keyed by capability id then tool id.

    Cached for the process: capabilities are registered at import and the
    answer changes on redeploy, not between requests. A capability that fails
    to build is logged and skipped rather than failing the catalog - the
    Builder can still offer it, with one fewer thing to read.
    """
    contracts: dict[str, dict[str, ToolContract]] = {}
    for definition in all_capabilities():
        try:
            contracts[definition.id] = _contracts_for(definition)
        except Exception:
            logger.exception("Could not read the tool contracts for capability %s", definition.id)
            contracts[definition.id] = {}
    return contracts


def _contracts_for(definition: Any) -> dict[str, ToolContract]:
    built = definition.builder(
        CapabilityBuildContext(
            binding=CapabilityBinding(capability_id=definition.id),
            config=None,
            resources=_DOCUMENTATION_STUB,
        )
    )
    toolset = built.get_toolset() if built is not None else None
    if toolset is None:
        return {}

    contracts: dict[str, ToolContract] = {}
    for tool_id, tool in toolset.tools.items():
        # Unwrapped rather than assumed: what a toolset holds is a tool object
        # whose `tool_def` is the thing handed to the model. Reading the wrapper
        # would give a description that no model has ever seen.
        definition_for_model = getattr(tool, "tool_def", tool)
        contracts[tool_id] = ToolContract(
            description=getattr(definition_for_model, "description", "") or "",
            parameters=getattr(definition_for_model, "parameters_json_schema", None) or {},
        )
    return contracts
