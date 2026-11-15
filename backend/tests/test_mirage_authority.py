"""A paused terminal never acquires a different account or rotated credential."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.capabilities import get, load_builtins
from app.agents.capabilities.mirage import MirageConfig
from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.core.secret_kinds import GoogleOAuthAppSecret, SecretKind
from app.repositories import member_repo, organization_secret_repo
from app.schemas.routine_sources import RoutineSourcePolicy
from app.services import mcp_connection, mirage_mounts
from app.services.agent_runner import AgentRunnerService, PausedRunState
from app.services.mcp_connection import McpConnectionService
from app.services.mirage_mounts import MirageMountService
from app.services.routine_actions import routine_effect
from app.services.routine_sources import RoutineSourcesRequired, require_bound_sources
from tests.test_connected_accounts import (
    SOURCE_GENERATION,
    SOURCE_ORG,
    SOURCE_SECRET,
    _account,
    _payload,
    _sealed,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize(
    "changed",
    [
        "unchanged",
        "tenant",
        "membership",
        "inactive_member",
        "rotation",
        "client",
        "removed",
        "legacy",
    ],
)
async def test_personal_account_keeps_the_issuing_tenant_and_current_client(monkeypatch, changed):
    account = _account()
    payload = _payload(account_source_secret_id=None) if changed == "legacy" else _payload()
    account.oauth_payload = _sealed(account, payload)
    member = AsyncMock(return_value=None if changed == "membership" else MagicMock())
    active_member = AsyncMock(return_value=None if changed == "inactive_member" else MagicMock())
    app = GoogleOAuthAppSecret(
        client_id="replacement-client" if changed == "client" else "org-client",
        client_secret="rotated-secret" if changed == "rotation" else "org-secret",
    )
    identity = AsyncMock(
        return_value=(app, SOURCE_SECRET, uuid4() if changed == "rotation" else SOURCE_GENERATION),
        side_effect=NotFoundError() if changed == "removed" else None,
    )
    monkeypatch.setattr(mcp_connection, "decider_context", member)
    monkeypatch.setattr(member_repo, "get_active", active_member)
    monkeypatch.setattr(
        mcp_connection.OrganizationSecretService, "oauth_app_identity_for_org", identity
    )
    result = await McpConnectionService(AsyncMock()).account_grant(
        account, organization_id=uuid4() if changed == "tenant" else SOURCE_ORG
    )
    # A secret rotation keeps its client and uses the current secret. A replaced
    # client, removed app or departed member cannot supply a grant. Paused runs
    # separately pin the credential generation, asserted below.
    assert (result is not None) is (changed in {"unchanged", "rotation"})
    if result is not None:
        assert result.client_id == "org-client"
        assert result.client_secret == app.client_secret
    if changed in {"tenant", "legacy"}:
        member.assert_not_awaited()
        active_member.assert_not_awaited()
    if changed in {"tenant", "legacy", "membership", "inactive_member"}:
        identity.assert_not_awaited()
    else:
        identity.assert_awaited_once_with(SOURCE_ORG, kind=SecretKind.GOOGLE_OAUTH_APP)


async def test_membership_lost_during_grant_resolution_never_reads_the_org_client(monkeypatch):
    account = _account()
    account.oauth_payload = _sealed(account, _payload())
    membership = AsyncMock(side_effect=[MagicMock(), None])
    active_member = AsyncMock(return_value=MagicMock())
    identity = AsyncMock()
    monkeypatch.setattr(mcp_connection, "decider_context", membership)
    monkeypatch.setattr(member_repo, "get_active", active_member)
    monkeypatch.setattr(
        mcp_connection.OrganizationSecretService, "oauth_app_identity_for_org", identity
    )
    db = AsyncMock()

    grant = await McpConnectionService(db).account_grant(account, organization_id=SOURCE_ORG)

    assert grant is None
    assert membership.await_count == 2
    active_member.assert_awaited_once_with(db, organization_id=SOURCE_ORG, user_id=account.user_id)
    identity.assert_not_awaited()


async def test_personal_mount_does_not_list_an_account_issued_by_another_tenant(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=SOURCE_ORG, role="owner")
    own, other = _account(), _account(account_source_organization_id=uuid4())
    monkeypatch.setattr(
        mirage_mounts.mcp_connection_repo, "list_accounts", AsyncMock(return_value=[own, other])
    )
    mount = MirageConfig.model_validate(
        {"mounts": [{"path": "/drive/", "backend": "gdrive", "account": {"kind": "personal"}}]}
    ).mounts[0]
    assert await MirageMountService(AsyncMock())._accounts(ctx, mount, ctx.user_id) == [own]


@pytest.mark.parametrize("change", ["same", "swapped", "legacy"])
async def test_resume_checks_terminal_authority_before_resolving_credentials(monkeypatch, change):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    spec = AgentSpec(
        name="Terminal",
        capabilities=[
            {"id": "mirage", "config": {"mounts": [{"path": "/data/", "backend": "ram"}]}}
        ],
    )
    authority = AsyncMock(return_value="a" * 64)
    resolve = AsyncMock(return_value=object())
    monkeypatch.setattr(MirageMountService, "authority", authority)
    monkeypatch.setattr(MirageMountService, "resolve", resolve)
    service = AgentRunnerService(AsyncMock())
    pins: dict[str, str] = {}
    await service._add_mirage_terminal({}, ctx, spec, person_id=ctx.user_id, authorities=pins)
    state = PausedRunState.model_validate_json(
        PausedRunState(messages=[], tool_call_ids={}, mirage_authorities=pins).model_dump_json()
    )
    assert state.mirage_authorities == pins
    if change == "swapped":
        authority.return_value = "b" * 64
    resolve.reset_mock()
    if change == "same":
        await service._add_mirage_terminal(
            {},
            ctx,
            spec,
            person_id=ctx.user_id,
            authorities=state.mirage_authorities,
            restoring=True,
        )
        resolve.assert_awaited_once()
    else:
        with pytest.raises(AuthorizationError, match="changed while this run waited"):
            await service._add_mirage_terminal(
                {},
                ctx,
                spec,
                person_id=ctx.user_id,
                authorities={} if change == "legacy" else state.mirage_authorities,
                restoring=True,
            )
        resolve.assert_not_awaited()


async def test_routine_secret_rotation_invalidates_the_reviewed_source(monkeypatch):
    policy = RoutineSourcePolicy(
        id=uuid4(),
        consented_by=uuid4(),
        reviewed_at="2026-11-06T00:00:00Z",
        version_id=uuid4(),
        scope_hash="0" * 64,
        spec_hash="0" * 64,
        secret_sources={SOURCE_SECRET: SOURCE_GENERATION},
    )
    generation = AsyncMock(return_value=SOURCE_GENERATION)
    monkeypatch.setattr(organization_secret_repo, "authorization_generation", generation)
    await require_bound_sources(AsyncMock(), organization_id=SOURCE_ORG, policy=policy)
    generation.return_value = uuid4()
    with pytest.raises(RoutineSourcesRequired):
        await require_bound_sources(AsyncMock(), organization_id=SOURCE_ORG, policy=policy)


async def test_routine_terminal_writes_are_effects_even_without_a_mount_approval_gate():
    load_builtins()
    definition = get("mirage")
    effects = {
        tool.id for tool in definition.tools if routine_effect(definition, tool, local=False)
    }
    assert {"mirage_write_file", "mirage_edit_file", "mirage_execute"} <= effects
    assert not {"mirage_ls", "mirage_read_file", "mirage_glob", "mirage_grep"} & effects


@pytest.mark.parametrize("change", ["secret", "account", "client", "disconnect", "legacy", "label"])
async def test_terminal_identity_tracks_credentials_without_exposing_them(monkeypatch, change):
    ctx = AuthContext(user_id=uuid4(), organization_id=SOURCE_ORG, role="owner")
    secret_id, secret_generation = uuid4(), uuid4()
    account = _account(authorization_generation=uuid4())
    account.oauth_payload = _sealed(account, _payload())
    accounts = AsyncMock(return_value=[account])
    generations = {secret_id: secret_generation, SOURCE_SECRET: SOURCE_GENERATION}

    async def generation(db, identifier, *, organization_id):
        assert organization_id == SOURCE_ORG
        return generations[identifier]

    monkeypatch.setattr(mirage_mounts.mcp_connection_repo, "list_accounts", accounts)
    monkeypatch.setattr(organization_secret_repo, "authorization_generation", generation)
    config = MirageConfig.model_validate(
        {
            "mounts": [
                {"path": "/db/", "backend": "postgres", "secrets": {"dsn": str(secret_id)}},
                {"path": "/drive/", "backend": "gdrive", "account": {"kind": "personal"}},
            ]
        }
    )
    service = MirageMountService(AsyncMock())
    original = await service.authority(ctx, config, person_id=ctx.user_id)
    assert len(original) == 64
    assert original == await service.authority(ctx, config, person_id=ctx.user_id)
    if change == "secret":
        generations[secret_id] = uuid4()
    elif change == "account":
        account.authorization_generation = uuid4()
    elif change == "client":
        generations[SOURCE_SECRET] = uuid4()
    elif change == "disconnect":
        accounts.return_value = []
    elif change == "legacy":
        account.oauth_payload = _sealed(account, _payload(account_source_secret_id=None))
    else:
        account.label = "A display-only rename"
    current = await service.authority(ctx, config, person_id=ctx.user_id)
    assert (current == original) is (change == "label")
    assert current == await service.authority(ctx, config, person_id=ctx.user_id)


@pytest.mark.parametrize("pins_kind", ["canonical", "legacy", "canonical_mismatch"])
async def test_terminal_authority_digest_is_canonical_and_preserves_legacy_pins(
    monkeypatch, pins_kind
):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    config = {
        "mounts": [
            {
                "path": "/repo/",
                "backend": "github",
                "options": {"owner": "vstorm-co", "repo": "agenticos"},
                "secrets": {"token": str(uuid4())},
            }
        ]
    }
    spec = AgentSpec(name="Terminal", capabilities=[{"id": "mirage", "config": config}])
    authority = AsyncMock(return_value="a" * 64)
    resolve = AsyncMock(return_value=object())
    monkeypatch.setattr(MirageMountService, "authority", authority)
    monkeypatch.setattr(MirageMountService, "resolve", resolve)
    service = AgentRunnerService(AsyncMock())
    pins: dict[str, str] = {}
    await service._add_mirage_terminal({}, ctx, spec, person_id=ctx.user_id, authorities=pins)
    assert len(pins) == 2
    canonical = next(key for key in pins if key.startswith("v2:"))
    legacy = next(key for key in pins if not key.startswith("v2:"))
    if pins_kind == "legacy":
        pins = {legacy: pins[legacy]}
    else:
        # The same free map as JSONB may return it, in a different order.
        config["mounts"][0]["options"] = {"repo": "agenticos", "owner": "vstorm-co"}
        spec = AgentSpec(name="Terminal", capabilities=[{"id": "mirage", "config": config}])
        if pins_kind == "canonical_mismatch":
            pins[canonical] = "b" * 64
    resolve.reset_mock()
    if pins_kind == "canonical_mismatch":
        with pytest.raises(AuthorizationError, match="changed while this run waited"):
            await service._add_mirage_terminal(
                {}, ctx, spec, person_id=ctx.user_id, authorities=pins, restoring=True
            )
        resolve.assert_not_awaited()
    else:
        await service._add_mirage_terminal(
            {}, ctx, spec, person_id=ctx.user_id, authorities=pins, restoring=True
        )
        resolve.assert_awaited_once()
        assert pins[canonical] == "a" * 64
