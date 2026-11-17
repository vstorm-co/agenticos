"""Own-account channel setup defaults to linked users and no provider traffic."""

import json
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from click.testing import CliRunner

from app.commands import channel_setup as command
from app.core.config import settings

pytestmark = pytest.mark.security


def fake_service(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    service = SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(id=uuid4())))

    @asynccontextmanager
    async def context(org: str | None) -> AsyncIterator[SimpleNamespace]:
        yield service

    monkeypatch.setattr(command, "_channel_service", context)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://agents.example")
    return service


def test_email_setup_keeps_the_shared_key_in_a_private_file_and_vault(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = fake_service(monkeypatch)
    monkeypatch.setattr(command, "get_email_provider", lambda: SimpleNamespace(delivers=True))
    path = tmp_path / "relay.json"
    result = CliRunner().invoke(
        command.channel_add_email,
        ["--name", "Support", "--address", "agent@example.com", "--relay-config", str(path)],
    )
    assert result.exit_code == 0, result.output
    config = json.loads(path.read_text())
    data = service.create.call_args.args[0]
    assert config["webhook_secret"] == data.webhook_secret
    assert data.access_policy.mode == "jwt_linked" and data.webhook_mode
    assert config["webhook_secret"] not in result.output
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert str(service.create.return_value.id) in config["webhook_url"]


def test_email_never_overwrites_an_existing_relay_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = fake_service(monkeypatch)
    monkeypatch.setattr(command, "get_email_provider", lambda: SimpleNamespace(delivers=True))
    path = tmp_path / "relay.json"
    path.write_text("existing-key")
    result = CliRunner().invoke(
        command.channel_add_email,
        ["--name", "Support", "--address", "agent@example.com", "--relay-config", str(path)],
    )
    assert result.exit_code != 0 and path.read_text() == "existing-key"
    service.create.assert_not_awaited()


def test_email_setup_refuses_a_non_delivering_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = fake_service(monkeypatch)
    monkeypatch.setattr(command, "get_email_provider", lambda: SimpleNamespace(delivers=False))
    result = CliRunner().invoke(
        command.channel_add_email,
        [
            "--name",
            "Support",
            "--address",
            "agent@example.com",
            "--relay-config",
            str(tmp_path / "relay.json"),
        ],
    )
    assert result.exit_code != 0
    service.create.assert_not_awaited()


def test_sms_setup_prompts_privately_and_sends_no_message(monkeypatch: pytest.MonkeyPatch) -> None:
    service = fake_service(monkeypatch)
    secret = "b" * 32
    result = CliRunner().invoke(
        command.channel_add_sms,
        ["--name", "Support", "--account-sid", "AC" + "a" * 32, "--from-number", "+15551234567"],
        input=secret + "\n",
    )
    assert result.exit_code == 0, result.output
    assert secret not in result.output
    data = service.create.call_args.args[0]
    assert data.access_policy.mode == "jwt_linked" and data.access_policy.rate_limit_rpm == 3
    assert data.webhook_mode and data.token == "AC" + "a" * 32 + ":" + secret + ":+15551234567"
    assert "No number was bought and no SMS was sent" in result.output


def test_email_relay_validates_without_sending_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_id = uuid4()
    config = tmp_path / "relay.json"
    config.write_text(
        json.dumps(
            {
                "bot_id": str(bot_id),
                "from_address": "agent@example.com",
                "webhook_url": f"https://agents.example/api/v1/email/{bot_id}/inbound",
                "webhook_secret": "synthetic-webhook-secret",
            }
        )
    )
    message = tmp_path / "message.json"
    message.write_text(
        json.dumps(
            {
                "from": "ada@example.com",
                "sender_authentication": {"dmarc": "pass", "from": "ada@example.com"},
                "message_id": "<one@example.com>",
                "text": "hello",
            }
        )
    )
    client = Mock()
    monkeypatch.setattr(command.httpx, "Client", client)
    result = CliRunner().invoke(
        command.email_relay_send, ["--config", str(config), "--message", str(message)]
    )
    assert result.exit_code == 0, result.output
    client.assert_not_called()
    assert "No request sent" in result.output and "synthetic-webhook-secret" not in result.output


def test_email_relay_signs_only_with_an_explicit_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_id = uuid4()
    config = tmp_path / "relay.json"
    config.write_text(
        json.dumps(
            {
                "bot_id": str(bot_id),
                "from_address": "agent@example.com",
                "webhook_url": f"https://agents.example/api/v1/email/{bot_id}/inbound",
                "webhook_secret": "synthetic-webhook-secret",
            }
        )
    )
    message = tmp_path / "message.json"
    message.write_text(
        json.dumps(
            {
                "from": "ada@example.com",
                "sender_authentication": {"dmarc": "pass", "from": "ada@example.com"},
                "message_id": "<one@example.com>",
                "text": "hello",
            }
        )
    )
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert command.EmailAdapter().verify_webhook_signature(
            dict(request.headers), "synthetic-webhook-secret", request.content.decode()
        )
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False)
    monkeypatch.setattr(command.httpx, "Client", lambda **kwargs: client)
    result = CliRunner().invoke(
        command.email_relay_send, ["--config", str(config), "--message", str(message), "--send"]
    )
    assert result.exit_code == 0, result.output
    assert len(calls) == 1


def test_sms_webhook_default_is_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import channel_bot
    from app.services.channels import sms_setup

    service = fake_service(monkeypatch)
    bot_id = uuid4()
    service.get = AsyncMock(return_value=SimpleNamespace(id=bot_id, platform="sms"))
    monkeypatch.setattr(
        channel_bot,
        "unseal_bot_token",
        lambda bot: "AC" + "a" * 32 + ":" + "b" * 32 + ":+15551234567",
    )
    configure = AsyncMock()
    monkeypatch.setattr(sms_setup, "configure_sms_webhook", configure)
    result = CliRunner().invoke(command.channel_configure_sms_webhook, ["--bot-id", str(bot_id)])
    assert result.exit_code == 0, result.output
    configure.assert_not_awaited()
    assert "No provider request sent" in result.output
