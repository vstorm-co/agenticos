"""`trigger.schedule`: a workflow that runs on a clock.

Its cadence and the input every run starts with are this node's configuration;
publishing a version is what schedules it, and the schedule heartbeat fires it.
A tick that finds the last run still going is skipped rather than stacked.
"""

from pydantic import BaseModel

from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._triggers import ScheduleTriggerOutput, run_input_as


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Hand on the tick the run was started by."""
    tick = run_input_as(ScheduleTriggerOutput)
    if isinstance(tick, Failed):
        return tick
    return Completed[ScheduleTriggerOutput](output=tick)
