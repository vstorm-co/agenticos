"""Real PostgreSQL preserves issued registrations and rejects stale callback claims."""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import OrganizationMember
from app.repositories import chatgpt_registration as registrations
from app.repositories import member_repo
from app.repositories.personal_data import chatgpt_registrations_of
from app.schemas.personal_data import ChatGPTRegistrationRead
from tests.integration.test_secret_tenant_isolation import _member, _org

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_reconnect_retains_host_and_client_and_invalidates_the_previous_intent(
    db: AsyncSession,
) -> None:
    org, owner = await _org(db, name="ChatGPT")
    other = await _member(db)
    db.add_all(
        [
            OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner"),
            OrganizationMember(organization_id=org.id, user_id=other.id, role="member"),
        ]
    )
    await db.flush()
    host = uuid4()
    first = await registrations.start(db, organization_id=org.id, user_id=owner.id, host_id=host)
    old_generation = first.generation
    assert await registrations.claim_client(
        db,
        organization_id=org.id,
        user_id=owner.id,
        generation=old_generation,
        client_id="registered-client",
    )
    second = await registrations.start(
        db, organization_id=org.id, user_id=owner.id, host_id=uuid4()
    )
    assert second.host_id == host and second.client_id == "registered-client"
    assert second.generation != old_generation
    assert not await registrations.claim_client(
        db,
        organization_id=org.id,
        user_id=owner.id,
        generation=old_generation,
        client_id="late-client",
    )
    assert not await registrations.claim_client(
        db,
        organization_id=org.id,
        user_id=owner.id,
        generation=second.generation,
        client_id="different-client",
    )
    assert (
        await registrations.get(db, organization_id=org.id, user_id=owner.id, locked=True) is second
    )
    assert await registrations.get(db, organization_id=uuid4(), user_id=owner.id) is None
    assert await registrations.get(db, organization_id=org.id, user_id=other.id) is None
    third = await registrations.start(db, organization_id=org.id, user_id=other.id, host_id=host)
    assert third.client_id is None
    exported = await chatgpt_registrations_of(db, owner.id)
    assert len(exported) == 1 and exported[0].user_id == owner.id
    safe = ChatGPTRegistrationRead.model_validate(exported[0]).model_dump_json()
    assert "registered-client" in safe and "generation" not in safe
    assert await chatgpt_registrations_of(db, uuid4()) == []
    member = await member_repo.get(db, organization_id=org.id, user_id=owner.id)
    assert member is not None
    await db.delete(member)
    await db.flush()
    assert await registrations.get(db, organization_id=org.id, user_id=owner.id) is None


async def test_a_registration_cannot_bind_a_user_outside_the_tenant(db: AsyncSession) -> None:
    org, _ = await _org(db, name="ChatGPT")
    other = await _member(db)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await registrations.start(db, organization_id=org.id, user_id=other.id, host_id=uuid4())
