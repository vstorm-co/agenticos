"""Real envelopes and PostgreSQL records retain browser ownership through rotation."""

import json
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.browser_sign_ins import SignIn
from app.commands import vault_rotate as sweep
from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.secret_kinds import (
    ApiKeySecret,
    BrowserLoginSecret,
    BrowserProfileSecret,
    seal_secret,
    unseal_kind,
)
from app.core.vault import VaultScope, seal, unseal
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.browser_sign_in import BrowserSignIn
from app.db.models.organization import OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import Visibility
from app.repositories import member as member_repo
from app.services.organization_secret import OrganizationSecretService
from tests.integration.test_personal_coding_accounts import context, organization, person
from tests.test_browser_credentials import PASSWORD, SEED, USERNAME, login

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_browser_record_and_metadata_are_private_to_one_member_and_organization(
    db: AsyncSession,
) -> None:
    owner, other = await person(db), await person(db)
    mine, elsewhere = await organization(db, owner), await organization(db, owner)
    db.add(OrganizationMember(organization_id=mine.id, user_id=other.id, role="owner"))
    await db.flush()
    service = OrganizationSecretService(db)
    row = await service.create(
        context(owner, mine),
        name="Private portal",
        value=login(),
        usage_scope="personal",
        visibility=Visibility.PRIVATE,
    )
    scope = VaultScope.browser_member(mine.id, owner.id)
    assert row.hint == "" and row.owner_user_id == owner.id
    assert (
        unseal_kind(
            row.sealed_secret, model=BrowserLoginSecret, scope=scope
        ).password.get_secret_value()
        == PASSWORD
    )
    for wrong_scope in (
        VaultScope.browser_member(mine.id, other.id),
        VaultScope.browser_member(elsewhere.id, owner.id),
        VaultScope.organization(mine.id),
        VaultScope.user(owner.id),
    ):
        with pytest.raises(BadRequestError):
            unseal_kind(row.sealed_secret, model=BrowserLoginSecret, scope=wrong_scope)
    listed = await service.list_secrets(context(owner, mine))
    assert len(listed) == 1 and listed[0].browser is not None
    assert listed[0].browser.allowed_origins == ["https://portal.example.test"]
    assert listed[0].browser.has_totp
    audit = list(
        (
            await db.execute(
                select(AppAdminAuditLog.details).where(AppAdminAuditLog.organization_id == mine.id)
            )
        ).scalars()
    )
    outward = listed[0].model_dump_json() + json.dumps(audit, default=str) + repr(row)
    assert not any(value in outward for value in (PASSWORD, USERNAME, SEED))
    for ctx in (context(other, mine), context(owner, elsewhere)):
        assert await service.list_secrets(ctx) == []
        with pytest.raises(AuthorizationError):
            await service.require_view(ctx, row.id)
        with pytest.raises(NotFoundError):
            await service.update(ctx, row.id, value=login(totp=False))
        with pytest.raises(NotFoundError):
            await service.delete(ctx, row.id)
    assert await service.resolve_for_bindings(context(owner, mine), [row.id]) == {}


async def test_replacement_rotates_authority_but_member_removal_refuses_further_access(
    db: AsyncSession,
) -> None:
    owner = await person(db)
    org = await organization(db, owner)
    ctx = context(owner, org)
    service = OrganizationSecretService(db)
    row = await service.create(
        ctx,
        name="Private portal",
        value=login(),
        usage_scope="personal",
        visibility=Visibility.PRIVATE,
    )
    previous_generation = row.authorization_generation
    replacement = BrowserLoginSecret(
        username="new synthetic user",
        password="new synthetic password",
        allowed_origins=("https://changed.example.test",),
    )
    await service.update(ctx, row.id, value=replacement)
    assert row.authorization_generation != previous_generation and row.hint == ""
    assert (
        unseal_kind(
            row.sealed_secret,
            model=BrowserLoginSecret,
            scope=VaultScope.browser_member(org.id, owner.id),
        )
        == replacement
    )
    metadata = (await service.list_secrets(ctx))[0].browser
    assert metadata is not None and not metadata.has_totp
    assert metadata.allowed_origins == ["https://changed.example.test"]
    membership = await member_repo.get(db, organization_id=org.id, user_id=owner.id)
    assert membership is not None
    await db.delete(membership)
    await db.flush()
    assert await service.list_secrets(ctx) == []
    with pytest.raises(NotFoundError):
        await service.update(ctx, row.id, value=login())
    with pytest.raises(AuthorizationError):
        await service.create(
            ctx,
            name="New portal",
            value=login(),
            usage_scope="personal",
            visibility=Visibility.PRIVATE,
        )


async def test_key_rotation_preserves_browser_and_technical_scopes(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_key, second_key = (
        "synthetic-vault-first-" + "a" * 32,
        "synthetic-vault-second-" + "b" * 32,
    )
    monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: first_key})
    owner = await person(db)
    org = await organization(db, owner)
    service = OrganizationSecretService(db)
    profile = BrowserProfileSecret(
        allowed_origins=("https://portal.example.test",),
        fields={"name": SecretStr("Synthetic private name"), "postal_code": SecretStr("123456")},
    )
    browser = await service.create(
        context(owner, org),
        name="Profile",
        value=profile,
        usage_scope="personal",
        visibility=Visibility.PRIVATE,
    )
    technical = await service.create(
        context(owner, org),
        name="Technical",
        value=ApiKeySecret(api_key="synthetic-technical-credential"),
    )
    # A malformed imported row must be reported without stopping other key rotations.
    bad = seal_secret(login(), scope=VaultScope.organization(org.id))
    db.add(
        OrganizationSecret(
            organization_id=org.id,
            kind="browser_login",
            name="Invalid scope",
            usage_scope="organization",
            visibility="org",
            purpose="custom",
            sealed_secret=bad.ciphertext,
            hint="",
            key_version=bad.key_version,
            created_by_user_id=owner.id,
        )
    )
    await db.flush()
    generations = browser.authorization_generation, technical.authorization_generation
    monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: first_key, 2: second_key})
    report = sweep.Report()
    spec = next(item for item in sweep.SEALED_TABLES if item.label == "organization_secrets")
    await sweep._rotate_table(db, spec, target=2, dry_run=False, report=report)
    await db.flush()
    assert report.rotated == 2 and len(report.failures) == 1
    assert "personal owner" in report.failures[0]
    assert browser.key_version == technical.key_version == 2
    assert generations == (browser.authorization_generation, technical.authorization_generation)
    assert (
        unseal_kind(
            browser.sealed_secret,
            model=BrowserProfileSecret,
            scope=VaultScope.browser_member(org.id, owner.id),
            key_version=2,
        )
        == profile
    )
    assert (
        unseal_kind(
            technical.sealed_secret,
            model=ApiKeySecret,
            scope=VaultScope.organization(org.id),
            key_version=2,
        ).api_key.get_secret_value()
        == "synthetic-technical-credential"
    )
    metadata = (await service.list_secrets(context(owner, org)))[0].browser
    assert metadata is not None and metadata.available_fields == ["name", "postal_code"]


async def test_password_deletion_preserves_the_existing_explicit_cookie_session(
    db: AsyncSession,
) -> None:
    owner = await person(db)
    org = await organization(db, owner)
    sign_in = SignIn(
        site="portal.example.test",
        origin="https://portal.example.test",
        cookies=[
            {
                "name": "session",
                "value": "synthetic-session-cookie",
                "domain": "portal.example.test",
            }
        ],
        local_storage={"session": "synthetic-existing-state"},
    )
    sealed = seal(sign_in.model_dump_json(), scope=VaultScope.user(owner.id))
    saved = BrowserSignIn(
        id=uuid4(),
        organization_id=org.id,
        user_id=owner.id,
        site=sign_in.site,
        sealed_state=sealed.ciphertext,
        secret_key_version=sealed.key_version,
    )
    db.add(saved)
    await db.flush()
    service = OrganizationSecretService(db)
    password = await service.create(
        context(owner, org),
        name="Separate password",
        value=login(),
        usage_scope="personal",
        visibility=Visibility.PRIVATE,
    )
    await service.delete(context(owner, org), password.id)
    retained = await db.get(BrowserSignIn, saved.id)
    assert retained is not None and retained.sealed_state == sealed.ciphertext
    assert (
        SignIn.model_validate_json(
            unseal(
                retained.sealed_state,
                scope=VaultScope.user(owner.id),
                key_version=retained.secret_key_version,
            )
        )
        == sign_in
    )
