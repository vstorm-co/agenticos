"""`trigger.chat` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition, Port
from app.workflows.nodes._triggers import ChatTriggerOutput
from app.workflows.nodes.trigger_chat._handler import handle
from app.workflows.triggers import CHAT

register(
    NodeDefinition(
        id=CHAT,
        version=1,
        name="Chat message",
        category=TRIGGER_CATEGORY,
        description="A member sends a message in the chat, with this workflow picked to answer.",
        kind="action",
        config_schema=None,
        input_schema=None,
        output_schema=ChatTriggerOutput,
        ports=(Port(id="out", label="Out", kind="output", schema=ChatTriggerOutput),),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
