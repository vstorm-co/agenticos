"""`trigger.outlook`: a workflow a message arriving in the organization's Outlook starts.

The mailbox is the one the organization connected through the Outlook portal, read
once a minute by the same poll that fires agent triggers - one folder at a time,
so the folder this node names is where the poll looks. Each new message that fits
this node's filter starts one run, as the member who published it.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._mail import stage_attachments
from app.workflows.nodes._triggers import EmailTriggerOutput, run_input_as


class OutlookTriggerConfig(BaseModel):
    """Which folder is read, and which of its messages start the workflow.

    The same filter an agent's Outlook trigger applies, read by the same matcher:
    every key here is one that trigger accepts. A sender filter also needs the
    message to pass the authenticated-sender check (DMARC, a DKIM signature from the
    sender's domain, or mail from inside the tenant).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    folder: str = Field(
        default="inbox",
        min_length=1,
        max_length=255,
        title="Folder",
        description=(
            "A well-known folder (inbox, archive, junkemail) or the display name of a "
            "top-level folder, which is where a mail rule files the mail to read"
        ),
    )
    mailbox: str | None = Field(
        default=None,
        max_length=254,
        pattern=r"^[^@\s/]+@[^@\s/]+$",
        title="Shared mailbox",
        description=(
            "A shared mailbox the connected account can read; empty for its own. "
            "Naming one takes the permission to manage connections"
        ),
    )
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
        description=(
            "Matched against the sender's address only, never the display name, ignoring "
            "case: @acme.com is that domain exactly (not its subdomains), a full address "
            "is that address, other text is part of the address. Needs mail the sender "
            "domain authenticated"
        ),
    )
    has_attachments: bool | None = Field(
        default=None,
        title="Has attachments",
        description="Only mail with (or without) attachments",
    )
    importance: Literal["low", "normal", "high"] | None = Field(
        default=None, title="Importance", description="The importance the sender set"
    )
    category: str | None = Field(
        default=None,
        max_length=255,
        title="Category",
        description="One of the message's Outlook categories, ignoring case",
    )


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Hand on the message the run was started with, its attachments stored as files.

    Only a run the mailbox admitted reads the mailbox; any other run hands the
    attachments on unfetched. A repeat only reads mail and stores copies, so the
    step is idempotent - but an attempt that was interrupted leaves its copies with
    the run until run retention removes them.
    """
    message = run_input_as(EmailTriggerOutput)
    if isinstance(message, Failed):
        return message
    staged = await stage_attachments(message, portal_key="microsoft", admitted_by="outlook")
    if isinstance(staged, Failed):
        return staged
    return Completed[EmailTriggerOutput](output=staged)
