"""Lease, session authority and cleanup behavior around the isolated node."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.vault import seal, unseal
from app.repositories import network_connection_repo, resource_grant_repo
from app.services.network_connections import authority, lifecycle, runtime
from app.services.network_connections.broker import BrokerFailure
from app.services.network_connections.protocol import StateFrame, StatusFrame
from app.services.network_connections.secrets import connection_scope
from tests.network_connection_fixtures import admitted_row, node_job, owner_context

pytestmark = pytest.mark.anyio


@pytest.fixture
def env(monkeypatch):
    row = admitted_row()
    job = node_job(row)
    lease_id = uuid4()
    row.lease_id = lease_id
    row.lease_expires_at = datetime.now(UTC) + timedelta(seconds=15)
    db = MagicMock()
    events = []

    @asynccontextmanager
    async def transaction():
        yield db
        events.append("commit")

    monkeypatch.setattr(runtime, "get_worker_db_context", transaction)
    monkeypatch.setattr(lifecycle, "get_worker_db_context", transaction)
    monkeypatch.setattr(lifecycle, "hold_parent", AsyncMock())
    get_row = AsyncMock(return_value=row)
    monkeypatch.setattr(network_connection_repo, "get_by_id", get_row)
    session = SimpleNamespace(
        user_id=row.enrollment_user_id,
        is_active=True,
        impersonator_user_id=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    get_session = AsyncMock(return_value=session)
    monkeypatch.setattr(authority.session_repo, "get_by_id", get_session)
    member = AsyncMock(return_value=owner_context(row))
    monkeypatch.setattr(authority, "member_context", member)
    monkeypatch.setattr(resource_grant_repo, "get_level", AsyncMock(return_value=None))

    async def update(_db, *, changes, lease_id=None, expected_policy_generation=None, **_kwargs):
        if lease_id is not None and (
            row.lease_id != lease_id
            or row.policy_generation != expected_policy_generation
            or row.lease_expires_at is None
            or row.lease_expires_at <= datetime.now(UTC)
        ):
            return None
        for key, value in changes.items():
            setattr(row, key, value)
        return row

    saved = AsyncMock(side_effect=update)
    monkeypatch.setattr(network_connection_repo, "update", saved)
    renewed = AsyncMock(return_value=True)
    monkeypatch.setattr(network_connection_repo, "renew_lease", renewed)

    async def claim(_db, *, lease_id, **_kwargs):
        row.lease_id = lease_id
        row.lease_expires_at = datetime.now(UTC) + timedelta(seconds=15)
        return row

    claimed = AsyncMock(side_effect=claim)
    monkeypatch.setattr(network_connection_repo, "claim_lease", claimed)

    async def release(_db, *, lease_id, expected_policy_generation, **_kwargs):
        if row.lease_id != lease_id:
            return False
        row.lease_id = row.lease_expires_at = None
        if row.policy_generation == expected_policy_generation or row.desired_state != "active":
            row.runtime_state = "stopped"
        return True

    released = AsyncMock(side_effect=release)
    monkeypatch.setattr(network_connection_repo, "release_lease", released)

    async def settle(_db, *, changes, expected_policy_generation, **_kwargs):
        if row.policy_generation != expected_policy_generation or (
            row.lease_expires_at is not None and row.lease_expires_at > datetime.now(UTC)
        ):
            return None
        for key, value in changes.items():
            setattr(row, key, value)
        row.runtime_state = "stopped"
        row.login_payload = row.enrollment_expires_at = None
        row.enrollment_id = row.enrollment_user_id = row.enrollment_session_id = None
        row.lease_id = row.lease_expires_at = None
        row.peers = []
        row.policy_generation += 1
        return row

    settled = AsyncMock(side_effect=settle)
    monkeypatch.setattr(network_connection_repo, "settle_inactive", settled)
    monkeypatch.setattr(settings, "TAILSCALE_ENABLED", True)
    return SimpleNamespace(
        row=row,
        job=job,
        db=db,
        lease_id=lease_id,
        node=runtime.NodeSession(job, lease_id),
        session=session,
        get_session=get_session,
        member=member,
        get_row=get_row,
        events=events,
        saved=saved,
        renewed=renewed,
        claimed=claimed,
        released=released,
        settled=settled,
    )


@pytest.mark.security
@pytest.mark.parametrize(
    "changes",
    [
        {"policy_generation": 2},
        {"desired_state": "paused"},
        {"enrollment_id": uuid4()},
        {"enrollment_expires_at": None},
        {"enrollment_expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        {"enrollment_user_id": None},
        {"enrollment_session_id": None},
        {"owner_user_id": uuid4()},
    ],
)
async def test_changed_authority_stops_the_next_lease_heartbeat(env, changes):
    for key, value in changes.items():
        setattr(env.row, key, value)
    with pytest.raises(BrokerFailure):
        await env.node.heartbeat()
    env.renewed.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize(
    "changes",
    [
        {"is_active": False},
        {"user_id": uuid4()},
        {"impersonator_user_id": uuid4()},
        {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
    ],
)
async def test_session_revocation_or_expiry_withdraws_the_running_node(env, changes):
    for key, value in changes.items():
        setattr(env.session, key, value)
    with pytest.raises(BrokerFailure, match="authority_revoked"):
        await env.node.heartbeat()
    env.renewed.assert_not_awaited()


@pytest.mark.security
async def test_membership_or_management_loss_withdraws_the_running_node(env):
    env.member.return_value = None
    with pytest.raises(BrokerFailure, match="authority_revoked"):
        await env.node.heartbeat()
    env.member.return_value = owner_context(env.row, role="viewer")
    with pytest.raises(BrokerFailure, match="authority_revoked"):
        await env.node.heartbeat()
    env.renewed.assert_not_awaited()


async def test_revocation_cleanup_survives_removal_of_the_initiating_member(env):
    env.row.desired_state = "revoked"
    job = node_job(env.row, mode="logout")
    await authority.authorize_node(env.db, job, env.row)
    env.get_session.assert_not_awaited()
    env.member.assert_not_awaited()


@pytest.mark.security
async def test_a_lost_lease_cannot_persist_another_processes_node_state(env):
    env.row.lease_id = uuid4()
    with pytest.raises(BrokerFailure, match="lease_lost"):
        await env.node.persist(StateFrame(type="state", sequence=1, state={"key": "YQ=="}))
    env.saved.assert_not_awaited()


async def test_persistence_encrypts_and_commits_the_snapshot_before_returning(env):
    frame = StateFrame(type="state", sequence=1, state={"key": "c3ludGhldGljLWtleQ=="})
    await env.node.persist(frame)
    assert env.events == ["commit"]
    assert "c3ludGhldGljLWtleQ==" not in env.row.state_payload
    decoded = json.loads(
        unseal(
            env.row.state_payload,
            scope=connection_scope(env.row),
            key_version=env.row.secret_key_version,
        )
    )
    assert decoded == {"state": {"key": "c3ludGhldGljLWtleQ=="}}
    assert env.row.state_sequence == 1
    assert env.saved.call_args.kwargs["lease_id"] == env.lease_id
    assert env.saved.call_args.kwargs["expected_policy_generation"] == env.job.policy_generation


@pytest.mark.security
async def test_first_node_write_uses_the_current_vault_key_after_the_old_one_was_retired(
    env, monkeypatch
):
    monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {2: "synthetic-new-master-key-" + "b" * 32})
    assert env.row.secret_key_version == 1 and env.row.state_payload is None
    await env.node.observe(
        StatusFrame(
            type="status",
            backend_state="NeedsLogin",
            auth_url="https://login.tailscale.com/a/synthetic-new-key",
        )
    )
    assert env.row.secret_key_version == 2
    await env.node.persist(StateFrame(type="state", sequence=1, state={"key": "YQ=="}))
    assert env.row.secret_key_version == 2
    assert json.loads(
        unseal(env.row.state_payload, scope=connection_scope(env.row), key_version=2)
    ) == {"state": {"key": "YQ=="}}
    assert unseal(env.row.login_payload, scope=connection_scope(env.row), key_version=2).endswith(
        "synthetic-new-key"
    )


@pytest.mark.security
async def test_a_failed_fenced_update_cannot_be_reported_as_persisted(env):
    env.saved.side_effect = None
    env.saved.return_value = None
    with pytest.raises(BrokerFailure, match="lease_lost"):
        await env.node.persist(StateFrame(type="state", sequence=1, state={}))
    assert env.events == []


@pytest.mark.security
async def test_login_status_is_sealed_and_never_copied_to_public_metadata(env):
    url = "https://login.tailscale.com/a/synthetic-login"
    await env.node.observe(StatusFrame(type="status", backend_state="NeedsLogin", auth_url=url))
    assert env.row.auth_state == "sign_in_required"
    assert url not in env.row.login_payload
    assert unseal(env.row.login_payload, scope=connection_scope(env.row)) == url
    assert url not in repr(env.row)


async def test_device_approval_and_key_expiry_clear_the_login_link_without_claiming_readiness(env):
    env.row.login_payload = "old-encrypted-link"
    await env.node.observe(StatusFrame(type="status", backend_state="NeedsMachineAuth"))
    assert env.row.auth_state == "approval_required"
    assert env.row.login_payload is None
    await env.node.observe(StatusFrame(type="status", backend_state="Running", key_expired=True))
    assert env.row.auth_state == "expired"


async def test_status_refresh_never_offers_a_new_login_link(env):
    node = runtime.NodeSession(node_job(env.row, mode="status"), env.lease_id)
    await node.observe(
        StatusFrame(
            type="status",
            backend_state="NeedsLogin",
            auth_url="https://login.tailscale.com/a/new-login",
        )
    )
    assert env.row.auth_state == "sign_in_required"
    assert env.row.login_payload is None


@pytest.mark.security
@pytest.mark.parametrize(
    "field,value", [("node_id", "different-node"), ("tailnet_name", "different-tailnet")]
)
async def test_an_enrolled_connection_cannot_silently_adopt_another_identity(env, field, value):
    env.row.node_id = "expected-node"
    env.row.tailnet_name = "expected-tailnet"
    data = {"node_id": "expected-node", "tailnet_name": "expected-tailnet", field: value}
    with pytest.raises(BrokerFailure, match="identity_changed"):
        await env.node.observe(StatusFrame(type="status", backend_state="Running", **data))
    env.saved.assert_not_awaited()


async def test_success_keeps_the_identity_but_releases_compute_and_enrollment_material(
    env, monkeypatch
):
    async def run(_self, *, callbacks, state, **_kwargs):
        assert state.wire_state() == {}
        await callbacks.persist(StateFrame(type="state", sequence=1, state={"key": "YQ=="}))
        await callbacks.observe(
            StatusFrame(
                type="status",
                backend_state="Running",
                node_id="stable-node",
                tailnet_name="my-tailnet",
                peers=[{"id": "stable-peer", "online": True, "ips": ["100.90.0.2"]}],
            )
        )
        return "ready"

    monkeypatch.setattr(runtime.TailscaleBroker, "run", run)
    await runtime.run_node(env.job)
    assert env.row.auth_state == "authenticated"
    assert env.row.node_id == "stable-node"
    assert env.row.peers[0]["id"] == "stable-peer"
    assert env.row.runtime_state == "stopped" and env.row.lease_id is None
    assert env.row.enrollment_expires_at is None and env.row.login_payload is None
    assert env.row.state_payload is not None
    assert env.row.policy_generation == env.job.policy_generation


async def test_a_broker_failure_pauses_authority_but_preserves_the_enrolled_key(env, monkeypatch):
    env.row.state_payload = seal(
        '{"state":{"key":"YQ=="}}', scope=connection_scope(env.row)
    ).ciphertext
    original = env.row.state_payload
    monkeypatch.setattr(
        runtime.TailscaleBroker,
        "run",
        AsyncMock(side_effect=BrokerFailure("control_plane_unavailable")),
    )
    with pytest.raises(BrokerFailure, match="control_plane_unavailable"):
        await runtime.run_node(env.job)
    assert env.row.desired_state == "paused"
    assert env.row.auth_state == "error"
    assert env.row.last_error_code == "control_plane_unavailable"
    assert env.row.state_payload == original
    assert env.row.lease_id is None and env.row.login_payload is None


@pytest.mark.security
async def test_a_superseded_job_never_opens_the_broker_or_overwrites_new_work(env, monkeypatch):
    env.row.policy_generation += 1
    env.row.lease_id = uuid4()
    run = AsyncMock()
    monkeypatch.setattr(runtime.TailscaleBroker, "run", run)
    await runtime.run_node(env.job)
    assert env.row.runtime_state == "starting"
    run.assert_not_awaited()
    env.saved.assert_not_awaited()
    env.settled.assert_not_awaited()


async def test_logout_scrubs_local_state_and_reports_manual_remote_removal(env, monkeypatch):
    env.row.desired_state = "revoked"
    env.row.cleanup_state = "pending"
    env.row.state_payload = seal(
        '{"state":{"key":"YQ=="}}', scope=connection_scope(env.row)
    ).ciphertext
    job = node_job(env.row, mode="logout")
    monkeypatch.setattr(runtime.TailscaleBroker, "run", AsyncMock(return_value="logged_out"))
    await runtime.run_node(job)
    assert env.row.state_payload is None
    assert env.row.cleanup_state == "manual"
    assert env.row.auth_state == "not_connected"
    assert env.row.last_error_code is None
    assert env.row.lease_id is None


async def test_terminal_failure_before_claim_stops_the_pending_enrollment(env, monkeypatch):
    env.row.lease_id = env.row.lease_expires_at = None
    monkeypatch.setattr(settings, "TAILSCALE_ENABLED", False)
    with pytest.raises(BrokerFailure, match="runtime_unavailable"):
        await runtime.run_node(env.job)
    assert env.row.desired_state == "paused" and env.row.runtime_state == "stopped"
    assert env.row.last_error_code == "runtime_unavailable"


@pytest.mark.security
async def test_settling_an_old_attempt_cannot_clear_a_new_attempt_in_the_same_generation(env):
    env.row.enrollment_id = uuid4()
    await lifecycle.settle_ended(env.job, "runtime_failed")
    env.settled.assert_not_awaited()


@pytest.mark.security
async def test_untrusted_queue_error_details_never_become_a_public_status(env):
    env.row.lease_id = env.row.lease_expires_at = None
    await lifecycle.settle_ended(env.job, "provider error contains private-token")
    assert env.row.last_error_code == "runtime_failed"
    assert "private-token" not in repr(env.row)


async def test_recovery_never_restarts_an_expired_login(env, monkeypatch):
    env.row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    env.row.enrollment_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    monkeypatch.setattr(
        network_connection_repo,
        "list_recovery_candidates",
        AsyncMock(return_value=[(env.row.organization_id, env.row.id)]),
    )
    assert await lifecycle.recover() == 1
    assert env.row.desired_state == "paused"
    assert env.row.last_error_code == "enrollment_expired"
    assert env.row.login_payload is None
    env.claimed.assert_not_awaited()


async def test_recovery_leaves_still_queued_or_live_work_alone(env, monkeypatch):
    monkeypatch.setattr(
        network_connection_repo,
        "list_recovery_candidates",
        AsyncMock(return_value=[(env.row.organization_id, env.row.id)]),
    )
    assert await lifecycle.recover() == 0
    env.row.lease_id = env.row.lease_expires_at = None
    assert await lifecycle.recover() == 0
    env.settled.assert_not_awaited()


async def test_disabled_runtime_does_not_leave_revoked_keys_retained_forever(env, monkeypatch):
    from app.services.network_connections import NetworkConnectionService

    env.row.desired_state = "revoked"
    env.row.cleanup_state = "pending"
    env.row.state_payload = "encrypted-node-state"
    env.row.lease_id = env.row.lease_expires_at = None
    monkeypatch.setattr(NetworkConnectionService, "available", staticmethod(lambda: False))
    monkeypatch.setattr(
        network_connection_repo,
        "list_recovery_candidates",
        AsyncMock(return_value=[(env.row.organization_id, env.row.id)]),
    )
    assert await lifecycle.recover() == 1
    assert env.row.state_payload is None
    assert env.row.cleanup_state == "manual"
    assert env.row.last_error_code == "runtime_unavailable"
