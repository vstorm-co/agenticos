"""How the SMTP provider negotiates TLS and authentication.

The submission port decides the encryption scheme: 465 opens TLS from the start,
587 and 25 speak plaintext and upgrade with STARTTLS. The shipped defaults are
`SMTP_PORT=587` with `SMTP_TLS=true`, so a provider that opened implicit TLS
there was refused by every standards-compliant server and the deployment sent
nothing (#1543). And an empty `SMTP_USER` means an unauthenticated relay, not a
login attempt with a blank username.
"""

import aiosmtplib
import pytest

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


def _capture(monkeypatch) -> dict:
    sent: dict = {}

    async def fake_send(msg, **kwargs):
        sent.update(kwargs)
        sent["msg"] = msg

    monkeypatch.setattr(aiosmtplib, "send", fake_send)
    return sent


async def test_the_default_port_upgrades_with_starttls_rather_than_implicit_tls(monkeypatch):
    sent = _capture(monkeypatch)

    result = await SMTPProvider(host="mail", port=587, username="", password="", use_tls=True).send(
        _message()
    )

    assert sent["use_tls"] is False
    assert sent["start_tls"] is True
    assert result.accepted is True


async def test_the_implicit_tls_port_still_opens_tls_from_the_start(monkeypatch):
    sent = _capture(monkeypatch)

    await SMTPProvider(host="mail", port=465, username="u", password="p", use_tls=True).send(
        _message()
    )

    assert sent["use_tls"] is True
    assert sent["start_tls"] is False


async def test_tls_off_sends_plaintext_and_never_upgrades(monkeypatch):
    # A local relay on 25 that offers no encryption; forcing STARTTLS would fail.
    sent = _capture(monkeypatch)

    await SMTPProvider(host="mail", port=25, username="", password="", use_tls=False).send(
        _message()
    )

    assert sent["use_tls"] is False
    assert sent["start_tls"] is False


async def test_an_empty_username_relays_unauthenticated(monkeypatch):
    # aiosmtplib attempts AUTH whenever the username is not None, so a blank one
    # turns an open relay into a login attempt the server rejects.
    sent = _capture(monkeypatch)

    await SMTPProvider(host="mail", port=587, username="", password="", use_tls=True).send(
        _message()
    )

    assert sent["username"] is None
    assert sent["password"] is None


async def test_configured_credentials_are_passed_through(monkeypatch):
    sent = _capture(monkeypatch)

    await SMTPProvider(host="mail", port=587, username="me", password="pw", use_tls=True).send(
        _message()
    )

    assert sent["username"] == "me"
    assert sent["password"] == "pw"


async def test_the_message_carries_its_optional_headers(monkeypatch):
    sent = _capture(monkeypatch)

    await SMTPProvider(host="mail", port=587, username="", password="", use_tls=True).send(
        EmailMessage(
            to=["someone@example.com"],
            cc=["watcher@example.com"],
            from_email="noreply@example.com",
            from_name="AgenticOS",
            subject="Your invitation",
            html="<p>hello</p>",
            text="hello",
            reply_to="support@example.com",
        )
    )

    msg = sent["msg"]
    assert msg["From"] == "AgenticOS <noreply@example.com>"
    assert msg["Cc"] == "watcher@example.com"
    assert msg["Reply-To"] == "support@example.com"


async def test_a_send_failure_is_reported_not_raised(monkeypatch):
    async def fail(msg, **kwargs):
        raise aiosmtplib.SMTPConnectError("connection refused")

    monkeypatch.setattr(aiosmtplib, "send", fail)

    result = await SMTPProvider(host="mail", port=587, username="", password="", use_tls=True).send(
        _message()
    )

    assert result.accepted is False
    assert result.provider_message_id == ""
    assert "connection refused" in (result.error or "")
