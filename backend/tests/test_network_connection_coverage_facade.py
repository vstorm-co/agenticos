"""Administrative lifecycle operations preserve cleanup and refusal semantics."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.services.network_connections import NetworkConnectionService, facade, lifecycle, runtime
from app.worker.tasks import network_tasks
from tests.network_connection_fixtures import node_job
from tests.test_network_connection_service import env as env

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "enabled,binary,expected", [(False, True, False), (True, False, False), (True, True, True)]
)
def test_availability_requires_both_the_feature_and_an_executable(
    monkeypatch: pytest.MonkeyPatch, enabled: bool, binary: bool, expected: bool
) -> None:
    monkeypatch.setattr(settings, "TAILSCALE_ENABLED", enabled)
    monkeypatch.setattr(facade.TailscaleBroker, "available", lambda _self: binary)
    assert NetworkConnectionService.available() is expected


async def test_pausing_a_revoked_connection_is_refused(env: SimpleNamespace) -> None:
    env.row.desired_state = "revoked"
    with pytest.raises(BadRequestError, match="revoked"):
        await env.service.pause(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    env.update.assert_not_awaited()


async def test_pausing_an_already_paused_connection_does_not_advance_its_generation(
    env: SimpleNamespace,
) -> None:
    result = await env.service.pause(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    assert result.policy_generation == 1
    env.update.assert_not_awaited()
    env.audited.assert_not_awaited()


async def test_pause_settles_a_stale_runtime_in_the_same_request(env: SimpleNamespace) -> None:
    env.row.runtime_state = "running"
    result = await env.service.pause(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    assert result.runtime_state == "stopped"
    assert env.row.lease_id is None
    env.settle.assert_awaited_once()


async def test_member_cleanup_skips_connections_already_revoked(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.row.desired_state = "revoked"
    monkeypatch.setattr(env.repo, "has_personal_for_member", AsyncMock(return_value=True))
    monkeypatch.setattr(env.repo, "list_personal_for_member", AsyncMock(return_value=[env.row]))
    assert (
        await env.service.revoke_member(
            organization_id=env.row.organization_id, user_id=env.ctx.user_id
        )
        == 0
    )
    env.update.assert_not_awaited()


async def test_account_deletion_reports_a_row_that_survived_final_cleanup(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(env.repo, "list_personal_for_user", AsyncMock(return_value=[]))
    monkeypatch.setattr(env.repo, "delete_inactive_personal", AsyncMock(return_value=1))
    with pytest.raises(ConflictError, match="finishing"):
        await env.service.prepare_user_deletion(env.ctx.user_id)


async def test_already_revoked_metadata_can_be_erased_from_an_organization(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.row.desired_state = "revoked"
    monkeypatch.setattr(env.repo, "list_for_organization", AsyncMock(return_value=[env.row]))
    await env.service.prepare_organization_deletion(env.row.organization_id)
    env.update.assert_not_awaited()
    assert env.row.runtime_state == "stopped"


async def test_a_connection_removed_during_change_is_reported_as_missing(
    env: SimpleNamespace,
) -> None:
    env.update.side_effect = None
    env.update.return_value = None
    with pytest.raises(NotFoundError):
        await env.service._change(env.row, {"name": "New name"})
    env.queued.assert_not_awaited()


async def test_revocation_keeps_a_live_lease_until_its_writer_stops(
    env: SimpleNamespace,
) -> None:
    env.row.lease_id = env.row.id
    env.row.lease_expires_at = datetime.now(UTC) + timedelta(seconds=15)
    result = await env.service.revoke(env.ctx, connection_id=env.row.id, session_id=env.session_id)
    assert result.desired_state == "revoked"
    assert result.cleanup_state == "complete"
    assert env.row.lease_id == env.row.id


async def test_worker_entrypoints_pass_the_job_and_failure_to_the_lifecycle(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = node_job(env.row)
    run = AsyncMock()
    settle = AsyncMock()
    recover = AsyncMock(return_value=7)
    monkeypatch.setattr(runtime, "run_node", run)
    monkeypatch.setattr(lifecycle, "settle_ended", settle)
    monkeypatch.setattr(lifecycle, "recover", recover)
    await network_tasks.run_connection(job)
    await network_tasks.settle_connection(job, "timeout")
    assert await network_tasks.sweep_connections() == 7
    run.assert_awaited_once_with(job)
    settle.assert_awaited_once_with(job, "timeout")
