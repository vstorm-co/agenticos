"""Lease admission remains immutable across races, competing owners and revocation."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import AlreadyExistsError, AuthorizationError
from app.services import conversation_environment_project_files as files
from app.services import project_filesystem_bindings as module
from app.worker.jobs import ConversationEnvironmentPayload
from tests.test_project_filesystem_bindings import binding as binding

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def env(binding, monkeypatch):
    row = SimpleNamespace(id=uuid4(), expires_at=datetime.now(UTC) + timedelta(minutes=15))
    payload = ConversationEnvironmentPayload(
        environment_id=row.id, organization_id=binding.rows.actor.organization_id, revision=1
    )
    admission = AsyncMock(return_value=(row, binding.rows.authority))
    monkeypatch.setattr(files, "starting", admission)
    previous = AsyncMock(return_value=None)
    monkeypatch.setattr(module.binding_repo, "environment_lease", previous)
    return SimpleNamespace(
        binding=binding,
        row=row,
        payload=payload,
        admission=admission,
        previous=previous,
        project_id=binding.rows.lease.project_id,
        generation=binding.rows.lease.workspace_generation,
    )


async def issue(env):
    binding = env.binding
    return await binding.service.issue_environment_lease(
        binding_id=binding.rows.binding.id,
        payload=env.payload,
        attempt=2,
        project_id=env.project_id,
        generation=env.generation,
    )


@pytest.mark.parametrize("removed", [False, True])
async def test_binding_revoked_or_deleted_after_authority_refuses_before_lease_creation(
    env, removed
):
    first = env.binding.rows.binding
    changed = SimpleNamespace(revoked_at=datetime.now(UTC))
    env.binding.lookup.side_effect = [first, None if removed else changed]
    with pytest.raises(AuthorizationError, match="binding was revoked"):
        await issue(env)
    env.binding.create.assert_not_awaited()


async def test_missing_owner_cannot_gain_a_manual_filesystem_lease(env):
    authority = env.binding.rows.authority
    env.admission.return_value = (
        env.row,
        authority.model_copy(
            update={
                "actor": authority.actor.__class__(
                    organization_id=authority.actor.organization_id, user_id=None, role="owner"
                )
            }
        ),
    )
    with pytest.raises(AuthorizationError, match="owner is unavailable"):
        await issue(env)
    env.binding.create.assert_not_awaited()


@pytest.mark.parametrize(
    "changed", ["revoked_at", "project_id", "workspace_generation", "actor_id", "authority_json"]
)
async def test_existing_environment_path_never_reassigns_its_immutable_admission(env, changed):
    row = env.binding.rows.lease
    row.environment_id = env.row.id
    if changed == "revoked_at":
        row.revoked_at = datetime.now(UTC)
    elif changed == "authority_json":
        row.authority_json = env.binding.rows.authority.model_copy(
            update={"granted_scopes": frozenset({"projects:read"})}
        ).model_dump_json()
    else:
        setattr(row, changed, uuid4())
    env.previous.return_value = row
    with pytest.raises(AuthorizationError, match="cannot be reassigned"):
        await issue(env)
    env.binding.create.assert_not_awaited()


@pytest.mark.parametrize("changed", ["run_id", "project_id", "workspace_generation", "actor_id"])
async def test_environment_cannot_join_an_unrelated_active_mount(env, changed):
    row = env.binding.rows.lease
    setattr(row, changed, None if changed == "run_id" else uuid4())
    env.binding.live.return_value = [row]
    with pytest.raises(AlreadyExistsError, match="another Project mount"):
        await issue(env)
    env.binding.create.assert_not_awaited()


async def test_run_can_join_an_existing_same_person_environment_without_reviving_it(binding):
    row = binding.rows.lease
    row.run_id = None
    row.environment_id = uuid4()
    binding.live.return_value = [row]
    result = await binding.service.issue_lease(
        binding_id=binding.rows.binding.id,
        project_id=row.project_id,
        generation=row.workspace_generation,
        run_id=binding.rows.run.id,
        authority=binding.rows.authority,
    )
    assert result.id != row.id
    assert row.run_id is None
    assert binding.create.await_args.kwargs["lease"].run_id == binding.rows.run.id
