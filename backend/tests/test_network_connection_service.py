"""Enrollment is an explicit, owner/session-bound action with durable cleanup."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    ConfigurationError,
    ConflictError,
    NotFoundError,
)
from app.core.vault import VaultScope, seal, unseal
from app.repositories import resource_grant_repo
from app.schemas.network_connection import NetworkConnectionCreate
from app.services.network_connections import (
    NetworkConnectionService,
    admission,
    connection_scope,
    facade,
)
from tests.network_connection_fixtures import network_row, owner_context

pytestmark = pytest.mark.anyio


@pytest.fixture
def env(monkeypatch):
    row = network_row()
    ctx = owner_context(row)
    session_id = uuid4()
    session = SimpleNamespace(
        user_id=ctx.user_id,
        is_active=True,
        impersonator_user_id=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db = MagicMock()
    service = NetworkConnectionService(db)
    repo = facade.network_connection_repo
    get_row = AsyncMock(return_value=row)
    monkeypatch.setattr(repo, "get_by_id", get_row)
    get_session = AsyncMock(return_value=session)
    monkeypatch.setattr(facade.session_repo, "get_by_id", get_session)
    monkeypatch.setattr(resource_grant_repo, "get_level", AsyncMock(return_value=None))
    monkeypatch.setattr(facade, "visible_resource_ids", AsyncMock(return_value=[]))
    listing = AsyncMock(return_value=([row], 1))
    monkeypatch.setattr(repo, "list_visible", listing)
    monkeypatch.setattr(repo, "lock_quota", AsyncMock(return_value=True))
    monkeypatch.setattr(repo, "count_for_owner", AsyncMock(return_value=0))
    monkeypatch.setattr(repo, "count_pending_enrollments", AsyncMock(return_value=0))
    monkeypatch.setattr(facade, "guard_member", AsyncMock())
    monkeypatch.setattr(facade.member_repo, "get_active", AsyncMock(return_value=SimpleNamespace()))
    create = AsyncMock(return_value=row)
    monkeypatch.setattr(repo, "create", create)

    async def updated(_db, *, changes, **_kwargs):
        for key, value in changes.items():
            setattr(row, key, value)
        return row

    update = AsyncMock(side_effect=updated)
    monkeypatch.setattr(repo, "update", update)

    async def settled(_db, *, changes, expected_policy_generation, **_kwargs):
        if row.policy_generation != expected_policy_generation or (
            row.lease_expires_at is not None and row.lease_expires_at > datetime.now(UTC)
        ):
            return None
        for key, value in changes.items():
            setattr(row, key, value)
        row.runtime_state = "stopped"
        row.login_payload = None
        row.enrollment_expires_at = None
        row.enrollment_id = row.enrollment_user_id = row.enrollment_session_id = None
        row.lease_id = row.lease_expires_at = None
        row.peers = []
        row.policy_generation += 1
        return row

    settle = AsyncMock(side_effect=settled)
    monkeypatch.setattr(repo, "settle_inactive", settle)
    queued = AsyncMock()
    audited = AsyncMock()
    monkeypatch.setattr(facade, "enqueue", queued)
    monkeypatch.setattr(facade, "record_audit", audited)
    monkeypatch.setattr(NetworkConnectionService, "available", staticmethod(lambda: True))
    return SimpleNamespace(
        row=row,
        ctx=ctx,
        session_id=session_id,
        session=session,
        service=service,
        db=db,
        repo=repo,
        get_row=get_row,
        get_session=get_session,
        listing=listing,
        create=create,
        update=update,
        settle=settle,
        queued=queued,
        audited=audited,
    )


@pytest.mark.security
@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": None},
        {"api_key_id": uuid4()},
        {"key_scopes": frozenset()},
        {"channel_identity_id": uuid4()},
        {"subject_is_publisher_fallback": True},
        {"fired_as_creator": "schedule"},
        {"routine_id": uuid4()},
        {"routine_source_policy_id": uuid4()},
        {"routine_activation_id": uuid4()},
        {"is_impersonated": True},
        {"is_workflow": True},
    ],
)
async def test_background_and_delegated_contexts_cannot_administer_a_persons_network(env, changes):
    with pytest.raises(AuthorizationError):
        await env.service.connect(
            replace(env.ctx, **changes), connection_id=env.row.id, session_id=env.session_id
        )
    env.queued.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": uuid4()},
        {"is_active": False},
        {"impersonator_user_id": uuid4()},
        {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
    ],
)
async def test_an_expired_revoked_foreign_or_impersonated_session_is_refused(env, changes):
    for key, value in changes.items():
        setattr(env.session, key, value)
    with pytest.raises(AuthorizationError):
        await env.service.get(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    env.get_row.assert_not_awaited()


@pytest.mark.security
async def test_no_session_or_current_impersonation_is_refused_before_loading_a_row(
    env, monkeypatch
):
    with pytest.raises(AuthorizationError):
        await env.service.get(env.ctx, connection_id=env.row.id, session_id=None)
    monkeypatch.setattr(facade, "current_impersonator", lambda: uuid4())
    with pytest.raises(AuthorizationError):
        await env.service.get(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    env.get_row.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize("changed_field", ["organization_id", "owner_user_id"])
async def test_even_an_org_owner_cannot_read_another_person_or_tenants_personal_row(
    env, changed_field
):
    setattr(env.row, changed_field, uuid4())
    with pytest.raises(NotFoundError):
        await env.service.get(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    env.queued.assert_not_awaited()


@pytest.mark.security
async def test_the_same_member_in_another_org_cannot_read_the_enrollment(env):
    other_org = replace(env.ctx, organization_id=uuid4())
    with pytest.raises(NotFoundError):
        await env.service.enrollment(other_org, connection_id=env.row.id, session_id=env.session_id)


async def test_list_details_and_peers_only_read_the_last_snapshot(env):
    env.row.peers = [
        {
            "id": "stable-peer",
            "hostname": "laptop",
            "dns_name": None,
            "ips": ["100.90.0.1"],
            "online": True,
            "os": "windows",
        }
    ]
    env.row.last_seen_at = datetime.now(UTC) - timedelta(minutes=10)
    listing = await env.service.list(env.ctx, session_id=env.session_id)
    detail = await env.service.get(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    peers = await env.service.peers(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    assert listing.total == 1 and listing.available
    assert detail.can_manage
    assert peers.items[0].id == "stable-peer"
    assert peers.observed_at == env.row.last_seen_at
    env.queued.assert_not_awaited()
    env.update.assert_not_awaited()


@pytest.mark.security
async def test_list_and_detail_never_expose_stored_enrollment_or_identity_material(env):
    env.row.login_payload = "encrypted-login-payload"
    env.row.state_payload = "encrypted-node-payload"
    detail = await env.service.get(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    result = await env.service.list(env.ctx, session_id=env.session_id)
    for value in (detail.model_dump_json(), result.model_dump_json()):
        assert "encrypted-" not in value
        assert "enrollment_session_id" not in value
        assert "lease_id" not in value
        assert "state_payload" not in value


async def test_creation_is_paused_and_never_allocates_a_broker(env):
    result = await env.service.create(
        env.ctx, NetworkConnectionCreate(name="My devices", scope="user"), session_id=env.session_id
    )
    assert result.desired_state == "paused"
    assert result.auth_state == "not_connected"
    env.queued.assert_not_awaited()
    assert env.create.call_args.kwargs["organization_id"] == env.ctx.organization_id
    assert env.create.call_args.kwargs["owner_user_id"] == env.ctx.user_id


@pytest.mark.security
async def test_a_member_cannot_create_a_shared_network(env):
    with pytest.raises(AuthorizationError):
        await env.service.create(
            replace(env.ctx, role="member"),
            NetworkConnectionCreate(name="Shared", scope="org"),
            session_id=env.session_id,
        )
    env.create.assert_not_awaited()


async def test_creation_is_refused_while_the_feature_is_off(env, monkeypatch):
    monkeypatch.setattr(NetworkConnectionService, "available", staticmethod(lambda: False))
    with pytest.raises(ConfigurationError):
        await env.service.create(
            env.ctx,
            NetworkConnectionCreate(name="My devices", scope="user"),
            session_id=env.session_id,
        )
    env.create.assert_not_awaited()


async def test_creation_obeys_the_serialized_member_quota(env, monkeypatch):
    monkeypatch.setattr(env.repo, "count_for_owner", AsyncMock(return_value=10))
    with pytest.raises(BadRequestError, match="limit"):
        await env.service.create(
            env.ctx, NetworkConnectionCreate(name="New", scope="user"), session_id=env.session_id
        )
    facade.guard_member.assert_awaited_once_with(
        env.db,
        organization_id=env.ctx.organization_id,
        user_id=env.ctx.user_id,
        admission=True,
    )
    env.create.assert_not_awaited()


async def test_only_explicit_connect_queues_an_attempt_bound_to_its_person_and_session(env):
    result = await env.service.connect(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    assert result.desired_state == "active"
    assert result.runtime_state == "starting"
    assert env.row.enrollment_user_id == env.ctx.user_id
    assert env.row.enrollment_session_id == env.session_id
    assert env.row.policy_generation == 2
    job = env.queued.call_args.args[2]
    assert job.organization_id == env.ctx.organization_id
    assert job.enrollment_id == env.row.enrollment_id
    assert job.policy_generation == 2
    assert job.mode == "enroll"
    assert env.queued.call_args.kwargs["dedupe_active"] is True
    await env.service.connect(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    env.queued.assert_awaited_once()


@pytest.mark.security
async def test_another_session_cannot_take_over_an_in_progress_login(env):
    await env.service.connect(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    with pytest.raises(BadRequestError, match="progress"):
        await env.service.connect(env.ctx, connection_id=env.row.id, session_id=uuid4())
    with pytest.raises(NotFoundError):
        await env.service.enrollment(env.ctx, connection_id=env.row.id, session_id=uuid4())
    env.queued.assert_awaited_once()


@pytest.mark.security
async def test_only_the_live_initiating_session_can_decrypt_the_login_url(env):
    await env.service.connect(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    url = "https://login.tailscale.com/a/synthetic-login"
    env.row.auth_state = "sign_in_required"
    env.row.login_payload = seal(url, scope=connection_scope(env.row)).ciphertext
    result = await env.service.enrollment(
        env.ctx, connection_id=env.row.id, session_id=env.session_id
    )
    assert result.login_url == url
    assert url not in repr(result)
    env.row.enrollment_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    expired = await env.service.enrollment(
        env.ctx, connection_id=env.row.id, session_id=env.session_id
    )
    assert expired.login_url is None and expired.attempt_id is None


@pytest.mark.security
@pytest.mark.parametrize("field", ["organization_id", "owner_user_id", "id"])
def test_encrypted_identity_cannot_be_moved_to_another_connection_or_owner(field):
    row = network_row()
    sealed = seal("synthetic-private-key", scope=connection_scope(row))
    setattr(row, field, uuid4())
    with pytest.raises(BadRequestError):
        unseal(sealed.ciphertext, scope=connection_scope(row))


def test_an_org_identity_is_bound_to_its_org_and_connection_not_its_creator():
    row = network_row(scope="org", visibility="org")
    original = connection_scope(row)
    row.owner_user_id = uuid4()
    assert connection_scope(row) == original
    row.owner_user_id = None
    assert connection_scope(row) == original
    assert original != VaultScope.organization(row.organization_id)


async def test_pause_fences_the_writer_and_keeps_the_enrolled_identity(env):
    env.row.desired_state = "active"
    env.row.runtime_state = "running"
    env.row.state_payload = "encrypted-persistent-state"
    env.row.login_payload = "encrypted-login"
    env.row.lease_id = uuid4()
    env.row.lease_expires_at = datetime.now(UTC) + timedelta(seconds=15)
    lease = env.row.lease_id
    result = await env.service.pause(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    assert result.desired_state == "paused" and result.policy_generation == 2
    assert env.row.state_payload == "encrypted-persistent-state"
    assert env.row.login_payload is None
    assert env.row.lease_id == lease
    env.queued.assert_not_awaited()


async def test_revoke_denies_before_queueing_logout_and_keeps_cleanup_visible(env):
    env.row.desired_state = "active"
    env.row.state_payload = "encrypted-persistent-state"
    env.row.login_payload = "encrypted-login"
    env.row.peers = [
        {"id": "peer", "online": True, "ips": [], "hostname": "", "dns_name": None, "os": ""}
    ]
    env.row.lease_id = uuid4()
    env.row.lease_expires_at = datetime.now(UTC) + timedelta(seconds=15)
    lease = env.row.lease_id

    async def check_deny_before_queue(*_args, **_kwargs):
        assert env.row.desired_state == "revoked"
        assert env.row.login_payload is None and env.row.peers == []
        assert env.row.policy_generation == 2

    env.queued.side_effect = check_deny_before_queue
    result = await env.service.revoke(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    assert result.cleanup_state == "pending"
    assert env.row.lease_id == lease
    assert env.row.state_payload == "encrypted-persistent-state"
    assert env.queued.call_args.args[2].mode == "logout"
    assert env.queued.call_args.kwargs["run_after"] > datetime.now(UTC)
    await env.service.revoke(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    env.queued.assert_awaited_once()
    with pytest.raises(BadRequestError):
        await env.service.connect(env.ctx, connection_id=env.row.id, session_id=env.session_id)


async def test_revoking_an_unused_record_needs_no_provider_cleanup(env):
    result = await env.service.revoke(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    assert result.cleanup_state == "complete"
    assert result.runtime_state == "stopped"
    env.queued.assert_not_awaited()


@pytest.mark.security
async def test_revoke_cannot_claim_provider_removal_when_only_node_metadata_remains(env):
    env.row.node_id = "known-node"
    env.row.tailnet_name = "example.ts.net"
    result = await env.service.revoke(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    assert result.cleanup_state == "manual"
    assert result.runtime_state == "stopped"
    env.queued.assert_not_awaited()


@pytest.mark.security
async def test_membership_removed_before_admission_cannot_create_a_connection(env, monkeypatch):
    monkeypatch.setattr(facade.member_repo, "get_active", AsyncMock(return_value=None))
    with pytest.raises(AuthorizationError, match="membership"):
        await env.service.create(
            env.ctx,
            NetworkConnectionCreate(name="My devices", scope="user"),
            session_id=env.session_id,
        )
    env.create.assert_not_awaited()


@pytest.mark.security
async def test_removed_membership_cannot_read_a_pending_login_link(env, monkeypatch):
    monkeypatch.setattr(facade.member_repo, "get_active", AsyncMock(return_value=None))
    with pytest.raises(AuthorizationError, match="membership"):
        await env.service.enrollment(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    env.get_row.assert_not_awaited()


@pytest.mark.parametrize("counts", [[1], [0, 4]])
async def test_pending_enrollment_limits_refuse_work_before_queueing(env, monkeypatch, counts):
    monkeypatch.setattr(env.repo, "count_pending_enrollments", AsyncMock(side_effect=counts))
    with pytest.raises(BadRequestError):
        await env.service.connect(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    assert env.row.desired_state == "paused"
    env.queued.assert_not_awaited()


async def test_refresh_is_explicit_and_uses_the_existing_identity(env):
    env.row.desired_state = "active"
    env.row.auth_state = "authenticated"
    env.row.state_payload = "existing-encrypted-state"
    result = await env.service.refresh(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    assert result.runtime_state == "starting"
    assert env.row.state_payload == "existing-encrypted-state"
    assert env.queued.call_args.args[2].mode == "status"
    assert env.queued.call_args.args[2].policy_generation == 2
    await env.service.refresh(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    env.queued.assert_awaited_once()


async def test_unenrolled_refresh_and_disabled_connect_do_no_network_work(env, monkeypatch):
    with pytest.raises(BadRequestError):
        await env.service.refresh(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    monkeypatch.setattr(NetworkConnectionService, "available", staticmethod(lambda: False))
    with pytest.raises(ConfigurationError):
        await env.service.connect(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    env.queued.assert_not_awaited()


async def test_a_network_reader_gets_metadata_without_management_controls(env):
    env.row.scope = "org"
    env.row.visibility = "org"
    env.row.owner_user_id = uuid4()
    result = await env.service.get(
        replace(env.ctx, role="operator"), connection_id=env.row.id, session_id=env.session_id
    )
    assert result.can_manage is False
    with pytest.raises(NotFoundError):
        await env.service.connect(
            replace(env.ctx, role="operator"), connection_id=env.row.id, session_id=env.session_id
        )


@pytest.mark.security
async def test_leaving_an_org_revokes_each_personal_connection_in_that_org(env, monkeypatch):
    env.row.state_payload = "encrypted-state"
    rows = AsyncMock(return_value=[env.row])
    monkeypatch.setattr(env.repo, "list_personal_for_member", rows)
    monkeypatch.setattr(env.repo, "has_personal_for_member", AsyncMock(return_value=True))
    assert (
        await env.service.revoke_member(
            organization_id=env.ctx.organization_id, user_id=env.ctx.user_id
        )
        == 1
    )
    assert env.row.desired_state == "revoked"
    assert env.queued.call_args.args[2].mode == "logout"
    assert rows.call_args.kwargs["organization_id"] == env.ctx.organization_id
    assert rows.call_args.kwargs["user_id"] == env.ctx.user_id


@pytest.mark.security
@pytest.mark.parametrize("has_rows", [False, True])
async def test_member_removal_only_takes_the_per_user_lock_when_network_rows_exist(
    env, monkeypatch, has_rows
):
    """A routine job holding the per-user lock must not block removing a member with no rows."""
    monkeypatch.setattr(facade, "guard_member", admission.guard_member)
    monkeypatch.setattr(admission, "try_hold_subject", AsyncMock(return_value=False))
    monkeypatch.setattr(env.repo, "has_personal_for_member", AsyncMock(return_value=has_rows))
    rows = AsyncMock(return_value=[])
    monkeypatch.setattr(env.repo, "list_personal_for_member", rows)
    call = env.service.revoke_member(
        organization_id=env.ctx.organization_id, user_id=env.ctx.user_id
    )
    if has_rows:
        with pytest.raises(ConcurrentChangeError):
            await call
    else:
        assert await call == 0
        rows.assert_not_awaited()


@pytest.mark.security
async def test_account_and_org_deletion_refuse_to_orphan_stored_node_identity(env, monkeypatch):
    env.row.state_payload = "encrypted-state"
    monkeypatch.setattr(env.repo, "list_personal_for_user", AsyncMock(return_value=[env.row]))
    monkeypatch.setattr(env.repo, "list_for_organization", AsyncMock(return_value=[env.row]))
    deleted = AsyncMock(return_value=1)
    monkeypatch.setattr(env.repo, "delete_inactive_personal", deleted)
    with pytest.raises(ConflictError, match="Revoke"):
        await env.service.prepare_user_deletion(env.ctx.user_id)
    with pytest.raises(ConflictError, match="Revoke"):
        await env.service.prepare_organization_deletion(env.ctx.organization_id)
    deleted.assert_not_awaited()


async def test_erasing_an_account_also_erases_its_inactive_private_network_metadata(
    env, monkeypatch
):
    monkeypatch.setattr(env.repo, "list_personal_for_user", AsyncMock(return_value=[env.row]))
    deleted = AsyncMock(return_value=1)
    monkeypatch.setattr(env.repo, "delete_inactive_personal", deleted)
    await env.service.prepare_user_deletion(env.ctx.user_id)
    assert env.row.desired_state == "revoked"
    deleted.assert_awaited_once_with(env.db, user_id=env.ctx.user_id)
    env.queued.assert_not_awaited()


@pytest.mark.security
async def test_account_erasure_waits_for_a_live_broker_to_stop(env, monkeypatch):
    env.row.lease_id = uuid4()
    env.row.lease_expires_at = datetime.now(UTC) + timedelta(seconds=15)
    monkeypatch.setattr(env.repo, "list_personal_for_user", AsyncMock(return_value=[env.row]))
    with pytest.raises(ConflictError, match="finishing"):
        await env.service.prepare_user_deletion(env.ctx.user_id)


@pytest.mark.security
async def test_audit_entries_contain_only_ids_scope_and_generation(env):
    env.row.state_payload = "synthetic-secret-payload"
    await env.service.connect(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    await env.service.pause(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    await env.service.revoke(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    for call in env.audited.call_args_list:
        assert set(call.kwargs["details"]) == {"scope", "policy_generation"}
        assert "synthetic-secret-payload" not in repr(call)
