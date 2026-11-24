"""The database keeps personal network identity tied to its owner."""

import uuid

import anyio
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.db.models.network_connection import NetworkConnection
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import network_connection_repo

pytestmark = pytest.mark.anyio


async def _org(db) -> tuple[Organization, User]:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="owner")
    )
    await db.flush()
    return org, user


async def _member(db, org: Organization) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="member")
    )
    await db.flush()
    return user


async def test_personal_connection_requires_private_visibility_and_an_owner(db):
    org, owner = await _org(db)
    db.add(
        NetworkConnection(
            organization_id=org.id,
            owner_user_id=owner.id,
            scope="user",
            visibility="org",
            name="Laptop",
        )
    )

    with pytest.raises(IntegrityError):
        await db.flush()


async def test_deleting_owner_cannot_orphan_personal_runtime_identity(db):
    org, _creator = await _org(db)
    owner = await _member(db, org)
    db.add(
        NetworkConnection(
            organization_id=org.id,
            owner_user_id=owner.id,
            scope="user",
            visibility="private",
            name="Laptop",
            desired_state="active",
            state_payload="vault-sealed-state",
        )
    )
    await db.flush()

    await db.delete(owner)
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_expired_lease_cannot_write_after_it_expires_in_an_open_transaction(db):
    """A transaction timestamp must not extend a lease past its wall-clock expiry."""
    org, owner = await _org(db)
    connection = NetworkConnection(
        organization_id=org.id,
        owner_user_id=owner.id,
        scope="user",
        visibility="private",
        name="Laptop",
        desired_state="active",
    )
    db.add(connection)
    await db.flush()
    lease_id = uuid.uuid4()

    # The transaction began while creating the owner and organization. Give the
    # lease a short interval from PostgreSQL's live clock, then wait until it has
    # expired before calling the fenced writer in the same transaction.
    await db.execute(
        update(NetworkConnection)
        .where(NetworkConnection.id == connection.id)
        .values(
            lease_id=lease_id,
            lease_expires_at=func.clock_timestamp() + text("interval '1 second'"),
        )
    )
    remaining = await db.scalar(
        select(NetworkConnection.lease_expires_at - func.clock_timestamp()).where(
            NetworkConnection.id == connection.id
        )
    )
    assert remaining is not None and remaining.total_seconds() > 0
    await anyio.sleep(remaining.total_seconds() + 0.05)

    updated = await network_connection_repo.update(
        db,
        organization_id=org.id,
        connection_id=connection.id,
        changes={"node_id": "late-write"},
        lease_id=lease_id,
        expected_policy_generation=connection.policy_generation,
    )

    assert updated is None
    await db.refresh(connection)
    assert connection.node_id is None


async def test_inactive_settlement_uses_live_clock_after_transaction_started(db):
    """A long-lived transaction can settle a lease once its actual expiry passes."""
    org, owner = await _org(db)
    connection = NetworkConnection(
        organization_id=org.id,
        owner_user_id=owner.id,
        scope="user",
        visibility="private",
        name="Laptop",
        desired_state="active",
    )
    db.add(connection)
    await db.flush()
    await db.execute(
        update(NetworkConnection)
        .where(NetworkConnection.id == connection.id)
        .values(
            lease_id=uuid.uuid4(),
            lease_expires_at=func.clock_timestamp() + text("interval '1 second'"),
        )
    )
    remaining = await db.scalar(
        select(NetworkConnection.lease_expires_at - func.clock_timestamp()).where(
            NetworkConnection.id == connection.id
        )
    )
    assert remaining is not None and remaining.total_seconds() > 0
    await anyio.sleep(remaining.total_seconds() + 0.05)

    settled = await network_connection_repo.settle_inactive(
        db,
        organization_id=org.id,
        connection_id=connection.id,
        expected_policy_generation=connection.policy_generation,
        changes={"desired_state": "paused"},
    )

    assert settled is not None
    assert settled.desired_state == "paused"
    assert settled.lease_id is None
