"""Read-only app registration and Vault handoff never expose generated credentials."""

import json
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.services.portals.github_app_manifest import (
    GithubManifest,
    Registration,
    https_origin,
    manifest_for,
    preflight_registration,
    registration_form,
    store_registration,
)

pytestmark = pytest.mark.security


def manifest(events: tuple[str, ...] = ("issues", "issue_comment")) -> GithubManifest:
    return manifest_for(
        base_url="https://agents.example/",
        name="Support",
        callback_url="http://127.0.0.1:8765/callback",
        events=events,
    )


def test_selected_events_request_only_required_read_permissions() -> None:
    value = manifest()
    assert value["default_permissions"] == {"metadata": "read", "issues": "read"}
    assert value["default_events"] == ["issue_comment", "issues"]
    assert value["hook_attributes"]["url"] == "https://agents.example/api/v1/webhooks/github-app"
    assert value["redirect_url"] == "http://127.0.0.1:8765/callback"
    assert value["public"] is False
    assert manifest(("push", "release", "pull_request", "workflow_run"))["default_permissions"] == {
        "metadata": "read",
        "contents": "read",
        "pull_requests": "read",
        "actions": "read",
    }


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.com",
        "https://a:b@example.com",
        "https://example.com/path",
        "https://example.com?secret=x",
        "https://example.com#x",
        "https://exa mple.com",
    ],
)
def test_origin_refusals_do_not_echo_input(origin: str) -> None:
    with pytest.raises(BadRequestError) as error:
        https_origin(origin)
    assert origin not in error.value.message


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8765/callback",
        "http://evil.example:8765/callback",
        "http://127.0.0.1/callback",
        "http://127.0.0.1:8765/other",
        "http://user@127.0.0.1:8765/callback",
        "http://127.0.0.1:8765/callback?code=secret",
        "http://127.0.0.1:8765/callback#x",
    ],
)
def test_callback_is_only_the_local_listener(url: str) -> None:
    with pytest.raises(BadRequestError):
        manifest_for(
            base_url="https://agents.example", name="Support", callback_url=url, events=["issues"]
        )


@pytest.mark.parametrize(
    "name,events",
    [("", ["issues"]), ("a" * 35, ["issues"]), ("Support", []), ("Support", ["admin"])],
)
def test_invalid_manifests_are_refused(name: str, events: list[str]) -> None:
    with pytest.raises(BadRequestError):
        manifest_for(
            base_url="https://agents.example",
            name=name,
            callback_url="http://127.0.0.1:8765/callback",
            events=events,
        )


def test_form_targets_only_github_and_escapes_names() -> None:
    value = manifest()
    value["name"] = "<script>secret</script>"
    page = registration_form(value, state="a" * 64, owner="vstorm-co")
    assert 'method="post"' in page
    assert "https://github.com/organizations/vstorm-co/settings/apps/new?state=" in page
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "https://github.com/settings/apps/new?" in registration_form(
        value, state="a" * 64, owner=None
    )
    with pytest.raises(BadRequestError):
        registration_form(value, state="invalid", owner=None)
    with pytest.raises(BadRequestError):
        registration_form(value, state="a" * 64, owner="evil/path")


def test_vault_receives_credentials_with_exact_organization_authority() -> None:
    organization_id, secret_id = uuid4(), uuid4()
    registration = Registration(
        id=42,
        slug="my-app",
        pem="synthetic-private-key" * 3,
        webhook_secret="synthetic-webhook-secret",
    )

    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://agents.example/api/v1/secrets"
        assert request.headers["authorization"] == "Bearer synthetic-access-token"
        assert request.headers["x-organization-id"] == str(organization_id)
        payload = json.loads(request.content)
        assert payload["value"] == {
            "kind": "github_app",
            "app_id": "42",
            "private_key": "synthetic-private-key" * 3,
            "webhook_secret": "synthetic-webhook-secret",
        }
        assert payload["visibility"] == "org"
        return httpx.Response(201, json={"id": str(secret_id)})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert (
            store_registration(
                client,
                registration=registration,
                base_url="https://agents.example",
                organization_id=organization_id,
                access_token=SecretStr("synthetic-access-token"),
                name="App",
            )
            == secret_id
        )
    assert "synthetic-private-key" not in repr(registration)
    assert "synthetic-webhook-secret" not in repr(registration)


@pytest.mark.parametrize(
    "status,body",
    [
        (302, {"secret": "do-not-print"}),
        (403, {"secret": "do-not-print"}),
        (201, {"id": "do-not-print"}),
    ],
)
def test_vault_failure_never_echoes_provider_payload(status: int, body: dict[str, str]) -> None:
    registration = Registration(
        id=42,
        slug="app",
        pem="synthetic-private-key" * 3,
        webhook_secret="synthetic-webhook-secret",
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body)),
            follow_redirects=False,
        ) as client,
        pytest.raises(ExternalServiceError) as error,
    ):
        store_registration(
            client,
            registration=registration,
            base_url="https://agents.example",
            organization_id=uuid4(),
            access_token=SecretStr("access"),
            name="App",
        )
    assert "do-not-print" not in error.value.message


def test_uncertain_vault_write_is_not_retried() -> None:
    client = Mock(spec=httpx.Client)
    client.stream.side_effect = httpx.ReadTimeout("do-not-print")
    with pytest.raises(ExternalServiceError) as error:
        store_registration(
            client,
            registration=Registration(
                id=42,
                slug="app",
                pem="synthetic-private-key" * 3,
                webhook_secret="synthetic-webhook-secret",
            ),
            base_url="https://agents.example",
            organization_id=uuid4(),
            access_token=SecretStr("access"),
            name="App",
        )
    assert client.stream.call_count == 1
    assert "do-not-print" not in error.value.message


@pytest.mark.parametrize(
    "value", ["https://[", "https://example.com:invalid", "https://example.com:0"]
)
def test_malformed_origins_are_domain_errors(value: str) -> None:
    with pytest.raises(BadRequestError):
        https_origin(value)


@pytest.mark.parametrize(
    "value", ["http://127.0.0.1:invalid/callback", "http://127.0.0.1:0/callback"]
)
def test_malformed_callback_ports_are_domain_errors(value: str) -> None:
    with pytest.raises(BadRequestError):
        manifest_for(
            base_url="https://agents.example", name="App", callback_url=value, events=["issues"]
        )


def test_oversize_vault_response_is_bounded() -> None:
    registration = Registration(
        id=42,
        slug="app",
        pem="synthetic-private-key" * 3,
        webhook_secret="synthetic-webhook-secret",
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(201, content=b"x" * 65537))
        ) as client,
        pytest.raises(ExternalServiceError, match="exceeded"),
    ):
        store_registration(
            client,
            registration=registration,
            base_url="https://agents.example",
            organization_id=uuid4(),
            access_token=SecretStr("access"),
            name="App",
        )


@pytest.mark.parametrize(
    "items,error",
    [
        ([], False),
        ([{"kind": "github_app", "name": "Existing"}], True),
        ([{"kind": "api_key", "name": "APP"}], True),
    ],
)
def test_preflight_checks_vault_before_registration(
    items: list[dict[str, str]], error: bool
) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"items": items}))
    ) as client:
        if error:
            with pytest.raises(BadRequestError):
                preflight_registration(
                    client,
                    base_url="https://agents.example",
                    organization_id=uuid4(),
                    access_token=SecretStr("access"),
                    name="App",
                )
        else:
            preflight_registration(
                client,
                base_url="https://agents.example",
                organization_id=uuid4(),
                access_token=SecretStr("access"),
                name="App",
            )


@pytest.mark.parametrize(
    "status,body", [(403, b"private"), (200, b"invalid"), (200, b"x" * 1048577)]
)
def test_preflight_failures_are_bounded(status: int, body: bytes) -> None:
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, content=body))
        ) as client,
        pytest.raises(ExternalServiceError) as error,
    ):
        preflight_registration(
            client,
            base_url="https://agents.example",
            organization_id=uuid4(),
            access_token=SecretStr("access"),
            name="App",
        )
    assert "private" not in error.value.message
