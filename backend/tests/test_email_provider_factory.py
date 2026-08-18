"""Which provider `EMAIL_PROVIDER` selects, and what an unknown value does.

The last of those is the reason this file exists: the match used to end
`case "log" | _`, so a value nothing handled - `resend`, which the module
docstring advertised and no branch implemented - resolved to the development
provider and every message it was handed was logged and reported as sent (#829).
"""

import tempfile

import pytest

from app.services.email import get_email_provider
from app.services.email.exceptions import EmailProviderError
from app.services.email.providers.base import EmailMessage
from app.services.email.providers.smtp import SMTPProvider

pytestmark = pytest.mark.anyio


def _message() -> EmailMessage:
    return EmailMessage(
        to=["someone@example.com"],
        from_email="noreply@example.com",
        subject="Your invitation",
        html="<p>hello</p>",
        text="hello",
    )


async def test_smtp_is_selected_by_name(monkeypatch):
    monkeypatch.setattr("app.services.email.settings.EMAIL_PROVIDER", "smtp")
    assert isinstance(get_email_provider(), SMTPProvider)


async def test_the_log_provider_honours_the_write_to_disk_setting(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.email.settings.EMAIL_PROVIDER", "log")
    monkeypatch.setattr("app.services.email.settings.LOG_PROVIDER_WRITE_TO_DISK", True)
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix: str(tmp_path))

    await get_email_provider().send(_message())

    assert list(tmp_path.glob("*.html")), "the setting was read but nothing was written"


async def test_an_unknown_provider_is_refused_rather_than_logged(monkeypatch):
    monkeypatch.setattr("app.services.email.settings.EMAIL_PROVIDER", "resend")

    with pytest.raises(EmailProviderError) as excinfo:
        get_email_provider()

    assert excinfo.value.details == {"provider": "resend", "supported": ["smtp", "log"]}
