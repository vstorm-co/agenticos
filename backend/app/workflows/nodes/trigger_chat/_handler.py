"""`trigger.chat`: a workflow the chat can answer with.

A member picks the workflow in the chat's "who answers" list and sends a
message; the run starts here with the message as `prompt`, and its `core.output`
text is written back into that conversation. Only a workflow whose live version
starts from this trigger is offered in the chat.
"""

from pydantic import BaseModel

from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._triggers import ChatTriggerOutput, run_input_as


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Hand on the message the run was started with."""
    message = run_input_as(ChatTriggerOutput)
    if isinstance(message, Failed):
        return message
    return Completed[ChatTriggerOutput](output=message)
