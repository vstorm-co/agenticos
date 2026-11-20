"""User sealing, tenant isolation and renewable grants against real PostgreSQL."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4
from zipfile import ZipFile

import anyio
import pytest
from pydantic import SecretStr
from pydantic_ai.models.test import TestModel
from pydantic_ai.providers.openai_codex import OpenAICodexCredentials
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from pydantic_ai.workspaces import Workspace
from pydantic_ai.workspaces.local import LocalWorkspaceBackend
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.agents.audience import acting_impersonated
from app.agents.capabilities.sandbox import SandboxConfig
from app.agents.capabilities.sandbox._identity import WorkspaceIdentity
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, OpenAICodexSecret, SecretKind, unseal_secret
from app.core.vault import VaultScope
from app.db.models.coding_account import CodingAccount
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_workspace as workspace_repo
from app.repositories import coding_account as account_repo
from app.schemas.coding_account import CodingAccountCreate, CodingAccountRead, CodingAccountUpdate
from app.services import personal_codex as codex_module
from app.services import personal_coding as coding_module
from app.services.coding_accounts import CodingAccountService, account_owner
from app.services.personal_codex import PersonalCodexCredentials
from app.services.personal_coding import PersonalCodingSessionFactory
from app.services.personal_data import PersonalDataService
from app.services.sandbox_workspace import OpenWorkspace, WorkspaceFlushFailure
from tests.test_personal_coding import MemoryRedis

pytestmark = [pytest.mark.anyio, pytest.mark.security]
KEY = "sk-personal-test-private-value"


@pytest.mark.parametrize("change", ["deleted", "disabled", "rotated"])
async def test_revocation_between_admission_and_account_lock_never_opens_a_workspace(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    @asynccontextmanager
    async def connection() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db
            await db.commit()

    async with connection() as db:
        owner = await person(db)
        org = await organization(db, owner)
        auth = context(owner, org)
        saved = await CodingAccountService(db).create(auth, request(enabled=True))
        account = await account_repo.get(
            db, organization_id=org.id, user_id=owner.id, account_id=saved.id
        )
        assert account is not None
    async with connection() as db:
        changed = await db.get(CodingAccount, account.id)
        assert changed is not None
        if change == "deleted":
            await db.delete(changed)
        elif change == "disabled":
            changed.enabled = False
        else:
            changed.generation = uuid4()

    monkeypatch.setattr(coding_module, "get_db_context", connection)
    monkeypatch.setattr(PersonalCodingSessionFactory, "_active", AsyncMock(return_value=True))
    workspace_service = MagicMock()
    monkeypatch.setattr(coding_module, "SandboxWorkspaceService", workspace_service)
    factory = PersonalCodingSessionFactory(
        auth, AgentSpec(name="Test"), SandboxConfig(backend="service"), uuid4(), redis=MemoryRedis()
    )
    run = RunContext(
        deps=AgentDeps(organization_id=org.id, user_id=str(owner.id), conversation_id=uuid4()),
        model=TestModel(),
        usage=RunUsage(),
        prompt="Task",
    )
    with pytest.raises(
        AuthorizationError, match="Permission to use this coding account was revoked"
    ):
        async with factory._isolated(run, account, "claude_code"):
            pytest.fail("Revoked credentials must not reach a workspace")
    workspace_service.assert_not_called()


async def person(db: AsyncSession) -> User:
    row = User(email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(row)
    await db.flush()
    return row


async def organization(db: AsyncSession, owner: User) -> Organization:
    row = Organization(name="Coding test", slug=uuid4().hex, created_by_user_id=owner.id)
    db.add(row)
    await db.flush()
    db.add(OrganizationMember(organization_id=row.id, user_id=owner.id, role="owner"))
    await db.flush()
    return row


def context(user: User, org: Organization) -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=org.id, role="owner")


def request(*, enabled: bool = False) -> CodingAccountCreate:
    return CodingAccountCreate(
        harness="claude_code", label="My Claude", api_key=SecretStr(KEY), enabled=enabled
    )


async def test_accounts_are_user_sealed_and_metadata_never_contains_credentials(
    engine: AsyncEngine,
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db:
        user = await person(db)
        org = await organization(db, user)
        row = await CodingAccountService(db).create(context(user, org), request())
        assert row.enabled is False
        assert KEY not in row.sealed_secret and KEY not in repr(row)
        secret = unseal_secret(
            row.sealed_secret,
            kind=SecretKind.API_KEY,
            scope=VaultScope.user(user.id),
            key_version=row.key_version,
        )
        assert isinstance(secret, ApiKeySecret) and secret.api_key.get_secret_value() == KEY
        with pytest.raises(BadRequestError):
            unseal_secret(
                row.sealed_secret,
                kind=SecretKind.API_KEY,
                scope=VaultScope.organization(org.id),
                key_version=row.key_version,
            )
        metadata = CodingAccountRead.model_validate(row).model_dump_json()
        assert (
            KEY not in metadata
            and "sealed_secret" not in metadata
            and "key_version" not in metadata
        )
        assert len(await CodingAccountService(db).mine(context(user, org))) == 1
        exported = await PersonalDataService(db).export(user.id, actor_user_id=user.id)
        assert len(exported.coding_accounts) == 1
        assert exported.coding_accounts[0]["label"] == "My Claude"
        assert KEY not in exported.model_dump_json()
        assert "sealed_secret" not in exported.coding_accounts[0]


async def test_an_administrator_or_another_tenant_cannot_use_or_disconnect_the_account(
    engine: AsyncEngine,
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db:
        owner, other = await person(db), await person(db)
        org = await organization(db, owner)
        elsewhere = await organization(db, owner)
        service = CodingAccountService(db)
        row = await service.create(context(owner, org), request(enabled=True))
        for ctx in (context(other, org), context(owner, elsewhere)):
            assert await service.mine(ctx) == []
            with pytest.raises(NotFoundError):
                await service.own(ctx, row.id)
            with pytest.raises(NotFoundError):
                await service.disconnect(ctx, row.id)
        assert (
            await account_repo.get(
                db, organization_id=org.id, user_id=owner.id, harness="claude_code"
            )
            is row
        )


async def test_consent_is_revision_checked_and_reconnection_is_explicit(
    engine: AsyncEngine,
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db:
        user = await person(db)
        org = await organization(db, user)
        ctx = context(user, org)
        service = CodingAccountService(db)
        row = await service.create(ctx, request())
        original = row.generation
        with pytest.raises(AlreadyExistsError):
            await service.create(ctx, request(enabled=True))
        await service.update(ctx, row.id, CodingAccountUpdate(generation=original, enabled=True))
        assert row.enabled and row.generation != original
        with pytest.raises(ConflictError):
            await service.update(
                ctx, row.id, CodingAccountUpdate(generation=original, enabled=False)
            )
        await service.disconnect(ctx, row.id)
        assert await service.mine(ctx) == []


@pytest.mark.parametrize("kind", ["api_key", "key_scope", "anonymous", "impersonated"])
async def test_non_person_authorities_cannot_borrow_a_personal_account(kind: str) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    if kind == "api_key":
        ctx = replace(ctx, api_key_id=uuid4())
    elif kind == "key_scope":
        ctx = replace(ctx, key_scopes=())
    elif kind == "anonymous":
        ctx = replace(ctx, user_id=None)
    with acting_impersonated(kind == "impersonated"), pytest.raises(AuthorizationError):
        account_owner(ctx)


async def test_codex_refresh_preserves_owner_identity_and_checks_the_written_pair(
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def connection() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db
            await db.commit()

    monkeypatch.setattr(codex_module, "get_db_context", connection)
    async with connection() as db:
        user = await person(db)
        org = await organization(db, user)
        row = await CodingAccountService(db).save(
            context(user, org),
            harness="codex",
            label="My ChatGPT",
            secret=OpenAICodexSecret(
                access_token="access-token-original",
                refresh_token="refresh-token-original",
                account_id="account-1",
            ),
            enabled=True,
        )
        identifiers: tuple[UUID, UUID, UUID, UUID] = org.id, user.id, row.id, row.generation
    source = PersonalCodexCredentials(*identifiers)
    held = await source.load()
    assert await source.visible_to(identifiers[1])
    assert not await source.visible_to(uuid4())
    other = OpenAICodexCredentials(
        access_token="other-access-token",
        refresh_token="other-refresh-token",
        account_id="account-2",
    )
    assert not await source.swap(held, other)
    rotated = OpenAICodexCredentials(
        access_token="rotated-access-token",
        refresh_token="rotated-refresh-token",
        account_id="account-1",
    )
    assert await source.swap(held, rotated)
    assert not await source.swap(held, rotated)
    assert (await source.load()).refresh_token == rotated.refresh_token
    async with connection() as db:
        account = await db.get(CodingAccount, identifiers[2])
        assert account is not None
        account.enabled = False
    with pytest.raises(AuthorizationError):
        await source.load()
    assert not await source.swap(rotated, held)


@pytest.mark.parametrize(
    "ending",
    [
        "success",
        "failure",
        "revoke",
        "share",
        "share_before_publish",
        "revoked_at_publication",
        "conversation_gone_at_publication",
        "revoked_after_lock",
        "cancel",
        "codex",
        "cleanup",
        "failure_cleanup",
        "missing_workspace",
        "missing_row_id",
        "missing_row",
        "wrong_owner",
        "wrong_account",
        "expired",
        "partial_source",
        "wait",
    ],
)
async def test_private_task_lifecycle_copies_results_and_always_closes(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    @asynccontextmanager
    async def connection() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db
            await db.commit()

    monkeypatch.setattr(coding_module, "get_db_context", connection)
    shared, isolated = tmp_path / "shared", tmp_path / "isolated"
    shared.mkdir()
    isolated.mkdir()
    (shared / "app.py").write_text("old")
    parent = Workspace(LocalWorkspaceBackend(shared))
    private = Workspace(LocalWorkspaceBackend(isolated))
    opened = OpenWorkspace(private, "service", "user", "private-task", None)
    closed: list[OpenWorkspace] = []
    identifiers: list[UUID] = []

    class Workspaces:
        def __init__(self, db: AsyncSession) -> None:
            self.db = db

        async def discard_personal_coding(self, ctx, row) -> None:
            await workspace_repo.delete(self.db, workspace=row)

        async def open(
            self,
            spec: AgentSpec,
            *,
            ctx: AuthContext,
            identity: WorkspaceIdentity,
            scope_override: str,
        ) -> OpenWorkspace | None:
            assert scope_override == "user" and identity.project_id is None
            assert identity.namespace is not None
            assert identity.run_id is not None and identity.run_id != run.deps.run_id
            identifiers.append(identity.run_id)
            if ending == "missing_workspace":
                return None
            row = await workspace_repo.create(
                self.db,
                organization_id=ctx.organization_id,
                agent_id=None,
                scope="user",
                scope_key=str(identity.namespace),
                backend="service",
                owner_ref=str(ctx.user_id),
            )
            opened.row_id = None if ending == "missing_row_id" else row.id
            if ending == "missing_row":
                await workspace_repo.delete(self.db, workspace=row)
            elif ending == "wrong_owner":
                row.owner_ref = str(uuid4())
            elif ending == "wrong_account":
                other = await CodingAccountService(self.db).save(
                    ctx,
                    harness="codex",
                    label="Other",
                    secret=ApiKeySecret(api_key=SecretStr(KEY)),
                    enabled=True,
                )
                row.coding_account_id = other.id
                row.conversation_id = run.deps.conversation_id
            elif ending == "expired":
                row.coding_source_revision = "a" * 64
            elif ending == "partial_source":
                row.session_id = "interrupted-initial-copy"
            await self.db.flush()
            return opened

        async def close(self, workspace: OpenWorkspace) -> WorkspaceFlushFailure | None:
            closed.append(workspace)
            if ending in ("cleanup", "failure_cleanup"):
                return WorkspaceFlushFailure(ExternalServiceError(message="Cleanup failed"))
            return None

    monkeypatch.setattr(coding_module, "SandboxWorkspaceService", Workspaces)
    async with connection() as db:
        owner = await person(db)
        org = await organization(db, owner)
        auth = context(owner, org)
        account = (
            await CodingAccountService(db).save(
                auth,
                harness="codex",
                label="My Codex",
                secret=OpenAICodexSecret(
                    access_token="my-access", refresh_token="my-refresh", account_id="my-account"
                ),
                enabled=True,
            )
            if ending == "codex"
            else await CodingAccountService(db).create(auth, request(enabled=True))
        )
        account_id = account.id
    monkeypatch.setattr(codex_module, "get_db_context", connection)
    from app.db.models.conversation import Conversation

    async with connection() as db:
        conversation = Conversation(organization_id=org.id, user_id=owner.id, title="Private task")
        db.add(conversation)
        await db.flush()
    run = RunContext(
        deps=AgentDeps(
            organization_id=org.id,
            user_id=str(owner.id),
            conversation_id=conversation.id,
            run_id=uuid4(),
        ),
        model=TestModel(),
        usage=RunUsage(),
        prompt="Task",
        workspace=parent,
    )
    redis = MemoryRedis()
    factory = PersonalCodingSessionFactory(
        auth,
        AgentSpec(name="Test"),
        SandboxConfig(backend="service"),
        uuid4(),
        redis=redis,
    )

    if ending in {
        "revoked_at_publication",
        "conversation_gone_at_publication",
        "revoked_after_lock",
    }:
        from unittest.mock import AsyncMock

        if ending == "conversation_gone_at_publication":
            monkeypatch.setattr(
                coding_module.conversation_share_repo,
                "lock_private_publication",
                AsyncMock(return_value=False),
            )
        else:
            original_active_in = type(factory)._active_in

            async def active_in(self, db, *args, lock=False):
                if lock and ending == "revoked_at_publication":
                    return False
                result = await original_active_in(self, db, *args, lock=lock)
                if lock and ending == "revoked_after_lock":
                    monkeypatch.setattr(type(factory), "_active", AsyncMock(return_value=False))
                return result

            monkeypatch.setattr(type(factory), "_active_in", active_in)

    async def execute() -> str:
        async with factory.session(
            run, harness="codex" if ending == "codex" else "claude_code", timeout_seconds=60
        ) as task:
            assert task.workspace is private
            if ending == "codex":
                assert task.api_key is None and task.sign_in is not None
                assert (await task.sign_in(org.id).load()).account_id == "my-account"
            else:
                assert task.api_key is not None and task.api_key.get_secret_value() == KEY
            assert (isolated / "app.py").read_text() == "old"
            (isolated / "app.py").write_text("new")
            if ending in ("failure", "failure_cleanup"):
                raise RuntimeError("harness failed")
            if ending == "revoke":
                async with connection() as db:
                    row = await db.get(CodingAccount, account_id)
                    assert row is not None
                    row.enabled = False
                with anyio.fail_after(5):
                    await anyio.sleep_forever()
            if ending in ("share", "share_before_publish"):
                from app.db.models.conversation_share import ConversationShare

                async with connection() as db:
                    collaborator = await person(db)
                    db.add(
                        OrganizationMember(
                            organization_id=org.id, user_id=collaborator.id, role="member"
                        )
                    )
                    await db.flush()
                    db.add(
                        ConversationShare(
                            conversation_id=run.deps.conversation_id,
                            shared_with=collaborator.id,
                            shared_by=owner.id,
                            permission="edit",
                        )
                    )
                if ending == "share":
                    with anyio.fail_after(5):
                        await anyio.sleep_forever()
            if ending == "wait":
                await anyio.sleep(2.1)
            if ending == "cancel":
                scope.cancel()
                await anyio.lowlevel.checkpoint()
            return task.result_archive

    archive_path = ""
    with anyio.CancelScope() as scope:
        if ending in (
            "failure",
            "revoke",
            "share",
            "share_before_publish",
            "revoked_at_publication",
            "conversation_gone_at_publication",
            "revoked_after_lock",
            "cleanup",
            "failure_cleanup",
            "missing_workspace",
            "missing_row_id",
            "missing_row",
            "wrong_owner",
            "wrong_account",
            "expired",
            "partial_source",
        ):
            error = (
                AuthorizationError
                if ending
                in (
                    "revoke",
                    "share",
                    "share_before_publish",
                    "revoked_at_publication",
                    "conversation_gone_at_publication",
                    "revoked_after_lock",
                )
                else ExternalServiceError
                if ending == "cleanup"
                else BadRequestError
                if ending in ("expired", "partial_source")
                else RuntimeError
            )
            with pytest.raises(error):
                await execute()
        else:
            archive_path = await execute()
    assert closed == ([] if ending == "missing_workspace" else [opened])
    assert not redis.values and len(identifiers) == 1
    assert (shared / "app.py").read_text() == "old"
    if ending in ("success", "codex", "wait"):
        with ZipFile(BytesIO(await parent.read_bytes(archive_path))) as archive:
            assert archive.read("app.py") == b"new"
    elif ending != "cleanup":
        assert not (shared / "coding-results").exists()


async def test_task_admission_and_live_project_authority(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    @asynccontextmanager
    async def connection() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db
            await db.commit()

    monkeypatch.setattr(coding_module, "get_db_context", connection)
    async with connection() as db:
        owner = await person(db)
        org = await organization(db, owner)
        auth = context(owner, org)
    factory = PersonalCodingSessionFactory(
        auth, AgentSpec(name="Test"), SandboxConfig(backend="service"), uuid4(), redis=MemoryRedis()
    )
    run = RunContext(
        deps=AgentDeps(organization_id=org.id, user_id=str(owner.id), conversation_id=uuid4()),
        model=TestModel(),
        usage=RunUsage(),
        prompt="Task",
    )
    with pytest.raises(BadRequestError):
        await factory._account("claude_code")
    assert not await factory._active(uuid4(), uuid4())
    with pytest.raises(AuthorizationError):
        async with factory.session(
            replace(run, deps=replace(run.deps, user_id=str(uuid4()))),
            harness="claude_code",
            timeout_seconds=1,
        ):
            pytest.fail("Foreign user admitted")
    with pytest.raises(BadRequestError):
        async with replace(factory, config=SandboxConfig(backend="state")).session(
            run, harness="claude_code", timeout_seconds=1
        ):
            pytest.fail("No server admitted")
    async with connection() as db:
        row = await CodingAccountService(db).create(auth, request(enabled=True))
        identifiers = row.id, row.generation
    project = replace(factory, project_id=uuid4())
    guard = AsyncMock(return_value=None)
    monkeypatch.setattr(coding_module, "project_for_workspace", guard)
    assert await project._active(*identifiers)
    guard.side_effect = AuthorizationError(message="Project access revoked")
    assert not await project._active(*identifiers)
    assert not await replace(factory, ctx=replace(auth, user_id=uuid4()))._active(*identifiers)
    stale = await factory._account("claude_code")
    async with connection() as db:
        account = await db.get(CodingAccount, stale.id)
        assert account is not None
        account.enabled = False
    with pytest.raises(AuthorizationError):
        async with factory._isolated(run, stale, "claude_code"):
            pytest.fail("Revoked account admitted")


async def test_unrelated_integrity_failures_are_not_reported_as_duplicate_accounts(
    engine: AsyncEngine,
) -> None:
    from sqlalchemy.exc import IntegrityError

    async with AsyncSession(engine, expire_on_commit=False) as db:
        with pytest.raises(IntegrityError):
            await CodingAccountService(db).create(
                AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member"), request()
            )


@pytest.mark.parametrize("stored_kind", ["api_key", "openai_codex"])
async def test_codex_refuses_an_invalid_stored_credential_variant(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, stored_kind: str
) -> None:
    @asynccontextmanager
    async def connection() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db
            await db.commit()

    monkeypatch.setattr(codex_module, "get_db_context", connection)
    async with connection() as db:
        owner = await person(db)
        org = await organization(db, owner)
        row = await CodingAccountService(db).create(
            context(owner, org), request().model_copy(update={"harness": "codex", "enabled": True})
        )
        row.secret_kind = stored_kind
        source = PersonalCodexCredentials(org.id, owner.id, row.id, row.generation)
    monkeypatch.setattr(
        codex_module, "unseal_secret", lambda *args, **kwargs: ApiKeySecret(api_key=KEY)
    )
    pair = OpenAICodexCredentials(
        access_token="access-value", refresh_token="refresh-value", account_id="account"
    )
    with pytest.raises(TypeError):
        await source.load()
    with pytest.raises(TypeError):
        await source.swap(pair, pair)


async def test_a_private_task_refuses_a_wrong_harness_or_non_coding_credential(
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.secret_kinds import NoSecret

    @asynccontextmanager
    async def connection() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db
            await db.commit()

    monkeypatch.setattr(coding_module, "get_db_context", connection)
    async with connection() as db:
        owner = await person(db)
        org = await organization(db, owner)
        auth = context(owner, org)
        row = await CodingAccountService(db).save(
            auth,
            harness="codex",
            label="ChatGPT",
            secret=OpenAICodexSecret(
                access_token="access-value", refresh_token="refresh-value", account_id="account"
            ),
            enabled=True,
        )
    factory = PersonalCodingSessionFactory(
        auth, AgentSpec(name="Test"), SandboxConfig(backend="service"), uuid4()
    )
    run = RunContext(
        deps=AgentDeps(organization_id=org.id, user_id=str(owner.id), conversation_id=uuid4()),
        model=TestModel(),
        usage=RunUsage(),
        prompt="Task",
    )
    with pytest.raises(BadRequestError, match="only run Codex"):
        async with factory._isolated(run, row, "claude_code"):
            pytest.fail("Wrong harness admitted")
    monkeypatch.setattr(coding_module, "unseal_secret", lambda *args, **kwargs: NoSecret())
    with pytest.raises(TypeError):
        async with factory._isolated(run, row, "codex"):
            pytest.fail("Non-coding credential admitted")


async def test_membership_teardown_removes_coding_consent_without_affecting_other_accounts(
    db: AsyncSession,
) -> None:
    from sqlalchemy import select

    from app.services.member import end_membership

    owner, other = await person(db), await person(db)
    org, elsewhere = await organization(db, owner), await organization(db, owner)
    db.add(OrganizationMember(organization_id=org.id, user_id=other.id, role="builder"))
    await db.flush()
    service = CodingAccountService(db)
    previous = await service.create(context(owner, org), request(enabled=True))
    other_account = await service.create(context(other, org), request(enabled=True))
    elsewhere_account = await service.create(context(owner, elsewhere), request(enabled=True))
    membership = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org.id, OrganizationMember.user_id == owner.id
        )
    )
    previous_id = previous.id
    await end_membership(db, membership)
    assert (
        await account_repo.get(db, organization_id=org.id, user_id=owner.id, account_id=previous_id)
        is None
    )
    assert (
        await account_repo.get(
            db, organization_id=org.id, user_id=other.id, account_id=other_account.id
        )
        is not None
    )
    assert (
        await account_repo.get(
            db, organization_id=elsewhere.id, user_id=owner.id, account_id=elsewhere_account.id
        )
        is not None
    )
    db.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner"))
    await db.flush()
    assert await service.mine(context(owner, org)) == []
    with pytest.raises(NotFoundError):
        await service.own(context(owner, org), previous_id)


@pytest.mark.parametrize("source", ["project", "agent", "channel", "conversation"])
async def test_factory_refuses_collaborator_sources_before_loading_a_personal_account(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    from unittest.mock import AsyncMock

    from app.db.models.conversation import Conversation
    from app.db.models.conversation_share import ConversationShare

    @asynccontextmanager
    async def connection() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db
            await db.commit()

    monkeypatch.setattr(coding_module, "get_db_context", connection)
    async with connection() as db:
        owner, collaborator = await person(db), await person(db)
        org = await organization(db, owner)
        db.add(OrganizationMember(organization_id=org.id, user_id=collaborator.id, role="member"))
        chat = Conversation(organization_id=org.id, user_id=owner.id, title="Source")
        db.add(chat)
        await db.flush()
        if source == "conversation":
            db.add(
                ConversationShare(
                    conversation_id=chat.id,
                    shared_with=collaborator.id,
                    shared_by=owner.id,
                    permission="edit",
                )
            )
    factory = PersonalCodingSessionFactory(
        context(owner, org),
        AgentSpec(name="Test"),
        SandboxConfig(
            backend="service",
            session_scope=source if source in {"agent", "channel"} else "conversation",
        ),
        uuid4(),
        project_id=uuid4() if source == "project" else None,
    )
    run = RunContext(
        deps=AgentDeps(organization_id=org.id, user_id=str(owner.id), conversation_id=chat.id),
        model=TestModel(),
        usage=RunUsage(),
        prompt="Task",
    )
    load = AsyncMock()
    monkeypatch.setattr(coding_module.PersonalCodingSessionFactory, "_account", load)
    with pytest.raises(AuthorizationError, match="Personal coding accounts"):
        async with factory.session(run, harness="codex", timeout_seconds=60):
            pytest.fail("Shared source admitted")
    load.assert_not_awaited()


@pytest.mark.parametrize("revocation", ["account", "membership"])
async def test_publication_authority_locks_serialize_concurrent_revocation(
    engine: AsyncEngine, revocation: str
) -> None:
    from app.repositories import member as members

    async with AsyncSession(engine, expire_on_commit=False) as setup_db:
        owner = await person(setup_db)
        org = await organization(setup_db, owner)
        auth = context(owner, org)
        account = await CodingAccountService(setup_db).create(auth, request(enabled=True))
        await setup_db.commit()
    factory = PersonalCodingSessionFactory(
        auth, AgentSpec(name="Test"), SandboxConfig(backend="service"), uuid4(), redis=MemoryRedis()
    )
    started, finished = anyio.Event(), anyio.Event()

    async def revoke() -> None:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            started.set()
            if revocation == "account":
                row = await db.get(CodingAccount, account.id)
                assert row is not None
                row.enabled = False
                await db.flush()
            else:
                row = await members.get(db, organization_id=org.id, user_id=owner.id)
                assert row is not None
                await db.delete(row)
                await db.flush()
            await db.commit()
            finished.set()

    async with anyio.create_task_group() as group:
        async with AsyncSession(engine, expire_on_commit=False) as publication:
            assert await factory._active_in(publication, account.id, account.generation, lock=True)
            group.start_soon(revoke)
            await started.wait()
            await anyio.sleep(0.05)
            assert not finished.is_set()
            await publication.commit()
        with anyio.fail_after(5):
            await finished.wait()
    async with AsyncSession(engine, expire_on_commit=False) as db:
        assert not await factory._active_in(db, account.id, account.generation, lock=True)


async def test_named_personal_sessions_keep_files_and_source_revision_without_sharing_them(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @asynccontextmanager
    async def connection() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db
            await db.commit()

    monkeypatch.setattr(coding_module, "get_db_context", connection)
    monkeypatch.setattr(coding_module, "MAX_RETAINED_SESSIONS_PER_ACCOUNT", 2)
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("original")
    parent = Workspace(LocalWorkspaceBackend(source))
    namespaces: list[UUID] = []

    class Workspaces:
        def __init__(self, db: AsyncSession) -> None:
            self.db = db

        async def open(self, spec, *, ctx, identity, scope_override):
            assert scope_override == "user" and identity.namespace is not None
            namespaces.append(identity.namespace)
            folder = tmp_path / str(identity.namespace)
            folder.mkdir(exist_ok=True)
            row = await workspace_repo.create(
                self.db,
                organization_id=ctx.organization_id,
                agent_id=None,
                scope="user",
                scope_key=str(identity.namespace),
                backend="service",
                owner_ref=str(ctx.user_id),
            )
            return OpenWorkspace(
                Workspace(LocalWorkspaceBackend(folder)), "service", "user", row.scope_key, row.id
            )

        async def close(self, opened):
            row = await self.db.get(coding_module.workspace_repo.AgentWorkspace, opened.row_id)
            assert row is not None
            row.session_id = str(row.id)
            await self.db.flush()
            return

    monkeypatch.setattr(coding_module, "SandboxWorkspaceService", Workspaces)
    from app.db.models.conversation import Conversation
    from app.services.sandbox_workspace import SandboxWorkspaceService

    async with connection() as db:
        owner, other = await person(db), await person(db)
        org = await organization(db, owner)
        auth = context(owner, org)
        db.add(OrganizationMember(organization_id=org.id, user_id=other.id, role="owner"))
        await CodingAccountService(db).create(auth, request(enabled=True))
        conversation = Conversation(
            organization_id=org.id, user_id=owner.id, title="Named sessions"
        )
        db.add(conversation)
        await db.flush()
    factory = PersonalCodingSessionFactory(
        auth, AgentSpec(name="Test"), SandboxConfig(backend="service"), uuid4(), redis=MemoryRedis()
    )
    run = RunContext(
        deps=AgentDeps(
            organization_id=org.id,
            user_id=str(owner.id),
            conversation_id=conversation.id,
            run_id=uuid4(),
        ),
        model=TestModel(),
        usage=RunUsage(),
        prompt="Task",
        workspace=parent,
    )
    async with factory.session(
        run, harness="claude_code", timeout_seconds=60, session="api"
    ) as task:
        first_revision = task.base_revision
        assert not task.resumed
        assert await task.workspace.read_bytes("app.py") == b"original"
        await task.workspace.write_bytes("app.py", b"modified in api")
        await task.workspace.write_bytes("native-history", b"remembered")
    (source / "app.py").write_text("new root source")
    async with factory.session(
        run, harness="claude_code", timeout_seconds=60, session="api"
    ) as task:
        assert task.base_revision == first_revision
        assert task.resumed
        assert await task.workspace.read_bytes("app.py") == b"modified in api"
        assert await task.workspace.read_bytes("native-history") == b"remembered"
    async with factory.session(
        run, harness="claude_code", timeout_seconds=60, session="ui"
    ) as task:
        assert task.base_revision != first_revision
        assert not task.resumed
        assert await task.workspace.read_bytes("app.py") == b"new root source"
        assert not await task.workspace.exists("native-history")
    assert namespaces[0] == namespaces[1] != namespaces[2]
    with pytest.raises(BadRequestError, match="saved session limit"):
        async with factory.session(run, harness="claude_code", timeout_seconds=60, session="extra"):
            pytest.fail("A new retained session was admitted past the limit")
    async with factory.session(
        run, harness="claude_code", timeout_seconds=60, session="api"
    ) as task:
        assert task.resumed
    async with connection() as db:
        rows = await workspace_repo.list_personal_coding(
            db, organization_id=org.id, user_id=owner.id
        )
        assert len(rows) == 2
        assert not await workspace_repo.list_for_conversation(
            db, organization_id=org.id, conversation_id=conversation.id
        )
        service = SandboxWorkspaceService(db)
        assert await service._may_read(auth, rows[0])
        assert not await service._may_read(context(other, org), rows[0])
        assert not await workspace_repo.list_for_reader(
            db, organization_id=org.id, user_id=other.id, see_all=True
        )
        assert (
            len(
                await workspace_repo.list_for_reader(
                    db, organization_id=org.id, user_id=owner.id, see_all=True
                )
            )
            == 2
        )
    assert (source / "app.py").read_text() == "new root source"


@pytest.mark.parametrize("failure", ["tenant", "shared_scope"])
async def test_personal_session_constraints_refuse_cross_tenant_or_shared_rows(
    db: AsyncSession, failure: str
) -> None:
    from sqlalchemy.exc import IntegrityError

    from app.db.models.agent_workspace import AgentWorkspace
    from app.db.models.conversation import Conversation

    owner = await person(db)
    org = await organization(db, owner)
    elsewhere = await organization(db, owner)
    account = await CodingAccountService(db).create(context(owner, org), request(enabled=True))
    conversation = Conversation(organization_id=org.id, user_id=owner.id, title="Private")
    db.add(conversation)
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                AgentWorkspace(
                    organization_id=elsewhere.id if failure == "tenant" else org.id,
                    conversation_id=conversation.id,
                    owner_ref=str(owner.id),
                    scope="agent" if failure == "shared_scope" else "user",
                    scope_key=uuid4().hex,
                    backend="service",
                    coding_account_id=account.id,
                )
            )
            await db.flush()


@pytest.mark.parametrize(
    "operation", ["disconnect", "agent_delete", "discard", "chat_retention", "workspace_retention"]
)
async def test_deletion_keeps_remote_cleanup_in_the_same_rollback_boundary(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from unittest.mock import AsyncMock

    from pydantic_ai.workspaces import WorkspaceUnavailableError
    from sqlalchemy import select

    from app.db.models.agent import Agent
    from app.db.models.agent_workspace import AgentWorkspace
    from app.db.models.conversation import Conversation
    from app.db.models.pending_sandbox_destroy import PendingSandboxDestroy
    from app.db.models.sandbox_connection import SandboxConnection
    from app.services.agent_registry import AgentRegistryService
    from app.services.sandbox_connection import SandboxConnectionService

    monkeypatch.setattr(
        SandboxConnectionService,
        "resolve_for_teardown",
        AsyncMock(
            side_effect=WorkspaceUnavailableError("Offline provider"),
        ),
    )
    async with AsyncSession(engine, expire_on_commit=False) as db:
        owner = await person(db)
        org = await organization(db, owner)
        auth = context(owner, org)
        account = await CodingAccountService(db).create(auth, request(enabled=True))
        conversation = Conversation(
            organization_id=org.id,
            user_id=owner.id,
            title="Private",
            updated_at=datetime.now(UTC) - timedelta(days=60),
        )
        remote = SandboxConnection(organization_id=org.id, name="Offline", kind="opensandbox")
        agent = Agent(
            organization_id=org.id,
            owner_user_id=owner.id,
            name="Private coding agent",
            slug=uuid4().hex,
            draft_spec=AgentSpec(name="Private coding agent").model_dump(mode="json"),
        )
        db.add_all([conversation, remote, agent])
        await db.flush()
        workspace = AgentWorkspace(
            organization_id=org.id,
            conversation_id=conversation.id,
            owner_ref=str(owner.id),
            scope="user",
            scope_key=uuid4().hex,
            backend="service",
            coding_account_id=account.id,
            agent_id=agent.id,
            connection_id=remote.id,
            session_id="personal-session-to-destroy",
            last_used_at=datetime.now(UTC) - timedelta(days=60),
        )
        db.add(workspace)
        await db.flush()
        organization_id, account_id, workspace_id, agent_id = (
            org.id,
            account.id,
            workspace.id,
            agent.id,
        )

        async def remove(db: AsyncSession) -> None:
            if operation == "agent_delete":
                await AgentRegistryService(db).delete(auth, agent_id)
            elif operation == "discard":
                from app.services.sandbox_workspace import SandboxWorkspaceService

                held = await db.get(AgentWorkspace, workspace_id)
                assert held is not None
                await SandboxWorkspaceService(db).discard_personal_coding(auth, held)
            elif operation in {"chat_retention", "workspace_retention"}:
                from app.services.retention import RetentionService

                assert (
                    await RetentionService(db)._purge_batch(
                        "conversations" if operation == "chat_retention" else "workspaces",
                        organization_id=organization_id,
                        cutoff=datetime.now(UTC),
                    )
                    == 1
                )
            else:
                await CodingAccountService(db).disconnect(auth, account_id)

        await db.commit()
        await remove(db)
        assert (
            await db.scalar(select(AgentWorkspace.id).where(AgentWorkspace.id == workspace_id))
            is None
        )
        assert (
            await db.scalars(select(PendingSandboxDestroy))
        ).one().ref_id == "personal-session-to-destroy"
        await db.rollback()
    async with AsyncSession(engine, expire_on_commit=False) as db:
        assert await db.get(AgentWorkspace, workspace_id) is not None
        assert await db.get(CodingAccount, account_id) is not None
        assert not (await db.scalars(select(PendingSandboxDestroy))).all()
        await remove(db)
        await db.commit()
    async with AsyncSession(engine, expire_on_commit=False) as db:
        assert await db.get(AgentWorkspace, workspace_id) is None
        assert (await db.get(CodingAccount, account_id) is None) == (operation == "disconnect")
        assert (await db.get(Agent, agent_id) is None) == (operation == "agent_delete")
        assert (
            await db.scalars(select(PendingSandboxDestroy))
        ).one().ref_id == "personal-session-to-destroy"
