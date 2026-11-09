"""Recovery instructions shared by agents, separately from error classification."""

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT

_INSTRUCTIONS = """\
When a tool returns a structured error, use its code, execution disposition, issues and recovery:
- invalid_arguments: correct the specified field using its expected_type and example before calling again.
  Do not repeat the same invalid arguments.
- tool_unavailable: rediscover tools available in this context. Follow a supported invocation route only
  when the runtime or discovery result explicitly establishes it. A discovery result does not by itself
  make a tool directly callable. Do not infer missing user permission from a tool-registration error.
- permission_denied: stop the refused operation and explain the stated refusal. Do not try to bypass it.
- transient_failure: retry only when the execution outcome is known and another attempt is safe.
- execution_unknown, or execution=unknown: check execution status before retrying an action. Use an
  available status tool; if status cannot be established, explain the uncertainty and stop automatic retries.
  execution=started also requires checking an existing action before submitting it again.
  For a run_code error with code=invalid_arguments and cause_execution=not_started, correct the
  named child's arguments: that child never started. If the outer execution is unknown, inspect
  earlier actions before replaying the script.
Keep recovery relevant to the user's task. A workflow lookup failure does not justify filesystem searches.
When explaining a failure, preserve its actionable detail and error ID so an operator can find its log entry.
"""


class ToolRecovery(AbstractCapability[AgentDepsT]):
    """Put the runtime's recovery rules in every agent's model instructions."""

    def get_instructions(self) -> str:
        return _INSTRUCTIONS
