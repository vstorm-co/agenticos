"""Browser credential types, private scope, generic-reader refusal and safe metadata."""

import base64
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from app.commands import vault_rotate
from app.core.browser_origins import browser_origin
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.core.secret_kinds import (
    ApiKeySecret,
    BrowserLoginSecret,
    BrowserProfileSecret,
    BrowserTotp,
    SecretKind,
    SecretRequirement,
    parse_storable_secret,
    seal_secret,
    unseal_kind,
    unseal_secret,
)
from app.core.secret_scopes import organization_secret_scope
from app.core.vault import VaultScope
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import Visibility
from app.schemas.secret import BrowserSecretMetadata, SecretCreate
from app.services import organization_secret as service_module
from app.services.organization_secret import OrganizationSecretService, SecretSharingGuard

pytestmark = [pytest.mark.anyio, pytest.mark.security]

USERNAME = "synthetic-browser-login-user"
PASSWORD = "synthetic-browser-login-password"
SEED = "JBSWY3DPEHPK3PXP"


def login(*, totp: bool = True) -> BrowserLoginSecret:
    return BrowserLoginSecret(
        username=SecretStr(USERNAME),
        password=SecretStr(PASSWORD),
        allowed_origins=("https://portal.example.test",),
        totp=BrowserTotp(seed=SecretStr(SEED)) if totp else None,
    )


def record() -> OrganizationSecret:
    organization_id, owner = uuid4(), uuid4()
    sealed = seal_secret(login(), scope=VaultScope.browser_member(organization_id, owner))
    return OrganizationSecret(
        id=uuid4(),
        organization_id=organization_id,
        owner_user_id=owner,
        created_by_user_id=owner,
        kind="browser_login",
        name="Private portal",
        purpose="custom",
        usage_scope="personal",
        visibility="private",
        authorization_generation=uuid4(),
        sealed_secret=sealed.ciphertext,
        hint=sealed.hint,
        key_version=sealed.key_version,
        created_at=datetime.now(UTC),
    )


def context(row: OrganizationSecret, *, other: bool = False, key: bool = False) -> AuthContext:
    return AuthContext(
        user_id=uuid4() if other else row.owner_user_id,
        organization_id=row.organization_id,
        role="owner",
        api_key_id=uuid4() if key else None,
    )


@pytest.mark.parametrize(
    ("submitted", "canonical"),
    [
        ("HTTPS://EXAMPLE.COM:443/", "https://example.com"),
        ("https://portal.example.test:8443", "https://portal.example.test:8443"),
        ("https://b\u00fccher.example", "https://xn--bcher-kva.example"),
        ("https://8.8.8.8", "https://8.8.8.8"),
        ("https://[2606:4700:4700:0:0:0:0:1111]", "https://[2606:4700:4700::1111]"),
    ],
)
def test_browser_origins_have_one_exact_canonical_form(submitted: str, canonical: str) -> None:
    assert browser_origin(submitted) == canonical


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "https://" + "x" * 2050,
        " https://example.com",
        "https://example.com\n",
        "https://example.com/\x00",
        "http://example.com",
        "file:///etc/passwd",
        "https:///",
        "https://example.com/login",
        "https://example.com?",
        "https://example.com#",
        "https://user:synthetic-password@example.com",
        "https://*.example.com",
        "https://example.com\\other",
        "https://example.com:0",
        "https://example.com:65536",
        "https://example.com:invalid",
        "https://[",
        "https://localhost",
        "https://site.localhost",
        "https://site.local",
        "https://site.internal",
        "https://127.0.0.1",
        "https://10.0.0.1",
        "https://169.254.169.254",
        "https://[::1]",
        "https://[fc00::1]",
        "https://127.1",
        "https://0x7f000001",
        "https://-bad.example",
        "https://bad_.example",
        "https://%65xample.com",
        "https://" + "a" * 64 + ".example",
        "https://" + ".".join(["a" * 63] * 4),
    ],
)
def test_private_or_ambiguous_destinations_are_refused_without_echoing_input(origin: str) -> None:
    with pytest.raises(ValueError, match="exact public HTTPS origin") as refused:
        browser_origin(origin)
    assert "synthetic-password" not in str(refused.value)


def test_browser_payloads_hide_values_and_accept_short_passwords_without_hints() -> None:
    value = login()
    assert not any(secret in repr(value) for secret in (USERNAME, PASSWORD, SEED))
    assert value.hint == ""
    short = BrowserLoginSecret(username="u", password="p", allowed_origins=("https://example.com",))
    assert short.password.get_secret_value() == "p" and short.hint == ""
    deduped = BrowserLoginSecret(
        username="u",
        password="p",
        allowed_origins=(
            "https://EXAMPLE.COM:443/",
            "https://example.com",
        ),
    )
    assert deduped.allowed_origins == ("https://example.com",)
    assert BrowserTotp(seed=SecretStr(SEED.lower() + "====")).seed.get_secret_value() == SEED


@pytest.mark.parametrize(
    "seed",
    [
        "invalid-synthetic-seed",
        base64.b32encode(b"12345678").decode(),
        base64.b32encode(b"x" * 129).decode(),
    ],
)
def test_invalid_totp_seeds_are_safe_to_report(seed: str) -> None:
    payload = json.loads(login().model_dump_json())
    payload["totp"]["seed"] = seed
    with pytest.raises(BadRequestError) as refused:
        parse_storable_secret("browser_login", json.dumps(payload))
    assert seed not in str(refused.value) and PASSWORD not in str(refused.value)


@pytest.mark.parametrize(
    "change",
    [
        {"password": ""},
        {"allowed_origins": []},
        {"extra": PASSWORD},
        {"totp": {"seed": SEED, "algorithm": "MD5"}},
        {"totp": {"seed": SEED, "digits": 7}},
        {"totp": {"seed": SEED, "period_seconds": 15}},
    ],
)
def test_browser_login_replacement_requires_a_complete_valid_payload(
    change: dict[str, object],
) -> None:
    payload = json.loads(login().model_dump_json()) | change
    with pytest.raises(BadRequestError) as refused:
        parse_storable_secret("browser_login", json.dumps(payload))
    assert PASSWORD not in str(refused.value) and SEED not in str(refused.value)
    del payload["password"]
    with pytest.raises(ValidationError):
        SecretCreate(name="Missing password", value=payload)


def test_metadata_exposes_only_allowed_origins_and_available_field_names() -> None:
    for value in (
        login(),
        login(totp=False),
        BrowserProfileSecret(
            allowed_origins=("https://example.com",),
            fields={
                "name": SecretStr("Synthetic private person"),
                "email": SecretStr("private@example.test"),
            },
        ),
    ):
        metadata = BrowserSecretMetadata.from_secret(value)
        encoded = metadata.model_dump_json()
        assert not any(
            secret in encoded
            for secret in (
                USERNAME,
                PASSWORD,
                SEED,
                "Synthetic private person",
                "private@example.test",
            )
        )
        assert metadata.allowed_origins == list(value.allowed_origins)
        assert value.hint == ""
    assert BrowserSecretMetadata.from_secret(login()).has_totp
    with pytest.raises(ValidationError):
        BrowserProfileSecret(
            allowed_origins=("https://example.com",), fields={"credit_card": "private"}
        )
    with pytest.raises(ValidationError):
        BrowserProfileSecret(allowed_origins=("https://example.com",), fields={})


def test_browser_form_defaults_are_personal_without_changing_technical_defaults() -> None:
    request = SecretCreate(name="Portal", value=login())
    assert request.usage_scope == "personal" and request.visibility == "private"
    explicit = SecretCreate(
        name="Portal", value=login(), usage_scope="organization", visibility="org"
    )
    assert explicit.usage_scope == "organization" and explicit.visibility == "org"
    technical = SecretCreate(
        name="Technical", value=ApiKeySecret(api_key="synthetic-technical-key")
    )
    assert technical.usage_scope == "organization" and technical.visibility == "org"


def test_browser_scope_is_shared_by_storage_and_rotation_and_generic_readers_refuse_it() -> None:
    row = record()
    scope = organization_secret_scope(
        organization_id=row.organization_id,
        kind=row.kind,
        usage_scope=row.usage_scope,
        owner_user_id=row.owner_user_id,
    )
    spec = next(item for item in vault_rotate.SEALED_TABLES if item.label == "organization_secrets")
    assert (
        spec.scope(row)
        == scope
        == VaultScope.browser_member(row.organization_id, row.owner_user_id)
    )
    assert (
        unseal_kind(
            row.sealed_secret, model=BrowserLoginSecret, scope=scope
        ).password.get_secret_value()
        == PASSWORD
    )
    with pytest.raises(BadRequestError, match="confirmed browser writer"):
        unseal_secret(row.sealed_secret, kind=SecretKind.BROWSER_LOGIN, scope=scope)
    assert organization_secret_scope(
        organization_id=row.organization_id,
        kind="api_key",
        usage_scope="organization",
        owner_user_id=None,
    ) == VaultScope.organization(row.organization_id)
    assert organization_secret_scope(
        organization_id=row.organization_id,
        kind=row.kind,
        usage_scope="organization",
        owner_user_id=row.owner_user_id,
    ) == VaultScope.organization(row.organization_id)
    for usage_scope, owner in (("unknown", row.owner_user_id), ("personal", None)):
        with pytest.raises(BadRequestError):
            organization_secret_scope(
                organization_id=row.organization_id,
                kind=row.kind,
                usage_scope=usage_scope,
                owner_user_id=owner,
            )


def test_generic_capabilities_cannot_request_browser_credentials() -> None:
    for options in (
        {"kind": SecretKind.BROWSER_LOGIN},
        {"kind": SecretKind.API_KEY, "also_accepts": (SecretKind.BROWSER_PROFILE,)},
    ):
        with pytest.raises(ValidationError, match="explicit browser binding"):
            SecretRequirement(description="Synthetic request", **options)


@pytest.mark.parametrize(
    "case", ["other_owner", "api_key", "inactive", "organization", "visibility"]
)
async def test_even_an_administrator_cannot_read_or_rotate_another_browser_record(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = record()
    ctx = context(row, other=case == "other_owner", key=case == "api_key")
    if case == "organization":
        row.usage_scope = "organization"
    if case == "visibility":
        row.visibility = "org"
    monkeypatch.setattr(service_module.organization_secret_repo, "get", AsyncMock(return_value=row))
    monkeypatch.setattr(
        service_module.member_repo,
        "get_active",
        AsyncMock(return_value=None if case == "inactive" else object()),
    )
    monkeypatch.setattr(service_module, "resolve_access", AsyncMock(return_value=True))
    monkeypatch.setattr(
        service_module.browser_credential_repo, "policy_exists", AsyncMock(return_value=False)
    )
    service = OrganizationSecretService(AsyncMock())
    with pytest.raises(NotFoundError):
        await service.update(ctx, row.id, value=login(totp=False))
    with pytest.raises(AuthorizationError):
        await service.require_view(ctx, row.id)


@pytest.mark.parametrize("case", ["api_key", "inactive", "organization", "visibility"])
async def test_browser_creation_refuses_missing_owner_or_broader_scope(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = record()
    monkeypatch.setattr(
        service_module.member_repo,
        "get_active",
        AsyncMock(return_value=None if case == "inactive" else object()),
    )
    create = AsyncMock()
    monkeypatch.setattr(service_module.organization_secret_repo, "create", create)
    with pytest.raises((AuthorizationError, BadRequestError)):
        await OrganizationSecretService(AsyncMock()).create(
            context(row, key=case == "api_key"),
            name="Private portal",
            value=login(),
            usage_scope="organization" if case == "organization" else "personal",
            visibility=Visibility.ORG if case == "visibility" else Visibility.PRIVATE,
        )
    create.assert_not_awaited()


async def test_generic_binding_and_transport_readers_cannot_borrow_browser_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = record()
    monkeypatch.setattr(service_module.member_repo, "get_active", AsyncMock(return_value=object()))
    monkeypatch.setattr(service_module.organization_secret_repo, "get", AsyncMock(return_value=row))
    monkeypatch.setattr(
        service_module.organization_secret_repo, "get_many", AsyncMock(return_value={row.id: row})
    )
    monkeypatch.setattr(service_module, "resolve_access", AsyncMock(return_value=True))
    opened = Mock()
    monkeypatch.setattr(service_module, "unseal_secret", opened)
    service = OrganizationSecretService(AsyncMock())
    with pytest.raises(BadRequestError, match="confirmed browser writer"):
        await service.get_usable(context(row), row.id, kind=SecretKind.BROWSER_LOGIN)
    row.usage_scope = "organization"  # A malformed row must not make a browser kind injectable.
    assert await service.resolve_for_bindings(context(row), [row.id]) == {}
    opened.assert_not_called()


async def test_generic_sharing_cannot_adopt_a_browser_credential() -> None:
    row = record()
    owner = row.owner_user_id
    with pytest.raises(BadRequestError, match="owner cannot be changed"):
        await SecretSharingGuard().adopt(AsyncMock(), context(row, other=True), row)
    assert row.owner_user_id == owner


@pytest.mark.parametrize("removed", [True, False])
async def test_browser_rotation_rechecks_access_after_obtaining_the_row_lock(
    monkeypatch: pytest.MonkeyPatch,
    removed: bool,
) -> None:
    row = record()
    ctx = context(row)
    locked = None if removed else record()
    monkeypatch.setattr(service_module.organization_secret_repo, "get", AsyncMock(return_value=row))
    monkeypatch.setattr(service_module.member_repo, "get_active", AsyncMock(return_value=object()))
    monkeypatch.setattr(service_module, "resolve_access", AsyncMock(return_value=True))
    monkeypatch.setattr(
        service_module.browser_credential_repo, "policy_exists", AsyncMock(return_value=False)
    )
    lookup = AsyncMock(return_value=locked)
    monkeypatch.setattr(service_module.browser_credential_repo, "secret", lookup)
    update = AsyncMock()
    monkeypatch.setattr(service_module.organization_secret_repo, "update", update)
    with pytest.raises(NotFoundError, match="Browser credential not found"):
        await OrganizationSecretService(AsyncMock()).update(ctx, row.id, name="Renamed portal")
    assert lookup.await_args.kwargs == {"locked": True}
    update.assert_not_awaited()
