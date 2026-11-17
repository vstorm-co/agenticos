"""Loopback registration rejects forged callbacks and never prints app credentials."""

import http.client
import json
from http.server import HTTPServer
from threading import Thread
from unittest.mock import Mock
from urllib.parse import urlencode
from uuid import uuid4

import click
import pytest
from click.testing import CliRunner

from app.commands import github_app_setup as command
from app.core.exceptions import ExternalServiceError
from app.services.portals.github_app_manifest import Registration

pytestmark = pytest.mark.security


@pytest.mark.parametrize(
    "query,existing,expected",
    [
        ({"state": "a" * 64, "code": "abc123"}, False, 200),
        ({"state": "wrong", "code": "abc123"}, False, 403),
        ({"state": "ż", "code": "abc123"}, False, 403),
        ({"state": "a" * 64, "code": "../secret"}, False, 403),
        ({"state": "a" * 64, "code": "abc123"}, True, 403),
        ({"state": "a" * 64}, False, 403),
    ],
)
def test_callback_is_bound_to_state_and_single_use(
    query: dict[str, str], existing: bool, expected: int, capsys: pytest.CaptureFixture[str]
) -> None:
    received = ["consumed"] if existing else []
    with HTTPServer(("127.0.0.1", 0), command._handler("a" * 64, received)) as server:
        thread = Thread(target=server.handle_request, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        try:
            connection.request("GET", "/callback?" + urlencode(query))
            response = connection.getresponse()
            assert response.status == expected
            assert "abc123" not in response.read().decode()
        finally:
            connection.close()
            thread.join(timeout=2)
        assert not thread.is_alive()
    assert "abc123" not in capsys.readouterr().err
    if expected == 200:
        assert received == ["abc123"]


@pytest.mark.parametrize(
    "status,body", [(403, b"provider-private-secret"), (201, b"bad-json"), (201, b"x" * 65537)]
)
def test_conversion_errors_are_sanitized_and_connection_is_closed(
    monkeypatch: pytest.MonkeyPatch, status: int, body: bytes
) -> None:
    connection = Mock()
    response = connection.getresponse.return_value
    response.status = status
    response.read.return_value = body
    monkeypatch.setattr(command.http.client, "HTTPSConnection", lambda *args, **kwargs: connection)
    with pytest.raises(ExternalServiceError) as error:
        command._convert("singleusecode")
    assert "provider-private-secret" not in error.value.message
    connection.close.assert_called_once()


def test_conversion_preserves_only_the_app_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = Mock()
    response = connection.getresponse.return_value
    response.status = 201
    response.read.return_value = json.dumps(
        {
            "id": 42,
            "slug": "app",
            "pem": "synthetic-private-key" * 3,
            "webhook_secret": "synthetic-webhook-secret",
            "client_secret": "ignored",
        }
    ).encode()
    monkeypatch.setattr(command.http.client, "HTTPSConnection", lambda *args, **kwargs: connection)
    result = command._convert("abc123")
    assert result.id == 42 and "ignored" not in repr(result)
    connection.close.assert_called_once()


def test_wait_handles_callback_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    server = Mock(spec=HTTPServer)
    received = []
    server.handle_request.side_effect = lambda: received.append("code")
    assert command._wait_for_code(server, received, timeout=30) == "code"
    times = iter([0, 100])
    monkeypatch.setattr(command.time, "monotonic", lambda: next(times))
    with pytest.raises(click.ClickException, match="timed out"):
        command._wait_for_code(server, [], timeout=30)


def test_command_hands_credentials_to_vault_without_echo(monkeypatch: pytest.MonkeyPatch) -> None:
    org = uuid4()
    secret = uuid4()
    monkeypatch.setattr(command, "preflight_registration", Mock())
    monkeypatch.setattr(command, "_wait_for_code", lambda *args, **kwargs: "code")
    monkeypatch.setattr(
        command,
        "_convert",
        lambda code: Registration(
            id=42,
            slug="app",
            pem="synthetic-private-key" * 3,
            webhook_secret="synthetic-webhook-secret",
        ),
    )
    store = Mock(return_value=secret)
    monkeypatch.setattr(command, "store_registration", store)
    result = CliRunner().invoke(
        command.github_app_setup,
        ["--base-url", "https://agents.example", "--org", str(org), "--name", "App"],
        input="synthetic-access-token\n",
    )
    assert result.exit_code == 0, result.output
    assert str(secret) in result.output
    for value in ["synthetic-access-token", "synthetic-private-key", "synthetic-webhook-secret"]:
        assert value not in result.output
    assert store.call_args.kwargs["organization_id"] == org


def test_invalid_token_input_is_refused_before_registration() -> None:
    result = CliRunner().invoke(
        command.github_app_setup,
        ["--base-url", "https://agents.example", "--org", str(uuid4()), "--name", "App"],
        input="invalid token\n",
    )
    assert result.exit_code != 0 and "invalid token" not in result.output
