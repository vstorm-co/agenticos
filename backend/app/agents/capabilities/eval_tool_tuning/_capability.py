"""Eval-driven tool tuning (#11): score a tool against judged eval cases.

The tuning layer on top of the failure-learning loop (#32). The agent
hands the tool one tool and the judged results of a set of eval cases -
the cases #32's `agent_eval_cases` holds, each already judged by its
`judge()` - and the tool scores the tool, drafts one tuning proposal per
failure class, and records the run on the manifest. The proposals are
drafts: a human applies them, through #32 for instructions or #9 for
skills. Nothing here applies a change, runs an eval, or judges an answer.
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.eval_tool_tuning._toolset import (
    build_eval_tool_tuning_toolset,
)
from app.agents.manifest import RunRecorder

#: The run's recorder, so tuning runs land on the manifest beside the requests.
EVAL_TOOL_TUNING_RECORDER_RESOURCE = "eval_tool_tuning_recorder"

_INSTRUCTIONS = (
    "Eval-driven tool tuning scores one tool against eval cases that are "
    "already judged, and drafts tuning proposals from the failures. Call "
    "record_eval_tool_tuning with the tool and the judged cases - each case "
    "with what its answer was supposed to say, whether the judge said it "
    "passed, what the answer said, and every tool call the case's run made. "
    "The call scores the tool, classifies each failure, drafts one proposal "
    "per failure class, and records the run on the manifest. The proposals "
    "are drafts with their failing cases as evidence: show them to the "
    "person and let them decide. Never apply a proposal yourself, never "
    "judge an answer yourself - the verdicts arrive already judged - and "
    "never present a draft proposal as a fix that has been made."
)


@dataclass
class EvalToolTuning(AbstractCapability[AgentDepsT]):
    """Scores a tool against judged eval cases and records the tuning run.

    The run still builds with no recorder in its resources - the drift check
    builds it that way - so a missing recorder means the tool records onto a
    fresh one rather than failing the run.
    """

    max_tuning_runs: int = 3
    recorder: RunRecorder = field(default_factory=RunRecorder)

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        """The tuning run's one tool, built once."""
        if self._toolset is None:
            self._toolset = build_eval_tool_tuning_toolset(self.recorder, self.max_tuning_runs)
        return self._toolset

    def get_instructions(self) -> str:
        """How eval-driven tool tuning works, in the agent's instructions."""
        return _INSTRUCTIONS
