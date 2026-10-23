"""`email.send`: send an email from the deployment's own address.

`notification.send` reaches members, through their preferences. This step is for
everybody else - the lead who filled in a form, the customer whose order
shipped: up to ten addresses, each sent its own copy, so no recipient sees
another's address. It goes through the deployment's email provider and sender,
like every mail the platform sends, with the workflow's subject and text in a
plain template. A reply goes to `reply_to` when the step sets one.

`Completed` means the provider accepted every copy. A provider that only logs
mail - the development default - accepts it too, and `delivered` says so rather
than letting a run claim it reached anyone. A copy the provider refuses fails the
step with the addresses already sent named, since a retry sends to all of them
again: mail has no idempotency key, so the step is at least once.
"""

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.db.session import get_worker_db_context
from app.services.deployment_settings import DeploymentSettingsService
from app.services.email.service import EmailKey, get_email_service
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError

MAX_RECIPIENTS = 10


class EmailSendConfig(BaseModel):
    """Where replies go."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reply_to: EmailStr | None = Field(
        default=None,
        title="Reply to",
        description="Where a reply goes. The deployment's own reply address when empty.",
    )


class EmailSendInput(BaseModel):
    """Who it goes to, and what it says - typed in or bound from earlier steps."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    to: list[EmailStr] = Field(
        min_length=1,
        max_length=MAX_RECIPIENTS,
        description="Up to ten addresses. Each gets its own copy.",
    )
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=50_000, description="Plain text.")


class EmailSendOutput(BaseModel):
    """Who the provider accepted the mail for, and whether it actually leaves."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sent_to: tuple[str, ...]
    delivered: bool = Field(description="False when the deployment's email provider only logs mail")


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Send one copy to each address, stopping at the first the provider refuses."""
    if not isinstance(node_input, EmailSendInput):
        return Failed(
            error=WorkflowError(
                code="EMAIL_NOT_CONFIGURED", message="This step needs addresses, a subject and text"
            )
        )
    reply_to = config.reply_to if isinstance(config, EmailSendConfig) else None
    async with get_worker_db_context() as db:
        app_name = await DeploymentSettingsService(db).effective_app_name()
    service = get_email_service()
    sent: list[str] = []
    for address in dict.fromkeys(node_input.to):
        result = await service.send(
            key=EmailKey.WORKFLOW_MESSAGE,
            to=address,
            context={"subject": node_input.subject, "body": node_input.body, "app_name": app_name},
            reply_to=reply_to,
        )
        if not result.accepted:
            return Failed(
                error=WorkflowError(
                    code="EMAIL_NOT_SENT",
                    message="The email provider refused a message",
                    details={"refused": address, "sent_to": sent},
                )
            )
        sent.append(address)
    return Completed[EmailSendOutput](
        output=EmailSendOutput(sent_to=tuple(sent), delivered=service.delivers)
    )
