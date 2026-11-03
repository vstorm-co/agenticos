"""Await a verified reply in one selected mailbox thread."""

from app.schemas.reply_expectation import ReplyExpectationOutput
from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.flow_await_reply._handler import (
    AwaitReplyConfig,
    AwaitReplyInput,
    handle,
    resource_check,
    routes,
)

register(
    NodeDefinition(
        id="flow.await_reply",
        version=1,
        name="Await email reply",
        category="control",
        kind="control",
        description="Wait for an authenticated reply from one sender in one mail thread, or its deadline.",
        config_schema=AwaitReplyConfig,
        input_schema=AwaitReplyInput,
        output_schema=ReplyExpectationOutput,
        ports=(
            Port(id="in", label="In", kind="input"),
            Port(id="reply", label="Reply received", kind="output", schema=ReplyExpectationOutput),
            Port(
                id="deadline",
                label="Deadline reached",
                kind="output",
                schema=ReplyExpectationOutput,
            ),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        routes=routes,
        resource_check=resource_check,
        exclusive_branches=True,
    )
)
