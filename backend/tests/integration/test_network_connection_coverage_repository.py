"""Repository reads and fenced writes against an isolated PostgreSQL database."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import network_connection_repo as repo
from tests.integration.test_network_connection_constraints import _member, _org

pytestmark = pytest.mark.anyio


async def test_creating_personal_and_shared_connections_sets_visibility(db: AsyncSession) -> None:
    org, owner = await _org(db)
    personal = await repo.create(
        db, organization_id=org.id, owner_user_id=owner.id, scope="user", name="Personal"
    )
    shared = await repo.create(
        db, organization_id=org.id, owner_user_id=None, scope="org", name="Shared"
    )
    assert personal.visibility == "private" and personal.desired_state == "paused"
    assert shared.visibility == "org" and shared.auth_state == "not_connected"
    assert (
        await repo.get_by_id(db, organization_id=org.id, connection_id=personal.id, for_update=True)
        is personal
    )
    assert (
        await repo.get_by_id(db, organization_id=org.id, connection_id=shared.id, fresh=True)
        is shared
    )
    with pytest.raises(ValueError, match="owner"):
        await repo.create(
            db, organization_id=org.id, owner_user_id=None, scope="user", name="Invalid"
        )


@pytest.mark.security
async def test_listing_combines_personal_role_and_explicit_grant_visibility(
    db: AsyncSession,
) -> None:
    org, owner = await _org(db)
    other = await _member(db, org)
    personal = await repo.create(
        db, organization_id=org.id, owner_user_id=owner.id, scope="user", name="Mine"
    )
    hidden_personal = await repo.create(
        db, organization_id=org.id, owner_user_id=other.id, scope="user", name="Other"
    )
    shared = await repo.create(
        db, organization_id=org.id, owner_user_id=other.id, scope="org", name="Shared"
    )
    team = await repo.create(
        db, organization_id=org.id, owner_user_id=other.id, scope="org", name="Team"
    )
    team.visibility = "team"
    owned = await repo.create(
        db, organization_id=org.id, owner_user_id=owner.id, scope="org", name="Owned"
    )
    owned.visibility = "private"
    foreign_org, foreign_owner = await _org(db)
    foreign = await repo.create(
        db,
        organization_id=foreign_org.id,
        owner_user_id=foreign_owner.id,
        scope="org",
        name="Foreign",
    )
    await db.flush()
    args = {
        "organization_id": org.id,
        "user_id": owner.id,
        "see_all": False,
        "owner_scope": False,
        "shared_scope": False,
        "team_scope": False,
        "visible_ids": [],
    }
    rows, count = await repo.list_visible(db, **args)
    assert {row.id for row in rows} == {personal.id} and count == 1
    for flag, expected in [("owner_scope", owned), ("shared_scope", shared), ("team_scope", team)]:
        rows, count = await repo.list_visible(db, **(args | {flag: True}))
        assert {row.id for row in rows} == {personal.id, expected.id} and count == 2
    rows, count = await repo.list_visible(
        db, **(args | {"visible_ids": [owned.id, foreign.id, hidden_personal.id]})
    )
    assert {row.id for row in rows} == {personal.id, owned.id} and count == 2
    rows, count = await repo.list_visible(db, **(args | {"see_all": True}), skip=1, limit=2)
    assert count == 4 and len(rows) == 2
    assert foreign.id not in {row.id for row in rows}
    assert await repo.list_visible(db, **(args | {"user_id": None})) == ([], 0)
    for changes in [{"skip": -1}, {"limit": 0}, {"limit": 101}]:
        with pytest.raises(ValueError, match="pagination"):
            await repo.list_visible(db, **args, **changes)
    assert (
        await repo.get_by_id(db, organization_id=foreign_org.id, connection_id=personal.id) is None
    )


@pytest.mark.security
async def test_runtime_observations_require_a_complete_live_fence(db: AsyncSession) -> None:
    org, owner = await _org(db)
    row = await repo.create(
        db, organization_id=org.id, owner_user_id=owner.id, scope="user", name="Node"
    )
    args = {"organization_id": org.id, "connection_id": row.id}
    for changes in [
        {"auth_state": "authenticated"},
        {"state_payload": "sealed"},
        {"login_payload": "sealed"},
        {"runtime_state": "running"},
        {"peers": [{"id": "peer"}]},
        {"last_error_code": "runtime_failed"},
    ]:
        assert await repo.update(db, **args, changes=changes) is None
    with pytest.raises(ValueError, match="Unsupported"):
        await repo.update(db, **args, changes={"owner_user_id": owner.id})
    for fence in [{"lease_id": uuid4()}, {"expected_policy_generation": 1}]:
        with pytest.raises(ValueError, match="both"):
            await repo.update(db, **args, changes={}, **fence)
    assert await repo.update(db, **args, changes={}) is row
    assert (
        await repo.update(
            db, **args, changes={"name": "Renamed", "peers": [], "state_payload": None}
        )
        is row
    )
    assert row.name == "Renamed"
    assert (
        await repo.update(
            db, organization_id=org.id, connection_id=uuid4(), changes={"name": "Gone"}
        )
        is None
    )
    lease_id = uuid4()
    fence = {"lease_id": lease_id, "expected_policy_generation": row.policy_generation}
    row.desired_state = "active"
    await db.flush()
    assert await repo.claim_lease(db, **args, **fence, desired_state="active") is row
    assert await repo.update(db, **args, changes={}, **fence) is row
    assert (
        await repo.update(
            db, **args, changes={"node_id": "stable-node", "state_payload": "sealed"}, **fence
        )
        is row
    )
    assert row.node_id == "stable-node" and row.state_payload == "sealed"
    assert await repo.update(db, **args, changes={}, **(fence | {"lease_id": uuid4()})) is None


@pytest.mark.security
async def test_lease_claim_renewal_and_release_preserve_newer_authority(db: AsyncSession) -> None:
    org, owner = await _org(db)
    row = await repo.create(
        db, organization_id=org.id, owner_user_id=owner.id, scope="user", name="Node"
    )
    row.desired_state = "active"
    row.runtime_state = "starting"
    await db.flush()
    args = {"organization_id": org.id, "connection_id": row.id}
    lease_id = uuid4()
    fence = {
        "lease_id": lease_id,
        "expected_policy_generation": row.policy_generation,
        "desired_state": "active",
    }
    for method in [repo.claim_lease, repo.renew_lease]:
        for seconds in [0, 16]:
            with pytest.raises(ValueError, match="1 to 15"):
                await method(db, **args, **fence, lease_seconds=seconds)
    assert await repo.claim_lease(db, **args, **fence) is row
    assert await repo.claim_lease(db, **args, **(fence | {"lease_id": uuid4()})) is None
    assert await repo.renew_lease(db, **args, **fence)
    assert not await repo.renew_lease(db, **args, **(fence | {"lease_id": uuid4()}))
    assert not await repo.release_lease(db, **args, lease_id=uuid4())
    row.policy_generation += 1
    await db.flush()
    assert await repo.release_lease(db, **args, lease_id=lease_id, expected_policy_generation=1)
    await db.refresh(row)
    assert row.runtime_state == "starting" and row.lease_id is None
    fence["expected_policy_generation"] = row.policy_generation
    assert await repo.claim_lease(db, **args, **fence) is row
    assert await repo.release_lease(db, **args, lease_id=lease_id)
    await db.refresh(row)
    assert row.runtime_state == "stopped"


async def test_owner_and_pending_counts_exclude_revoked_or_expired_work(db: AsyncSession) -> None:
    org, owner = await _org(db)
    row = await repo.create(
        db, organization_id=org.id, owner_user_id=owner.id, scope="user", name="Node"
    )
    assert await repo.lock_quota(db, organization_id=org.id)
    assert not await repo.lock_quota(db, organization_id=uuid4())
    assert await repo.lock_parent(db, organization_id=org.id)
    assert not await repo.lock_parent(db, organization_id=uuid4())
    assert await repo.count_for_owner(db, organization_id=org.id, owner_user_id=None) == 0
    assert await repo.count_for_owner(db, organization_id=org.id, owner_user_id=owner.id) == 1
    assert await repo.count_pending_enrollments(db, organization_id=org.id) == 0
    row.desired_state = "active"
    row.enrollment_id = uuid4()
    row.enrollment_user_id = owner.id
    row.enrollment_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    await db.flush()
    assert await repo.count_pending_enrollments(db, organization_id=org.id) == 1
    assert await repo.count_pending_enrollments(db, organization_id=org.id, user_id=owner.id) == 1
    assert await repo.count_pending_enrollments(db, organization_id=org.id, user_id=uuid4()) == 0
    row.desired_state = "revoked"
    await db.flush()
    assert await repo.count_for_owner(db, organization_id=org.id, owner_user_id=owner.id) == 0


@pytest.mark.security
async def test_erasure_queries_keep_tenant_and_personal_boundaries(db: AsyncSession) -> None:
    org, owner = await _org(db)
    row = await repo.create(
        db, organization_id=org.id, owner_user_id=owner.id, scope="user", name="Personal"
    )
    shared = await repo.create(
        db, organization_id=org.id, owner_user_id=owner.id, scope="org", name="Shared"
    )
    assert await repo.has_personal_for_member(db, organization_id=org.id, user_id=owner.id)
    assert not await repo.has_personal_for_member(db, organization_id=uuid4(), user_id=owner.id)
    for locked in [False, True]:
        assert await repo.list_personal_for_member(
            db, organization_id=org.id, user_id=owner.id, for_update=locked
        ) == [row]
        assert await repo.list_personal_for_user(db, user_id=owner.id, for_update=locked) == [row]
        assert {
            r.id
            for r in await repo.list_for_organization(db, organization_id=org.id, for_update=locked)
        } == {row.id, shared.id}
    assert await repo.delete_inactive_personal(db, user_id=owner.id) == 0
    row.desired_state = "revoked"
    await db.flush()
    assert await repo.delete_inactive_personal(db, user_id=owner.id) == 1
    assert await repo.get_by_id(db, organization_id=org.id, connection_id=shared.id) is shared


@pytest.mark.security
async def test_inactive_settlement_only_redacts_and_never_installs_authority(
    db: AsyncSession,
) -> None:
    org, owner = await _org(db)
    row = await repo.create(
        db, organization_id=org.id, owner_user_id=owner.id, scope="user", name="Node"
    )
    args = {
        "organization_id": org.id,
        "connection_id": row.id,
        "expected_policy_generation": row.policy_generation,
    }
    for changes in [
        {"name": "invalid"},
        {"desired_state": "active"},
        {"auth_state": "authenticated"},
        {"cleanup_state": "pending"},
        {"state_payload": "sealed"},
        {"tailnet_name": "tailnet"},
        {"node_id": "node"},
        {"last_seen_at": datetime.now(UTC)},
    ]:
        with pytest.raises(ValueError):
            await repo.settle_inactive(db, **args, changes=changes)
    row.lease_id = uuid4()
    row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=1)
    await db.flush()
    assert await repo.settle_inactive(db, **args, changes={}) is None
    row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    row.state_payload = "sealed"
    row.login_payload = "login"
    row.node_id = "old-node"
    await db.flush()
    assert (
        await repo.settle_inactive(
            db,
            **args,
            changes={
                "desired_state": "revoked",
                "state_payload": None,
                "node_id": None,
                "tailnet_name": None,
                "last_seen_at": None,
            },
        )
        is row
    )
    assert row.policy_generation == 2 and row.lease_id is None
    assert row.state_payload is None and row.login_payload is None and row.node_id is None
    assert row.runtime_state == "stopped" and row.peers == []


async def test_recovery_candidates_include_stale_work_and_pending_cleanup_only(
    db: AsyncSession,
) -> None:
    org, owner = await _org(db)
    now = datetime.now(UTC)
    stale = await repo.create(
        db, organization_id=org.id, owner_user_id=owner.id, scope="user", name="Stale"
    )
    stale.desired_state = "active"
    stale.runtime_state = "running"
    cleanup = await repo.create(
        db, organization_id=org.id, owner_user_id=owner.id, scope="user", name="Cleanup"
    )
    cleanup.desired_state = "revoked"
    cleanup.cleanup_state = "pending"
    queued = await repo.create(
        db, organization_id=org.id, owner_user_id=owner.id, scope="user", name="Queued"
    )
    queued.desired_state = "active"
    queued.runtime_state = "starting"
    queued.enrollment_id = uuid4()
    queued.enrollment_expires_at = now + timedelta(minutes=10)
    await db.flush()
    assert set(await repo.list_recovery_candidates(db, now=now)) == {
        (org.id, stale.id),
        (org.id, cleanup.id),
    }
    assert len(await repo.list_recovery_candidates(db, now=now, limit=1)) == 1
    for limit in [0, 101]:
        with pytest.raises(ValueError, match="batch"):
            await repo.list_recovery_candidates(db, now=now, limit=limit)
