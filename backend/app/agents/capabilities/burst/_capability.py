"""One task, split into parallel subtasks, merged into one outcome.

The builder needs nothing resolved: the workers are ambient one-shot agents
on the run's own model, so there is no per-part model to resolve and nothing
to substitute. The recorder is what the tool writes the burst onto, beside
the run's requests.
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.burst._toolset import build_burst_toolset
from app.agents.manifest import RunRecorder

#: The run's recorder, so bursts land on the manifest beside the requests.
BURST_RECORDER_RESOURCE = "burst_recorder"

_INSTRUCTIONS = (
    "Burst mode splits one task into independent subtasks and runs them in "
    "parallel. Before calling run_burst, split the task into parts that do "
    "not depend on each other and show the split to the person, so they can "
    "correct it. Then call run_burst with the task and the parts: the call "
    "runs them side by side and returns the merged outcome. A part that "
    "fails is reported as failed with its reason - retry it, do it "
    "directly, or narrow the task; never present the merge as complete "
    "while a part is failed. Do not burst a task that is really one "
    "sequential job, and do not let repeated bursts widen the scope - fix "
    "what failed, nothing more."
)


@dataclass
class Burst(AbstractCapability[AgentDepsT]):
    """Runs bursts over the task the agent hands it.

    The run still builds with no recorder in its resources - the drift check
    builds it that way - so a missing recorder means the tool records onto a
    fresh one rather than failing the run.
    """

    max_subtasks: int = 3
    max_bursts: int = 3
    recorder: RunRecorder = field(default_factory=RunRecorder)

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        """The burst's one tool, built once."""
        if self._toolset is None:
            self._toolset = build_burst_toolset(self.recorder, self.max_subtasks, self.max_bursts)
        return self._toolset

    def get_instructions(self) -> str:
        """How burst mode works, in the agent's instructions."""
        return _INSTRUCTIONS
