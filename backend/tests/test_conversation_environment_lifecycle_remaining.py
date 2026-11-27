"""Real producer admission distinguishes lazy first use from manual provisioning."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.db.models.agent_run import AgentRun
from app.services import conversation_environments as lifecycle
from tests.test_conversation_environment_lifecycle import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_real_producer_admission_does_not_enqueue_a_competing_manual_provision(
    case, monkeypatch
):
    producer = AgentRun(
        id=uuid4(),
        user_id=case.ctx.user_id,
        organization_id=case.ctx.organization_id,
        agent_id=case.row.agent_id,
        conversation_id=case.row.conversation_id,
        agent_version_id=case.row.agent_version_id,
        status="running",
        surface="web",
    )
    monkeypatch.setattr(lifecycle.run_repo, "get_run", AsyncMock(return_value=producer))
    lifecycle.environments.latest.return_value = None
    read = await case.service.ensure(
        case.ctx, case.row.conversation_id, "browser", case.request, producer_run_id=producer.id
    )
    assert read.state == "starting"
    tasks = [call.args[1] for call in lifecycle.enqueue.await_args_list]
    assert lifecycle.PROVISION_CONVERSATION_ENVIRONMENT not in tasks
    assert lifecycle.CLEANUP_CONVERSATION_ENVIRONMENT in tasks


async def test_expiry_without_provider_handle_is_idempotent_and_needs_no_cleanup(case):
    case.row.state = "expired"
    revision, expiry = case.row.revision, case.row.expires_at
    await case.service.expire(case.row)
    assert (case.row.revision, case.row.expires_at) == (revision, expiry)
    lifecycle.enqueue.assert_not_awaited()


async def test_conversation_lifetime_ignores_old_producer_pin_without_losing_authority(case):
    case.row.state = "ready"
    case.row.source_run_id = uuid4()
    case.row.resource_ciphertext, case.row.resource_key_version = "sealed", 1
    case.service.resource = lambda _row, _org: case.resource
    _, configured, retained = await case.service.live(
        case.ctx, case.row.conversation_id, case.row.id, "agent"
    )
    assert configured.authority.producer_run_id is None
    assert retained == case.resource


async def test_sweep_retires_admission_that_never_acquired_a_physical_key(case):
    case.row.resource_key = None
    case.row.expires_at = datetime.now(UTC)
    lifecycle.environments.sweep_candidates.return_value = [case.row]
    await case.service.sweep()
    assert case.row.state == "expired"
    lifecycle.environments.driver.assert_not_awaited()
