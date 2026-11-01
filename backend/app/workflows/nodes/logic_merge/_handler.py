"""`logic.merge`: join branches back into one path.

By default the merge waits for **the branch that ran**: publishing refuses a merge
whose inputs do not leave one step that takes a single way out through different
ports, and neither branch dominates the merge, so rule 4 lets it bind to neither.
The dispatcher therefore hands it the output of the branch that did run
(`DispatchContext.arrived_output`), and the merge passes that on under `value`. What
reaches `value` differs by branch, so a node downstream reads fields of it by path
and is checked when it is dispatched.

With `wait_for="all"` it waits for **every branch**: its inputs run side by side, so it
runs once all have settled and hands each one's output on by name under `branches`
(`DispatchContext.arrived_branches`). A branch that did not run, in a group of
branches where another took its place, is `None`. The names are `branch_keys`.
"""

import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import BadRequestError
from app.services.workflow_execution import context
from app.workflows import _registry
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.graph.model import NodeInstance, WorkflowGraph

_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"
_MAX_KEY = 32
SPLIT = "logic.split"


class MergeBranchKey(BaseModel):
    """The name one incoming branch goes by in `branches`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_node_id: UUID = Field(description="The step the branch leaves")
    source_port: str = Field(description="The port it leaves by")
    key: str = Field(pattern=_KEY_PATTERN, description="The branch's name in `branches`")


class LogicMergeConfig(BaseModel):
    """How the merge waits, and what each branch is called when it waits for all."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    wait_for: Literal["one", "all"] = Field(
        default="one",
        description="`one`: the branch that ran, passed on as `value`. `all`: every branch, "
        "passed on by name as `branches`",
    )
    branch_keys: tuple[MergeBranchKey, ...] = Field(
        default=(),
        description="A name for each incoming branch. A branch with none is called after "
        "the step it leaves, or after the Split's branch",
    )


class LogicMergeOutput(BaseModel):
    """What reached the merge: the branch that ran, or every branch by name."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: dict[str, Any] | None = None
    branches: dict[str, dict[str, Any] | None] | None = None


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    if slug[:1].isdigit():
        slug = f"b_{slug}"
    return slug[:_MAX_KEY]


def branch_keys(graph: WorkflowGraph, merge: NodeInstance) -> dict[tuple[UUID, str], str]:
    """The name of each branch reaching `merge`, by (source step, source port).

    The stored key where the config has one, else the Split's branch name when the
    wire leaves a Split, else a slug of the source step's name.
    """
    configured = merge.config.get("branch_keys")
    stored = {
        (str(item.get("source_node_id")), item.get("source_port")): item.get("key")
        for item in (configured if isinstance(configured, list) else [])
        if isinstance(item, dict)
    }
    by_id = graph.node_by_id
    keys: dict[tuple[UUID, str], str] = {}
    for edge in graph.edges:
        if edge.target_node_id != merge.id or edge.source_node_id not in by_id:
            continue
        wire = (edge.source_node_id, edge.source_port)
        if wire in keys:
            continue
        source = by_id[edge.source_node_id]
        key = stored.get((str(source.id), edge.source_port))
        if not isinstance(key, str):
            key = edge.source_port if source.definition_id == SPLIT else _slug(_name(source))
        keys[wire] = key
    return keys


def _name(node: NodeInstance) -> str:
    if node.label:
        return node.label
    try:
        return _registry.get(node.definition_id, node.definition_version).name
    except BadRequestError:
        return node.definition_id


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Pass on the branch that ran, or every branch by name."""
    current = context.current()
    if isinstance(config, LogicMergeConfig) and config.wait_for == "all":
        return Completed[LogicMergeOutput](
            output=LogicMergeOutput(branches=current.arrived_branches)
        )
    return Completed[LogicMergeOutput](output=LogicMergeOutput(value=current.arrived_output))
