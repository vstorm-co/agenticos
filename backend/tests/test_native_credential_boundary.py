"""Vault secrets go straight to the named provider adapter, never back to an API."""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.exceptions import NotFoundError
from app.core.secret_kinds import ApiKeySecret, EntraAppSecret, GcpServiceAccountSecret, SecretKind
from app.db.models.organization_secret import OrganizationSecret
from app.services import organization_secret as secrets
from app.services.integrations import ApplicationGrant
from app.services.organization_secret import OrganizationSecretService

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("provider", ["google", "microsoft"])
async def test_application_credential_is_opened_only_for_its_organization_and_provider(
    monkeypatch, provider
):
    org, identifier = uuid4(), uuid4()
    value = (
        GcpServiceAccountSecret(
            service_account_json=SecretStr(
                json.dumps(
                    {
                        "type": "service_account",
                        "project_id": "project",
                        "client_email": "bot@example.com",
                        "private_key": "key",
                    }
                )
            )
        )
        if provider == "google"
        else EntraAppSecret(
            tenant_id=str(uuid4()), client_id=str(uuid4()), client_secret="private-secret"
        )
    )
    row = OrganizationSecret(
        id=identifier,
        organization_id=org,
        kind=value.kind.value,
        sealed_secret="sealed",
        key_version=1,
    )
    lookup = AsyncMock(return_value=row)
    monkeypatch.setattr(secrets.organization_secret_repo, "get", lookup)
    opened = []

    def unseal(ciphertext, **kwargs):
        opened.append(kwargs)
        return value

    monkeypatch.setattr(secrets, "unseal_secret", unseal)
    exchange = AsyncMock(
        return_value=SecretStr("access-token")
        if provider == "google"
        else ApplicationGrant(
            access_token=SecretStr("access-token"), granted_scopes=frozenset({"read"})
        )
    )
    monkeypatch.setattr(f"app.services.integrations.{provider}_token", exchange)
    result = await OrganizationSecretService(AsyncMock()).integration_token(
        organization_id=org,
        secret_id=identifier,
        provider=provider,
        subject="person@example.com",
        scopes=["read"],
    )
    assert result.get_secret_value() == "access-token" and "access-token" not in repr(result)
    assert lookup.await_args.kwargs == {"organization_id": org}
    assert opened[0]["scope"].subject_id == org
    assert exchange.await_args.args == (value,)
    assert exchange.await_args.kwargs == (
        {"subject": "person@example.com", "scopes": ["read"]} if provider == "google" else {}
    )


@pytest.mark.parametrize("failure", ["missing", "kind", "value"])
async def test_missing_or_wrong_credentials_cannot_reach_an_application_token_endpoint(
    monkeypatch, failure
):
    row = OrganizationSecret(
        id=uuid4(),
        organization_id=uuid4(),
        kind="api_key" if failure == "kind" else SecretKind.ENTRA_APP.value,
        sealed_secret="sealed",
        key_version=1,
    )
    monkeypatch.setattr(
        secrets.organization_secret_repo,
        "get",
        AsyncMock(return_value=None if failure == "missing" else row),
    )
    monkeypatch.setattr(
        secrets, "unseal_secret", lambda *args, **kwargs: ApiKeySecret(api_key="unrelated-key")
    )
    exchange = AsyncMock()
    monkeypatch.setattr("app.services.integrations.microsoft_token", exchange)
    with pytest.raises(NotFoundError):
        await OrganizationSecretService(AsyncMock()).integration_token(
            organization_id=row.organization_id,
            secret_id=row.id,
            provider="microsoft",
            subject=None,
            scopes=[],
        )
    exchange.assert_not_awaited()


@pytest.mark.parametrize(
    "provider,roles,refused",
    [
        ("microsoft", {"Mail.Read"}, False),
        ("microsoft", set(), True),
        ("microsoft", {"Files.Read.All"}, True),
        ("google", set(), False),
    ],
)
async def test_renewal_cannot_silently_keep_revoked_application_permissions(
    monkeypatch, provider, roles, refused
):
    from app.core.exceptions import AuthorizationError

    grant = AsyncMock(
        return_value=ApplicationGrant(
            access_token=SecretStr("private-bearer"), granted_scopes=frozenset(roles)
        )
    )
    monkeypatch.setattr(OrganizationSecretService, "integration_grant", grant)
    service = OrganizationSecretService(AsyncMock())
    kwargs = {
        "organization_id": uuid4(),
        "secret_id": uuid4(),
        "provider": provider,
        "subject": None,
        "scopes": ["Mail.Read"],
    }
    if refused:
        with pytest.raises(AuthorizationError, match="permissions changed"):
            await service.integration_token(**kwargs)
    else:
        assert await service.integration_token(**kwargs) == SecretStr("private-bearer")
