"""Account selection stays inside the published grant and gives actionable setup guidance."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.audience import RunAudience
from app.agents.capabilities import _integration as capability
from app.agents.capabilities._integration import NativeIntegration
from app.agents.capabilities._integration_toolset import build_toolset
from app.agents.deps import AgentDeps
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun
from app.schemas.routine_sources import RoutineSourcePolicy
from app.services.integrations import (
    PRODUCTS,
    AccountSelection,
    IntegrationAccountRequired,
    IntegrationService,
    authority,
)
from tests.test_native_integrations import account

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def context(*, private: bool = True, organization_id: UUID | None = None) -> RunContext[AgentDeps]:
    person = uuid4()
    return RunContext(
        deps=AgentDeps(
            organization_id=organization_id or uuid4(),
            run_person=person,
            audience=RunAudience(user_id=person, room_key=None if private else "room"),
        ),
        model=TestModel(),
        usage=RunUsage(),
    )


async def test_personal_account_choice_does_not_override_the_published_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, person = uuid4(), uuid4()
    work = account(name="work", user_id=person, account_source_organization_id=org)
    other = account(name="other", user_id=person, account_source_organization_id=org)
    monkeypatch.setattr(
        "app.services.integrations.service.member_repo.get_active", AsyncMock(return_value=object())
    )
    lookup = AsyncMock(return_value=[work, other])
    monkeypatch.setattr(
        "app.services.integrations.service.mcp_connection_repo.list_accounts", lookup
    )
    service = IntegrationService(AsyncMock())
    assert (
        await service.account(
            PRODUCTS["gmail"],
            AccountSelection(),
            organization_id=org,
            person_id=person,
            account_name="other",
        )
        is other
    )
    assert lookup.await_args.kwargs["user_id"] == person
    with pytest.raises(IntegrationAccountRequired):
        await service.account(
            PRODUCTS["gmail"],
            AccountSelection(account_name="work"),
            organization_id=org,
            person_id=person,
            account_name="other",
        )
    with pytest.raises(IntegrationAccountRequired):
        await service.account(
            PRODUCTS["gmail"], AccountSelection(), organization_id=org, person_id=person
        )


async def test_organization_choice_cannot_add_an_unbound_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = uuid4()
    first, second, unbound = [
        account(scope="org", organization_id=org, name=name)
        for name in ("first", "second", "unbound")
    ]
    held = {row.id: row for row in (first, second, unbound)}
    lookup = AsyncMock(side_effect=lambda _db, identifier: held.get(identifier))
    monkeypatch.setattr("app.services.integrations.service.mcp_connection_repo.get_account", lookup)
    service = IntegrationService(AsyncMock())
    selection = AccountSelection(
        account="organization", connection_id=first.id, connection_ids=[first.id, second.id]
    )
    assert (
        await service.account(
            PRODUCTS["gmail"], selection, organization_id=org, person_id=None, account_name="second"
        )
        is second
    )
    with pytest.raises(IntegrationAccountRequired):
        await service.account(
            PRODUCTS["gmail"],
            selection,
            organization_id=org,
            person_id=None,
            account_name="unbound",
        )
    assert all(call.args[1] != unbound.id for call in lookup.await_args_list)


async def test_publication_rechecks_every_selected_account(monkeypatch: pytest.MonkeyPatch) -> None:
    service = IntegrationService(AsyncMock())
    first, second = uuid4(), uuid4()
    rows = [account(id=first), account(id=second)]
    checks = AsyncMock(side_effect=rows)
    monkeypatch.setattr(service, "binding_account", checks)
    ctx = AuthContext(organization_id=uuid4(), user_id=uuid4(), role="owner")
    selection = AccountSelection(account="organization", connection_ids=[first, second])
    assert await service.binding_accounts(PRODUCTS["gmail"], selection, ctx) == rows
    assert [call.args[1].connection_id for call in checks.await_args_list] == [first, second]
    checks.side_effect = [rows[0], AuthorizationError(message="grant revoked")]
    with pytest.raises(AuthorizationError, match="grant revoked"):
        await service.binding_accounts(PRODUCTS["gmail"], selection, ctx)


async def test_personal_binding_review_includes_all_current_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = IntegrationService(AsyncMock())
    rows = [account(name="one"), account(name="two")]
    monkeypatch.setattr(service, "accounts", AsyncMock(return_value=rows))
    checks = AsyncMock(side_effect=rows)
    monkeypatch.setattr(service, "binding_account", checks)
    ctx = AuthContext(organization_id=uuid4(), user_id=uuid4(), role="owner")
    assert await service.binding_accounts(PRODUCTS["gmail"], AccountSelection(), ctx) == rows
    assert [call.args[1].account_name for call in checks.await_args_list] == ["one", "two"]
    monkeypatch.setattr(service, "accounts", AsyncMock(return_value=[]))
    with pytest.raises(IntegrationAccountRequired):
        await service.binding_accounts(PRODUCTS["gmail"], AccountSelection(), ctx)


async def test_account_metadata_requires_current_binding_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = IntegrationService(AsyncMock())
    rows = [account(name="one"), account(name="two")]
    monkeypatch.setattr(service, "accounts", AsyncMock(return_value=rows))
    ctx = AuthContext(organization_id=uuid4(), user_id=uuid4(), role="owner")
    monkeypatch.setattr(authority, "run_author", AsyncMock(return_value=ctx))
    check = AsyncMock(side_effect=[None, AuthorizationError(message="not shared")])
    monkeypatch.setattr(authority, "authorize", check)
    with pytest.raises(AuthorizationError, match="not shared"):
        await service.available_accounts(
            PRODUCTS["gmail"],
            AccountSelection(account="organization"),
            organization_id=ctx.organization_id,
            person_id=ctx.user_id,
        )
    assert check.await_count == 2
    check.side_effect = None
    check.return_value = None
    assert (
        await service.available_accounts(
            PRODUCTS["gmail"],
            AccountSelection(account="organization"),
            organization_id=ctx.organization_id,
            person_id=ctx.user_id,
        )
        == rows
    )
    assert (
        await service.available_accounts(
            PRODUCTS["gmail"],
            AccountSelection(),
            organization_id=ctx.organization_id,
            person_id=ctx.user_id,
        )
        == rows
    )


@pytest.mark.parametrize("held", [False, True])
async def test_model_is_told_which_accounts_exist_and_where_to_connect(
    monkeypatch: pytest.MonkeyPatch, held: bool
) -> None:
    @asynccontextmanager
    async def database() -> AsyncIterator[AsyncSession]:
        yield AsyncMock(spec=AsyncSession)

    monkeypatch.setattr(capability, "get_db_context", database)
    rows = [account(name="work-one", label="Work"), account(name="work-two", label="Work")]
    lookup = AsyncMock(return_value=rows if held else [])
    monkeypatch.setattr(IntegrationService, "available_accounts", lookup)
    integration = NativeIntegration(
        "gmail", AccountSelection(), build_toolset("gmail", AccountSelection())
    )
    prompt = await integration.get_instructions()(context())
    assert "Chat controls → Preferences → Your accounts" in prompt
    if held:
        assert "work-one" in prompt and "work-two" in prompt
        assert "ask before accessing any account" in prompt
    else:
        assert "no matching connected account" in prompt
    lookup.side_effect = AuthorizationError(message="grant revoked")
    assert "grant revoked" in await integration.get_instructions()(context())


async def test_shared_surfaces_do_not_disclose_personal_account_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup = AsyncMock()
    monkeypatch.setattr(IntegrationService, "available_accounts", lookup)
    integration = NativeIntegration(
        "gmail", AccountSelection(), build_toolset("gmail", AccountSelection())
    )
    prompt = await integration.get_instructions()(context(private=False))
    assert "private chat" in prompt
    missing_org = context()
    missing_org.deps.organization_id = None
    assert "no organization" in await integration.get_instructions()(missing_org)
    missing_audience = context()
    missing_audience.deps.audience = None
    assert "private chat" in await integration.get_instructions()(missing_audience)
    lookup.assert_not_awaited()


@pytest.mark.parametrize("kind", [None, "trigger"])
async def test_a_running_routine_cannot_acquire_an_account_added_after_review(
    monkeypatch: pytest.MonkeyPatch, kind: str | None
) -> None:
    org, identifier = uuid4(), uuid4()
    row = account(authorization_generation=uuid4())
    policy = RoutineSourcePolicy(
        id=uuid4(),
        consented_by=uuid4(),
        reviewed_at=datetime.now(UTC),
        version_id=uuid4(),
        scope_hash="a" * 64,
        spec_hash="b" * 64,
        mirage_accounts={row.id: row.authorization_generation},
    )
    run = AgentRun(routine_kind=kind, routine_policy=policy.model_dump(mode="json"))
    monkeypatch.setattr(authority.agent_run_repo, "get_run", AsyncMock(return_value=run))
    await authority.require_reviewed_accounts(
        AsyncMock(), [row], organization_id=org, agent_run_id=identifier
    )
    if kind:
        row.authorization_generation = uuid4()
        with pytest.raises(AuthorizationError, match="Review"):
            await authority.require_reviewed_accounts(
                AsyncMock(), [row], organization_id=org, agent_run_id=identifier
            )
    monkeypatch.setattr(authority.agent_run_repo, "get_run", AsyncMock(return_value=None))
    with pytest.raises(AuthorizationError, match="no longer exists"):
        await authority.require_reviewed_accounts(
            AsyncMock(), [row], organization_id=org, agent_run_id=identifier
        )


async def test_no_organization_account_is_never_an_implicit_default() -> None:
    with pytest.raises(NotFoundError):
        await IntegrationService(AsyncMock()).accounts(
            PRODUCTS["gmail"],
            AccountSelection(account="organization"),
            organization_id=uuid4(),
            person_id=None,
        )


def test_legacy_config_loads_and_account_limits_apply_to_the_combined_allowlist() -> None:
    from pydantic import ValidationError

    identifier = uuid4()
    old = AccountSelection.model_validate(
        {"account": "organization", "connection_id": str(identifier)}
    )
    assert old.connection_id == identifier and old.connection_ids == []
    with pytest.raises(ValidationError, match="at most 20"):
        AccountSelection(connection_id=identifier, connection_ids=[uuid4() for _ in range(20)])
