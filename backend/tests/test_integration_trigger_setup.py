"""Offline preparation must never activate or run a customer's routine."""

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from click.testing import CliRunner

from app.commands import integration_trigger_setup as setup

pytestmark = pytest.mark.security


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[list[str], Path]:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Summarize new mail that needs attention.")
    return [
        "--portal",
        "google",
        "--preset",
        "inbox_only",
        "--agent",
        str(uuid4()),
        "--connection",
        str(uuid4()),
        "--prompt-file",
        str(prompt),
    ], tmp_path


def test_offline_listing_uses_native_polling_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse_network(*args: object, **kwargs: object) -> None:
        pytest.fail("Offline listing opened a network client")

    monkeypatch.setattr(setup.httpx, "Client", refuse_network)
    result = CliRunner().invoke(setup.integration_trigger_setup, ["--list"])
    assert result.exit_code == 0, result.output
    for value in ["google\tinbox_only", "outlook_calendar\tbefore_meetings", "imap\tnew_message"]:
        assert value in result.output
    assert "github" not in result.output


def test_offline_payload_pins_account_and_requires_source_review(
    monkeypatch: pytest.MonkeyPatch, inputs: tuple[list[str], Path]
) -> None:
    def refuse_network(*args: object, **kwargs: object) -> None:
        pytest.fail("Offline preparation opened a network client")

    monkeypatch.setattr(setup.httpx, "Client", refuse_network)
    args, _ = inputs
    result = CliRunner().invoke(setup.integration_trigger_setup, args)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["is_active"] is False
    assert payload["review_before_activation"] is True
    assert payload["connection_id"] == args[7]
    assert payload["portal_key"] == "google"
    assert "event_secret" not in payload
    assert "Offline only" in result.stderr


@pytest.mark.parametrize(
    "extra,expected",
    [
        (["--list", "--apply"], "Choose --list"),
        (["--portal", "github", "--preset", "issue_opened"], "polling portals only"),
        (["--portal", "made-up"], "from --list"),
        (["--apply"], "requires --base-url and --org"),
    ],
)
def test_bad_modes_refused_before_network(
    inputs: tuple[list[str], Path], extra: list[str], expected: str
) -> None:
    args, _ = inputs
    result = CliRunner().invoke(setup.integration_trigger_setup, args + extra)
    assert result.exit_code != 0
    assert expected in result.output


@pytest.mark.parametrize("contents", ["not-json", "[]", '{"secret":"sensitive"}junk', "x" * 16385])
def test_bad_filters_never_echo_input(inputs: tuple[list[str], Path], contents: str) -> None:
    args, root = inputs
    path = root / "filter.json"
    path.write_text(contents)
    result = CliRunner().invoke(
        setup.integration_trigger_setup, [*args, "--filter-file", str(path)]
    )
    assert result.exit_code != 0
    assert "sensitive" not in result.output


def test_filters_are_overrides_not_a_replacement_for_preset(inputs: tuple[list[str], Path]) -> None:
    args, root = inputs
    path = root / "filter.json"
    path.write_text('{"subject_contains":"invoice"}')
    result = CliRunner().invoke(
        setup.integration_trigger_setup, [*args, "--filter-file", str(path)]
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["preset_key"] == "inbox_only"
    assert payload["event_config"] == {"subject_contains": "invoice"}


def test_apply_sends_one_paused_request_and_never_echoes_credentials(
    monkeypatch: pytest.MonkeyPatch, inputs: tuple[list[str], Path]
) -> None:
    args, _ = inputs
    org = uuid4()
    routine = uuid4()
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        payload = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer synthetic-access-token"
        assert request.headers["X-Organization-Id"] == str(org)
        assert payload["is_active"] is False and payload["review_before_activation"] is True
        assert payload["connection_id"] == args[7]
        return httpx.Response(
            201,
            json={
                "id": str(routine),
                "agent_id": args[5],
                "connection_id": args[7],
                "is_active": False,
                "delivery_mode": "polling",
            },
        )

    factory = httpx.Client
    monkeypatch.setattr(
        setup.httpx, "Client", lambda **kw: factory(transport=httpx.MockTransport(respond), **kw)
    )
    result = CliRunner().invoke(
        setup.integration_trigger_setup,
        [*args, "--apply", "--base-url", "https://agents.example", "--org", str(org)],
        input="synthetic-access-token\n",
    )
    assert result.exit_code == 0, result.output
    assert str(routine) in result.output
    assert "synthetic-access-token" not in result.output
    assert len(calls) == 1
    assert str(calls[0].url) == f"https://agents.example/api/v1/agents/{args[5]}/triggers"


@pytest.mark.parametrize(
    "status,body",
    [(302, b"sensitive"), (403, b"sensitive"), (201, b"sensitive"), (201, b"x" * 65537)],
)
def test_uncertain_or_refused_creation_never_retries_or_echoes_response(
    monkeypatch: pytest.MonkeyPatch, inputs: tuple[list[str], Path], status: int, body: bytes
) -> None:
    args, _ = inputs
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, content=body, headers={"Location": "https://other.example"})

    factory = httpx.Client
    monkeypatch.setattr(
        setup.httpx, "Client", lambda **kw: factory(transport=httpx.MockTransport(respond), **kw)
    )
    result = CliRunner().invoke(
        setup.integration_trigger_setup,
        [*args, "--apply", "--base-url", "https://agents.example", "--org", str(uuid4())],
        input="synthetic-access-token\n",
    )
    assert result.exit_code != 0
    assert "sensitive" not in result.output
    assert len(calls) == 1


@pytest.mark.parametrize("token", ["bad token", "żółw", "bad\x00token", "bad\x7ftoken", "x" * 8193])
def test_invalid_tokens_refused_without_echo(inputs: tuple[list[str], Path], token: str) -> None:
    args, root = inputs
    path = root / "access-token"
    path.write_text(token)
    result = CliRunner().invoke(
        setup.integration_trigger_setup,
        [
            *args,
            "--apply",
            "--base-url",
            "https://agents.example",
            "--org",
            str(uuid4()),
            "--access-token-file",
            str(path),
        ],
    )
    assert result.exit_code != 0
    assert token not in result.output


def test_account_inspection_reads_only_local_api_and_omits_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = uuid4()
    account = uuid4()
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET"
        assert request.headers["X-Organization-Id"] == str(org)
        return httpx.Response(
            200,
            json={
                "total": 1,
                "items": [
                    {
                        "key": "google",
                        "name": "Gmail",
                        "description": "Mail",
                        "category": "email",
                        "event_source": "gmail",
                        "delivery": "polling",
                        "native_provider": "google",
                        "presets": [],
                        "connection_choices": [
                            {
                                "id": str(account),
                                "provider": "google",
                                "email": "test@example.com",
                                "scopes": ["private-scope"],
                                "owner": "personal",
                                "needs_reconnect": True,
                                "created_at": "2026-11-17T00:00:00Z",
                                "access_token": "must-never-print",
                            }
                        ],
                    }
                ],
            },
        )

    factory = httpx.Client
    monkeypatch.setattr(
        setup.httpx, "Client", lambda **kw: factory(transport=httpx.MockTransport(respond), **kw)
    )
    result = CliRunner().invoke(
        setup.integration_trigger_setup,
        [
            "--accounts",
            "--portal",
            "google",
            "--base-url",
            "https://agents.example",
            "--org",
            str(org),
        ],
        input="synthetic-access-token\n",
    )
    assert result.exit_code == 0, result.output
    assert str(account) in result.output
    assert '"needs_reconnect":true' in result.output
    assert "must-never-print" not in result.output
    assert "synthetic-access-token" not in result.output
    assert "private-scope" not in result.output
    assert len(calls) == 1


@pytest.mark.parametrize(
    "extra", [[], ["--base-url", "http://agents.example"], ["--portal", "github"]]
)
def test_account_listing_requires_explicit_valid_destination(extra: list[str]) -> None:
    result = CliRunner().invoke(
        setup.integration_trigger_setup, ["--accounts", "--org", str(uuid4()), *extra]
    )
    assert result.exit_code != 0


@pytest.mark.parametrize("active,mismatch", [(True, False), (False, True)])
def test_creation_response_must_be_paused_for_the_exact_account(
    monkeypatch: pytest.MonkeyPatch, inputs: tuple[list[str], Path], active: bool, mismatch: bool
) -> None:
    args, _ = inputs

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "id": str(uuid4()),
                "agent_id": args[5],
                "connection_id": str(uuid4()) if mismatch else args[7],
                "is_active": active,
                "delivery_mode": "polling",
            },
        )

    factory = httpx.Client
    monkeypatch.setattr(
        setup.httpx, "Client", lambda **kw: factory(transport=httpx.MockTransport(respond), **kw)
    )
    result = CliRunner().invoke(
        setup.integration_trigger_setup,
        [
            *args,
            "--apply",
            "--base-url",
            "https://agents.example",
            "--org",
            str(uuid4()),
        ],
        input="synthetic-access-token\n",
    )
    assert result.exit_code != 0
    assert "Created paused routine" not in result.output
