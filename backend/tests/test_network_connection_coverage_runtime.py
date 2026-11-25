"""Additional stopped-job and lost-lease behavior cases."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import BadRequestError, ConcurrentChangeError, NotFoundError
from app.core.vault import seal
from app.repositories import network_connection_repo
from app.services.network_connections import NetworkConnectionService, lifecycle, runtime
from app.services.network_connections.broker import BrokerFailure
from app.services.network_connections.protocol import StatusFrame
from app.services.network_connections.secrets import connection_scope
from tests.network_connection_fixtures import node_job
from tests.test_network_connection_runtime import env as env

pytestmark = pytest.mark.anyio


@pytest.mark.security
async def test_a_personal_connection_without_an_owner_cannot_open_its_vault(
    env: SimpleNamespace,
) -> None:
    env.row.owner_user_id = None
    with pytest.raises(BadRequestError, match="owner"):
        connection_scope(env.row)


@pytest.mark.security
async def test_failed_renewal_stops_a_previously_admitted_node(env: SimpleNamespace) -> None:
    env.renewed.return_value = False
    with pytest.raises(BrokerFailure, match="lease_lost"):
        await env.node.heartbeat()
    env.saved.assert_not_awaited()


async def test_logout_observations_do_not_replace_the_last_snapshot(env: SimpleNamespace) -> None:
    env.row.desired_state = "revoked"
    node = runtime.NodeSession(node_job(env.row, "logout"), env.lease_id)
    await node.observe(StatusFrame(type="status", backend_state="Running"))
    env.saved.assert_not_awaited()


async def test_incomplete_running_status_does_not_claim_authentication(
    env: SimpleNamespace,
) -> None:
    await env.node.observe(StatusFrame(type="status", backend_state="Running"))
    assert env.row.auth_state == "not_connected"
    assert env.row.runtime_state == "running"
    assert env.row.last_seen_at is not None


async def test_a_superseded_generation_releases_its_lease_without_overwriting_status(
    env: SimpleNamespace,
) -> None:
    env.row.policy_generation += 1
    await env.node.finish("runtime_failed")
    env.saved.assert_not_awaited()
    env.released.assert_awaited_once()
    assert env.row.runtime_state == "starting"


@pytest.mark.security
async def test_failed_claim_never_opens_the_stored_identity(env: SimpleNamespace) -> None:
    env.claimed.side_effect = None
    env.claimed.return_value = None
    with pytest.raises(BrokerFailure, match="lease_lost"):
        await runtime._claim_state(env.job, env.node)
    env.saved.assert_not_awaited()


async def test_malformed_stored_node_state_becomes_a_controlled_failure(
    env: SimpleNamespace,
) -> None:
    env.row.state_payload = seal('{"state":42}', scope=connection_scope(env.row)).ciphertext
    with pytest.raises(BrokerFailure, match="invalid_runtime_response"):
        await runtime._claim_state(env.job, env.node)


async def test_queue_timeout_uses_the_enrollment_expiry_code() -> None:
    assert lifecycle.failure_code("timeout") == "enrollment_expired"


@pytest.mark.parametrize("desired,cleanup", [("active", "pending"), ("revoked", "complete")])
async def test_finished_logout_does_not_settle_an_unrelated_cleanup(
    env: SimpleNamespace, desired: str, cleanup: str
) -> None:
    env.row.desired_state = desired
    env.row.cleanup_state = cleanup
    await lifecycle.settle_ended(node_job(env.row, "logout"), "timeout")
    env.settled.assert_not_awaited()


@pytest.mark.parametrize(
    "error", [ConcurrentChangeError(message="busy"), NotFoundError(message="gone")]
)
async def test_recovery_skips_a_busy_or_removed_parent(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(lifecycle, "hold_parent", AsyncMock(side_effect=error))
    monkeypatch.setattr(
        network_connection_repo,
        "list_recovery_candidates",
        AsyncMock(return_value=[(env.row.organization_id, env.row.id)]),
    )
    assert await lifecycle.recover() == 0
    env.get_row.assert_not_awaited()


async def test_recovery_skips_a_removed_connection(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.get_row.return_value = None
    monkeypatch.setattr(
        network_connection_repo,
        "list_recovery_candidates",
        AsyncMock(return_value=[(env.row.organization_id, env.row.id)]),
    )
    assert await lifecycle.recover() == 0
    env.settled.assert_not_awaited()


async def test_recovery_queues_only_pending_logout_when_runtime_is_available(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.row.desired_state = "revoked"
    env.row.cleanup_state = "pending"
    env.row.state_payload = "encrypted-state"
    env.row.lease_id = env.row.lease_expires_at = None
    queued = AsyncMock()
    monkeypatch.setattr(NetworkConnectionService, "available", staticmethod(lambda: True))
    monkeypatch.setattr(NetworkConnectionService, "_queue", queued)
    monkeypatch.setattr(
        network_connection_repo,
        "list_recovery_candidates",
        AsyncMock(return_value=[(env.row.organization_id, env.row.id)]),
    )
    assert await lifecycle.recover() == 0
    queued.assert_awaited_once_with(env.row, "logout")
    assert env.row.state_payload == "encrypted-state"
    env.settled.assert_not_awaited()


@pytest.mark.parametrize(
    "desired,running,settled",
    [("paused", "running", True), ("paused", "running", False), ("paused", "stopped", False)],
)
async def test_recovery_stops_stale_work_without_changing_paused_authentication(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, desired: str, running: str, settled: bool
) -> None:
    env.row.desired_state = desired
    env.row.runtime_state = running
    env.row.lease_id = env.row.lease_expires_at = None
    env.row.enrollment_expires_at = None
    if not settled:
        env.settled.side_effect = None
        env.settled.return_value = None
    monkeypatch.setattr(
        network_connection_repo,
        "list_recovery_candidates",
        AsyncMock(return_value=[(env.row.organization_id, env.row.id)]),
    )
    assert await lifecycle.recover() == int(settled)
    assert env.row.auth_state == "not_connected"
    if running == "running":
        assert env.settled.call_args.kwargs["changes"] == {
            "desired_state": "paused",
            "last_error_code": "runtime_disconnected",
        }


@pytest.mark.parametrize("node_id,expected", [(None, "complete"), ("known-node", "manual")])
async def test_pending_cleanup_without_keys_records_the_remaining_provider_work(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, node_id: str | None, expected: str
) -> None:
    env.row.desired_state = "revoked"
    env.row.cleanup_state = "pending"
    env.row.node_id = node_id
    env.row.lease_id = env.row.lease_expires_at = None
    monkeypatch.setattr(
        network_connection_repo,
        "list_recovery_candidates",
        AsyncMock(return_value=[(env.row.organization_id, env.row.id)]),
    )
    assert await lifecycle.recover() == 1
    assert env.row.cleanup_state == expected
    assert env.row.last_error_code is None


async def test_failed_logout_erases_local_keys_and_records_manual_provider_cleanup(
    env: SimpleNamespace,
) -> None:
    env.row.desired_state = "revoked"
    env.row.cleanup_state = "pending"
    env.row.state_payload = "encrypted-node-state"
    env.row.login_payload = "encrypted-login"
    env.row.lease_id = env.row.lease_expires_at = None
    await lifecycle.settle_ended(node_job(env.row, "logout"), "runtime_timeout")
    assert env.row.state_payload is None and env.row.login_payload is None
    assert env.row.cleanup_state == "manual"
    assert env.row.auth_state == "not_connected"
    assert env.row.last_error_code == "runtime_timeout"
