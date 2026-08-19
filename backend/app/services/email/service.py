from __future__ import annotations

import enum
import logging
from typing import Any

from app.core.config import settings
from app.services.email import get_email_provider
from app.services.email.providers.base import EmailMessage, EmailProvider, SendResult
from app.services.email.templates import render_email

logger = logging.getLogger(__name__)


class EmailKey(enum.StrEnum):
    WELCOME = "welcome"
    EMAIL_VERIFICATION = "email_verification"
    MAGIC_LINK = "magic_link"
    PASSWORD_RESET = "password_reset"
    INVITATION = "invitation"
    NEWSLETTER_WELCOME = "newsletter_welcome"
    BUDGET_EXCEEDED = "budget_exceeded"
    APPROVAL_REQUESTED = "approval_requested"
    USAGE_REPORT = "usage_report"


class EmailCategory(enum.StrEnum):
    TRANSACTIONAL = "transactional"
    LIFECYCLE = "lifecycle"
    MARKETING = "marketing"


_CATEGORIES: dict[EmailKey, EmailCategory] = {
    EmailKey.WELCOME: EmailCategory.TRANSACTIONAL,
    EmailKey.EMAIL_VERIFICATION: EmailCategory.TRANSACTIONAL,
    EmailKey.MAGIC_LINK: EmailCategory.TRANSACTIONAL,
    EmailKey.PASSWORD_RESET: EmailCategory.TRANSACTIONAL,
    EmailKey.INVITATION: EmailCategory.TRANSACTIONAL,
    EmailKey.NEWSLETTER_WELCOME: EmailCategory.MARKETING,
    # Lifecycle, not marketing: each one reports a state the recipient's own
    # agent is in. Each maps to one preference on the user (the `notify_*`
    # columns), consulted where recipients are resolved, in NotificationService.
    EmailKey.BUDGET_EXCEEDED: EmailCategory.LIFECYCLE,
    EmailKey.APPROVAL_REQUESTED: EmailCategory.LIFECYCLE,
    EmailKey.USAGE_REPORT: EmailCategory.LIFECYCLE,
}


class EmailService:
    """Renders and sends this deployment's transactional mail.

    `app_name` is a **required** argument on every send rather than a constant in
    here, and that is the point of it: the name is what the administrator sets on
    `/admin/settings`, so a default would be a second answer to "what is this
    product called" and the first email after a rename would be the one that
    disagrees. It was three hardcoded `"agenticos"` literals before #914. Callers
    resolve it through `DeploymentSettingsService.effective_app_name`, which has no
    session here to read it with.
    """

    def __init__(self, provider: EmailProvider) -> None:
        self.provider = provider

    async def send(
        self,
        *,
        key: EmailKey,
        to: str,
        context: dict[str, Any],
    ) -> SendResult:
        """Render and send one email.

        There is deliberately no opt-out check here: this method holds an
        address, not a user, and cannot ask the database what its owner wants.
        The lifecycle keys (budget exceeded, approval requested, usage report)
        are declinable, and their check lives in NotificationService, where
        recipients are resolved - an address that reaches this method has
        already passed it. The transactional keys have no preference at all.
        """
        subject, html, text = render_email(key.value, context)

        message = EmailMessage(
            to=[to],
            from_email=settings.EMAIL_FROM,
            from_name=settings.EMAIL_FROM_NAME,
            subject=subject,
            html=html,
            text=text,
            reply_to=getattr(settings, "EMAIL_REPLY_TO", None),
            tags=[_CATEGORIES[key].value, key.value],
        )

        result = await self.provider.send(message)
        if not result.accepted:
            logger.error(
                "email_not_accepted",
                extra={"key": key.value, "to": to, "error": result.error},
            )
        return result

    async def send_welcome(
        self, *, to: str, name: str, login_url: str, app_name: str
    ) -> SendResult:
        return await self.send(
            key=EmailKey.WELCOME,
            to=to,
            context={"name": name, "login_url": login_url, "app_name": app_name},
        )

    async def send_password_reset(
        self, *, to: str, name: str, reset_url: str, app_name: str
    ) -> SendResult:
        return await self.send(
            key=EmailKey.PASSWORD_RESET,
            to=to,
            context={
                "name": name,
                "reset_url": reset_url,
                "expires_in": "1 hour",
                "app_name": app_name,
            },
        )

    async def send_invitation(
        self, *, to: str, inviter_name: str, org_name: str, accept_url: str, app_name: str
    ) -> SendResult:
        return await self.send(
            key=EmailKey.INVITATION,
            to=to,
            context={
                "inviter_name": inviter_name,
                "org_name": org_name,
                "accept_url": accept_url,
                "app_name": app_name,
            },
        )


def get_email_service() -> EmailService:
    return EmailService(provider=get_email_provider())
