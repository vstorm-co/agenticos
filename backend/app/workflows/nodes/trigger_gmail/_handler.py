"""`trigger.gmail`: a workflow a message arriving in the organization's Gmail starts.

The mailbox is the one the organization connected through the Gmail portal, read at the
mailbox's own interval (a minute unless an administrator set another) by the same poll
that fires agent triggers. Each new message that fits this node's filter starts one run,
as the member who published it. Sent mail, drafts, spam and the bin are not arrivals and
start nothing, unless the label filter names one of them.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._mail import stage_attachments
from app.workflows.nodes._triggers import EmailTriggerOutput, run_input_as


class GmailTriggerConfig(BaseModel):
    """Which messages start the workflow; every new one when nothing is set.

    The same filter an agent's Gmail trigger applies, read by the same matcher. A
    sender filter also needs the message to pass the authenticated-sender check
    (DMARC, or a DKIM signature from the sender's domain).
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
        description=(
            "Matched against the sender's address only, never the display name, ignoring "
            "case: @acme.com is that domain exactly (not its subdomains), a full address "
            "is that address, other text is part of the address. Needs mail the sender "
            "domain authenticated"
        ),
    )
    label: str | None = Field(
        default=None,
        max_length=128,
        title="Label",
        description=(
            "One of the mailbox's labels, exactly, such as INBOX or IMPORTANT. Mail "
            "labelled SENT, DRAFT, SPAM or TRASH is skipped unless this names that label"
        ),
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
    staged = await stage_attachments(message, portal_key="google", admitted_by="gmail")
    if isinstance(staged, Failed):
        return staged
    return Completed[EmailTriggerOutput](output=staged)
