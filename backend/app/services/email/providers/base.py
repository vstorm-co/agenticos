"""Base types for email providers."""

from typing import Protocol

from pydantic import BaseModel


class EmailMessage(BaseModel):
    to: list[str]
    cc: list[str] = []
    bcc: list[str] = []
    from_email: str
    from_name: str | None = None
    subject: str
    html: str
    text: str
    reply_to: str | None = None
    tags: list[str] = []
    metadata: dict = {}


class SendResult(BaseModel):
    provider_message_id: str
    accepted: bool
    error: str | None = None


class EmailProvider(Protocol):
    delivers: bool
    """Whether a message this provider accepts actually leaves the deployment.

    `accepted` on its own cannot answer that. `LogProvider` writes the message to
    stdout and answers `accepted=True`, which is right - it did what it does - so a
    caller reading only that told the inviter their invitation had been emailed by
    a deployment that emails nothing. This is the other half of the question, and
    it belongs to the provider because nothing else knows (#1479).
    """

    async def send(self, message: EmailMessage) -> SendResult: ...
