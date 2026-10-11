"""`trigger.gmail`: a workflow a message arriving in the organization's Gmail starts.

The mailbox is the one the organization connected through the Gmail portal, read
once a minute by the same poll that fires agent triggers. Each new message that
fits this node's filter starts one run, as the member who published it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._triggers import EmailTriggerOutput, run_input_as


class GmailTriggerConfig(BaseModel):
    """Which messages start the workflow; every new one when nothing is set.

    The same filter an agent's Gmail trigger applies, read by the same matcher.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_contains: str | None = Field(
        default=None,
        max_length=255,
        title="Subject contains",
        description="A word or phrase in the subject, ignoring case",
    )
    sender_contains: str | None = Field(
        default=None,
        max_length=255,
        title="Sender contains",
        description="Part of the sender's name or address, such as @acme.com",
    )
    label: str | None = Field(
        default=None,
        max_length=128,
        title="Label",
        description="One of the mailbox's labels, exactly, such as INBOX or IMPORTANT",
    )


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Hand on the message the run was started with."""
    message = run_input_as(EmailTriggerOutput)
    if isinstance(message, Failed):
        return message
    return Completed[EmailTriggerOutput](output=message)
