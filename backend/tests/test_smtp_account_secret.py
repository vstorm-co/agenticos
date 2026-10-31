"""SMTP passwords remain bound to their server and the organization that stored them."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.core.secret_kinds import (
    SecretKind,
    SmtpAccountSecret,
    describe_kinds,
    seal_secret,
    unseal_kind,
)
from app.core.vault import VaultScope
from app.db.models.organization_secret import OrganizationSecret
from app.services import organization_secret as service
from app.services.email.providers.smtp import SMTPProvider

pytestmark = pytest.mark.anyio


def account() -> SmtpAccountSecret:
    return SmtpAccountSecret(
        host="smtp.example.com",
        username="ada@example.com",
        password="smtp-password",
        from_email="ada@example.com",
    )


def test_smtp_round_trip_binds_the_destination_and_never_exposes_a_password_hint() -> None:
    scope = VaultScope.organization(uuid4())
    value = account()
    sealed = seal_secret(value, scope=scope)
    assert "smtp-password" not in repr(value)
    assert "smtp-password" not in sealed.ciphertext
    assert sealed.hint == ""
    restored = unseal_kind(sealed.ciphertext, model=SmtpAccountSecret, scope=scope)
    assert restored.host == value.host and restored.password == value.password
    with pytest.raises(BadRequestError):
        unseal_kind(
            sealed.ciphertext, model=SmtpAccountSecret, scope=VaultScope.organization(uuid4())
        )
    assert SecretKind.SMTP_ACCOUNT in {kind.kind for kind in describe_kinds()}


@pytest.mark.parametrize(
    "field,value",
    [
        ("host", "smtp://evil.example.com"),
        ("host", "mail\r\nother"),
        ("port", 0),
        ("port", 65536),
        ("tls_mode", "none"),
        ("password", ""),
        ("from_email", "invalid"),
        ("from_name", "Name\r\nBcc: other@example.com"),
    ],
)
def test_malformed_or_unencrypted_accounts_are_refused(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        SmtpAccountSecret.model_validate({**account().model_dump(), field: value})


async def test_service_rechecks_scope_kind_and_grants_before_opening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    key = uuid4()
    sealed = seal_secret(account(), scope=VaultScope.organization(ctx.organization_id))
    row = OrganizationSecret(
        id=key,
        organization_id=ctx.organization_id,
        kind="smtp_account",
        name="Mailbox",
        sealed_secret=sealed.ciphertext,
        key_version=sealed.key_version,
    )
    get = AsyncMock(return_value=None)
    permitted = AsyncMock(return_value=True)
    monkeypatch.setattr(service.organization_secret_repo, "get", get)
    monkeypatch.setattr(service, "resolve_access", permitted)
    vault = service.OrganizationSecretService(MagicMock())
    assert await vault.smtp_email_service(ctx, key) is None
    assert get.await_args.kwargs["organization_id"] == ctx.organization_id
    get.return_value = row
    row.kind = "api_key"
    assert await vault.usable_smtp_account(ctx, key) is None
    row.kind = "smtp_account"
    permitted.return_value = False
    assert await vault.smtp_email_service(ctx, key) is None
    permitted.return_value = True
    mail = await vault.smtp_email_service(ctx, key)
    assert mail is not None
    assert mail.from_email == "ada@example.com" and mail.from_name is None
    assert isinstance(mail.provider, SMTPProvider)
    assert mail.provider.host == "smtp.example.com"
    assert mail.provider.use_tls is True
