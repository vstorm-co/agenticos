"""Email module - transactional email via SMTP, or log (dev)."""

from app.core.config import settings
from app.services.email.exceptions import EmailProviderError
from app.services.email.providers.base import EmailProvider


def get_email_provider() -> EmailProvider:
    """The provider `EMAIL_PROVIDER` names, or a refusal saying it names nothing.

    The refusal is the point. This used to end `case "log" | _`, so a deployment
    that set `EMAIL_PROVIDER=resend` - a value the module docstring advertised,
    and one no branch has ever handled - got the development provider, and every
    invitation, password reset and approval notice was written to a log line and
    reported as sent (#829).
    """
    match settings.EMAIL_PROVIDER:
        case "smtp":
            from app.services.email.providers.smtp import SMTPProvider

            return SMTPProvider(
                host=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USER,
                password=settings.SMTP_PASSWORD,
                use_tls=settings.SMTP_TLS,
            )
        case "log":
            from app.services.email.providers.log import LogProvider

            return LogProvider(write_to_disk=settings.LOG_PROVIDER_WRITE_TO_DISK)
        case unknown:
            raise EmailProviderError(
                message=f"EMAIL_PROVIDER names {unknown!r}, which nothing here can send with",
                details={"provider": unknown, "supported": ["smtp", "log"]},
            )
