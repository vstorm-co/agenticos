"""Scenario-based end-to-end proof: record what was observed, report what it proves (#8).

The agent records a reproduction scenario for a change and the attempts made
at it - before the fix and after it - and asks for the coverage verdict over
the diff. The capability never runs a command, never edits, commits, or
comments, and never merges: it records what the agent hands it and reports
what that evidence proves. A change with no observed proof says so.
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.proof_scenario._toolset import (
    build_proof_scenario_toolset,
)
from app.agents.manifest import RunRecorder

#: The run's recorder, so proof scenarios land on the manifest beside the
#: requests. Read here rather than resolved here: the runner holds the
#: recorder, and a capability must never fetch run state itself.
PROOF_SCENARIO_RECORDER_RESOURCE = "proof_scenario_recorder"

_INSTRUCTIONS = (
    "Prove a change with observed evidence, using the proof_scenario tools. "
    "Before fixing anything, record a reproduction scenario for the failure "
    "with proof_scenario_record - a command, a reproduction, or a UI flow - "
    "and the before-fix attempt that shows it failing. Apply the fix, then "
    "run the same reproduction again and record the after-fix attempt with "
    "what you actually saw. A scenario is proven only when the same "
    "reproduction failed before the fix and passed after it. A green unit "
    "test is not proof: record it as evidence kind unit_test and it will "
    "never count. When you cannot find a way to prove a change, say so and "
    "ask the user - never claim proof you do not have. Before asking for a "
    "merge, call proof_scenario_verdict with the changed files: it reports "
    "which files have observed proof and which do not, and whether the "
    "merge gate's proof half holds. Never merge, comment, or take any other "
    "action on the change yourself - proof and reporting only."
)


@dataclass
class ProofScenarioCapability(AbstractCapability[AgentDepsT]):
    """Records proof scenarios and reports the coverage verdict."""

    recorder: RunRecorder = field(default_factory=RunRecorder)

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        """The proof-scenario tools, built once."""
        if self._toolset is None:
            self._toolset = build_proof_scenario_toolset(self.recorder)
        return self._toolset

    def get_instructions(self) -> str:
        """How proof works, in the agent's instructions."""
        return _INSTRUCTIONS
