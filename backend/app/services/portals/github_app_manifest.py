"""A customer-owned GitHub App registration; credentials go directly to its Vault."""

import html
import json
import re
from collections.abc import Sequence
from typing import Literal, TypedDict
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, SecretStr, ValidationError

from app.core.exceptions import BadRequestError, ExternalServiceError

EVENT_PERMISSIONS = {
    "issues": "issues",
    "issue_comment": "issues",
    "pull_request": "pull_requests",
    "workflow_run": "actions",
    "release": "contents",
    "push": "contents",
}


class HookAttributes(TypedDict):
    url: str
    active: bool


class GithubManifest(TypedDict):
    name: str
    url: str
    hook_attributes: HookAttributes
    redirect_url: str
    public: bool
    default_permissions: dict[str, Literal["read"]]
    default_events: list[str]


class Registration(BaseModel):
    id: int = Field(gt=0)
    slug: str = Field(pattern=r"^[a-zA-Z0-9-]{1,100}$")
    pem: SecretStr = Field(min_length=32, max_length=32768)
    webhook_secret: SecretStr = Field(min_length=16, max_length=1024)


class StoredSecret(BaseModel):
    id: UUID


def https_origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise BadRequestError(message="Invalid HTTPS origin") from None
    if (
        parsed.scheme != "https"
        or port == 0
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or "?" in value
        or "#" in value
        or any(char.isspace() for char in value)
    ):
        raise BadRequestError(message="Use an HTTPS origin without a path, query or credentials")
    return value.rstrip("/")


def manifest_for(
    *, base_url: str, name: str, callback_url: str, events: Sequence[str]
) -> GithubManifest:
    origin = https_origin(base_url)
    try:
        callback = urlsplit(callback_url)
        port = callback.port
    except ValueError:
        raise BadRequestError(message="Invalid local callback") from None
    if (
        callback.scheme != "http"
        or callback.hostname != "127.0.0.1"
        or callback.path != "/callback"
        or callback.username is not None
        or callback.query
        or callback.fragment
        or port is None
        or port == 0
    ):
        raise BadRequestError(message="The registration callback must be the local setup listener")
    selected = sorted(set(events))
    if not selected or any(event not in EVENT_PERMISSIONS for event in selected):
        raise BadRequestError(message="Choose at least one supported GitHub trigger event")
    if not 1 <= len(name.strip()) <= 34:
        raise BadRequestError(message="Use an app name with 1 to 34 characters")
    permissions: dict[str, Literal["read"]] = {"metadata": "read"}
    permissions.update({EVENT_PERMISSIONS[event]: "read" for event in selected})
    return {
        "name": name.strip(),
        "url": origin,
        "hook_attributes": {"url": f"{origin}/api/v1/webhooks/github-app", "active": True},
        "redirect_url": callback_url,
        "public": False,
        "default_permissions": permissions,
        "default_events": selected,
    }


def registration_form(manifest: GithubManifest, *, state: str, owner: str | None) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", state):
        raise BadRequestError(message="Invalid registration state")
    if owner is not None and not re.fullmatch(
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", owner
    ):
        raise BadRequestError(message="Invalid GitHub organization name")
    path = f"organizations/{owner}/settings/apps/new" if owner else "settings/apps/new"
    action = "https://github.com/" + path + "?" + urlencode({"state": state})
    payload = html.escape(json.dumps(manifest), quote=True)
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="referrer" content="no-referrer"><title>AgenticOS GitHub App setup</title>'
        "<h1>Register your GitHub App</h1><p>This creates a private app owned by your account "
        "or organization, with read-only access on repositories you explicitly install it on.</p>"
        f'<form method="post" action="{html.escape(action, quote=True)}">'
        f'<input type="hidden" name="manifest" value="{payload}">'
        '<button type="submit">Continue on GitHub</button></form></html>'
    )


def store_registration(
    client: httpx.Client,
    *,
    registration: Registration,
    base_url: str,
    organization_id: UUID,
    access_token: SecretStr,
    name: str,
) -> UUID:
    """A single Vault write, with no retries after unknown acceptance."""
    origin = https_origin(base_url)
    try:
        with client.stream(
            "POST",
            f"{origin}/api/v1/secrets",
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {access_token.get_secret_value()}",
                "X-Organization-Id": str(organization_id),
            },
            json={
                "name": name,
                "visibility": "org",
                "purpose": "custom",
                "value": {
                    "kind": "github_app",
                    "app_id": str(registration.id),
                    "private_key": registration.pem.get_secret_value(),
                    "webhook_secret": registration.webhook_secret.get_secret_value(),
                },
            },
        ) as response:
            if response.status_code != 201:
                raise ExternalServiceError(
                    message="Vault did not confirm storage; inspect Vault before retrying"
                )
            body = bytearray()
            for chunk in response.iter_bytes(chunk_size=8192):
                body.extend(chunk)
                if len(body) > 65536:
                    raise ExternalServiceError(
                        message="Vault response exceeded the setup limit; inspect Vault before retrying"
                    )
            return StoredSecret.model_validate_json(bytes(body)).id
    except httpx.HTTPError, ValidationError:
        raise ExternalServiceError(
            message="Vault storage was not confirmed; inspect Vault before retrying"
        ) from None


class _ExistingSecret(BaseModel):
    kind: str
    name: str


class _SecretIndex(BaseModel):
    items: list[_ExistingSecret]


def preflight_registration(
    client: httpx.Client,
    *,
    base_url: str,
    organization_id: UUID,
    access_token: SecretStr,
    name: str,
) -> None:
    """Verify API access and refuse an existing app before creating another on GitHub."""
    try:
        with client.stream(
            "GET",
            f"{https_origin(base_url)}/api/v1/secrets",
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {access_token.get_secret_value()}",
                "X-Organization-Id": str(organization_id),
            },
        ) as response:
            if response.status_code != 200:
                raise ExternalServiceError(
                    message="Vault access was not confirmed; use a token with secrets:view and secrets:edit"
                )
            body = bytearray()
            for chunk in response.iter_bytes(chunk_size=8192):
                body.extend(chunk)
                if len(body) > 1048576:
                    raise ExternalServiceError(message="Vault metadata exceeds the setup limit")
            existing = _SecretIndex.model_validate_json(bytes(body))
        if any(secret.kind == "github_app" for secret in existing.items):
            raise BadRequestError(
                message="This organization already has a GitHub App; connect its existing installation instead"
            )
        if any(secret.name.casefold() == name.strip().casefold() for secret in existing.items):
            raise BadRequestError(
                message="That Vault name is already used; choose a different app name"
            )
    except httpx.HTTPError, ValidationError:
        raise ExternalServiceError(
            message="Vault access was not confirmed; check this instance and access token"
        ) from None
