"""Reusable sources dereference organization Vault authority on every delivery."""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.secret_kinds import (
    ApiKeySecret,
    SecretKind,
    WebhookCredentialsSecret,
    seal_secret,
)
from app.core.vault import VaultScope, seal, unseal
from app.db.models.organization_secret import OrganizationSecret
from app.schemas.event_source import (
    EventSourceCreate,
    EventSourceUpdate,
    SourceAuth,
    SourceCredentials,
)
from app.services import event_sources as module
from app.services import organization_secret as secrets_module
from app.services.event_sources import credential_json
from app.services.organization_secret import OrganizationSecretService
from tests.test_event_source_management import ctx as ctx
from tests.test_event_source_management import setup as setup
from tests.test_event_source_management import source as source

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def vault(ctx, monkeypatch):
    envelope = seal_secret(
        ApiKeySecret(api_key=SecretStr("shared-secret")),
        scope=VaultScope.organization(ctx.organization_id),
    )
    row = OrganizationSecret(
        id=uuid4(),
        organization_id=ctx.organization_id,
        kind="api_key",
        purpose="custom",
        visibility="org",
        owner_user_id=None,
        sealed_secret=envelope.ciphertext,
        key_version=envelope.key_version,
        name="Webhook signing",
    )
    monkeypatch.setattr(
        secrets_module.organization_secret_repo, "event_source_secret", AsyncMock(return_value=row)
    )
    monkeypatch.setattr(OrganizationSecretService, "get_usable", AsyncMock(return_value=row))
    return row


def bind(source, credential, secret_id):
    envelope = seal(
        credential_json(SourceCredentials(vault_secret_id=secret_id)),
        scope=VaultScope.organization(source.organization_id),
    )
    credential.sealed_secret, credential.secret_key_version = (
        envelope.ciphertext,
        envelope.key_version,
    )


def signed(key):
    return {"x-signature-256": "sha256=" + hmac.new(key, b"{}", hashlib.sha256).hexdigest()}


async def test_creation_stores_a_reference_without_copying_or_returning_the_value(
    ctx, setup, vault
):
    service, _, saved = setup
    result = await service.create(
        ctx,
        EventSourceCreate(name="Events", credentials=SourceCredentials(vault_secret_id=vault.id)),
    )
    stored = saved[0]
    opened = json.loads(
        unseal(
            stored.sealed_secret,
            scope=VaultScope.organization(ctx.organization_id),
            key_version=stored.secret_key_version,
        )
    )
    assert opened == {"vault_secret_id": str(vault.id)}
    assert "shared-secret" not in result.model_dump_json()
    assert result.reveal_secret is None
    OrganizationSecretService.get_usable.assert_awaited_once_with(
        ctx, vault.id, kind=SecretKind.API_KEY
    )


@pytest.mark.parametrize("case", ["missing", "private", "personal", "wrong_kind", "foreign"])
async def test_runtime_refuses_missing_private_personal_wrong_kind_and_foreign_credentials(
    ctx, setup, vault, monkeypatch, case
):
    service, credential, _ = setup
    if case == "missing":
        monkeypatch.setattr(
            secrets_module.organization_secret_repo,
            "event_source_secret",
            AsyncMock(return_value=None),
        )
    elif case == "private":
        vault.visibility = "private"
    elif case == "personal":
        vault.owner_user_id = ctx.user_id
    elif case == "wrong_kind":
        vault.kind = "smtp_account"
    else:
        vault.organization_id = uuid4()
    with pytest.raises(NotFoundError):
        await OrganizationSecretService(service.db).event_source_credentials(
            ctx.organization_id, vault.id
        )


async def test_webhook_uses_rotated_value_and_refuses_old_signatures(
    ctx, source, setup, vault, monkeypatch
):
    service, credential, _ = setup
    bind(source, credential, vault.id)
    monkeypatch.setattr(module.repo, "admit", AsyncMock(return_value=True))
    await service.receive(source.id, body=b"{}", headers=signed(b"shared-secret"))
    rotated = seal_secret(
        ApiKeySecret(api_key=SecretStr("rotated-secret")),
        scope=VaultScope.organization(ctx.organization_id),
    )
    vault.sealed_secret, vault.key_version = rotated.ciphertext, rotated.key_version
    with pytest.raises(AuthorizationError, match="did not verify"):
        await service.receive(source.id, body=b"{}", headers=signed(b"shared-secret"))
    await service.receive(source.id, body=b"{}", headers=signed(b"rotated-secret"))
    assert module.repo.admit.await_count == 2


async def test_rotation_between_signature_check_and_admission_refuses_delivery(
    ctx, source, setup, vault, monkeypatch
):
    service, credential, _ = setup
    bind(source, credential, vault.id)
    original = secrets_module.organization_secret_repo.event_source_secret

    async def changed(*args, **kwargs):
        if kwargs["lock"]:
            envelope = seal_secret(
                ApiKeySecret(api_key=SecretStr("rotated-secret")),
                scope=VaultScope.organization(ctx.organization_id),
            )
            vault.sealed_secret, vault.key_version = envelope.ciphertext, envelope.key_version
        return vault

    original.side_effect = changed
    admit = AsyncMock()
    monkeypatch.setattr(module.repo, "admit", admit)
    with pytest.raises(AuthorizationError, match="changed during"):
        await service.receive(source.id, body=b"{}", headers=signed(b"shared-secret"))
    admit.assert_not_awaited()


async def test_basic_vault_credentials_are_ingress_only_and_keep_passwords_out_of_hints(
    ctx, source, setup, vault
):
    service, _, _ = setup
    value = WebhookCredentialsSecret(username=SecretStr("user"), password=SecretStr("x"))
    assert value.hint == ""
    assert "'x'" not in repr(value)
    envelope = seal_secret(value, scope=VaultScope.organization(ctx.organization_id))
    vault.kind, vault.sealed_secret, vault.key_version = (
        "webhook_credentials",
        envelope.ciphertext,
        envelope.key_version,
    )
    stored, reveal = await service._prepare_credentials(
        ctx, SourceAuth(method="basic"), SourceCredentials(vault_secret_id=vault.id), generate=False
    )
    assert stored.vault_secret_id == vault.id and reveal is None
    resolved = await service._vault_credentials(
        ctx.organization_id, vault.id, SourceAuth(method="basic")
    )
    assert resolved.password.get_secret_value() == "x"
    with pytest.raises(BadRequestError, match="API key"):
        await service._vault_credentials(ctx.organization_id, vault.id, SourceAuth())
    with pytest.raises(ValidationError):
        WebhookCredentialsSecret(username=SecretStr("bad:user"), password=SecretStr("x"))


async def test_reference_and_inline_values_cannot_be_mixed_and_basic_needs_its_own_kind(
    ctx, setup, vault
):
    with pytest.raises(ValidationError):
        SourceCredentials(vault_secret_id=vault.id, secret=SecretStr("also-inline"))
    service, _, _ = setup
    with pytest.raises(BadRequestError, match="webhook credentials"):
        await service._vault_credentials(ctx.organization_id, vault.id, SourceAuth(method="basic"))


async def test_edit_and_rotation_keep_a_live_reference(ctx, source, setup, vault):
    service, credential, _ = setup
    await service.replace_credentials(ctx, source.id, SourceCredentials(vault_secret_id=vault.id))
    await service.update(ctx, source.id, EventSourceUpdate(name="Renamed"))
    assert json.loads(
        unseal(
            credential.sealed_secret,
            scope=VaultScope.organization(ctx.organization_id),
            key_version=credential.secret_key_version,
        )
    ) == {"vault_secret_id": str(vault.id)}


async def test_binding_a_reference_requires_resource_permission(ctx, setup, vault):
    service, _, saved = setup
    OrganizationSecretService.get_usable.side_effect = NotFoundError(message="Secret not found")
    with pytest.raises(NotFoundError):
        await service.create(
            ctx,
            EventSourceCreate(
                name="Denied", credentials=SourceCredentials(vault_secret_id=vault.id)
            ),
        )
    assert saved == []


async def test_a_malformed_vault_reader_result_is_an_explicit_failure(
    ctx, setup, vault, monkeypatch
):
    from app.core.secret_kinds import NoSecret

    service, _, _ = setup
    monkeypatch.setattr(secrets_module, "unseal_secret", lambda *args, **kwargs: NoSecret())
    with pytest.raises(BadRequestError, match="unsupported kind"):
        await OrganizationSecretService(service.db).event_source_credentials(
            ctx.organization_id, vault.id
        )


async def test_ingress_basic_credentials_never_qualify_for_transcription(
    ctx, setup, vault, monkeypatch
):
    service, _, _ = setup
    value = WebhookCredentialsSecret(
        username=SecretStr("Webhook user"), password=SecretStr("Ingress password")
    )
    envelope = seal_secret(value, scope=VaultScope.organization(ctx.organization_id))
    vault.kind = SecretKind.WEBHOOK_CREDENTIALS.value
    vault.purpose = "openai"
    vault.sealed_secret, vault.key_version = envelope.ciphertext, envelope.key_version
    monkeypatch.setattr(
        secrets_module.organization_secret_repo, "get", AsyncMock(return_value=vault)
    )
    unseal = AsyncMock()
    monkeypatch.setattr(secrets_module, "unseal_secret", unseal)
    reader = OrganizationSecretService(service.db)

    assert (
        await reader.usable_transcription_key(
            ctx.organization_id, vault.id, provider="openai", shared=True
        )
        is None
    )
    assert (
        await reader.transcription_key(
            ctx.organization_id, vault.id, provider="openai", shared=True
        )
        is None
    )
    unseal.assert_not_called()
