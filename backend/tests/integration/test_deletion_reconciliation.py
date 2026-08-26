"""Deleting a user or an org no longer 500s on a cascade the schema forbids.

Three `ON DELETE SET NULL`/RESTRICT cascades each drove precisely the write a
CHECK constraint rejects, so the delete raised inside the database and surfaced
as a 500 (#9). Each is reconciled in the service before the row goes: a private
secret is promoted to the org, a personal org is removed with its owner, and an
org-scoped collection is deleted - table and all - rather than orphaned.

Integration rather than unit because the whole point is what the database does
to neighbouring rows when one is deleted, which a mock cannot show.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import settings as app_settings
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.user import User
from app.repositories import member_repo
from app.services.organization import OrganizationService
from app.services.rag.vectorstore import PgVectorStore
from app.services.user import UserService

pytestmark = pytest.mark.anyio


def _user(email: str | None = None) -> User:
    return User(
        id=uuid.uuid4(),
        email=email or f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )


async def _member(db, org_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None:
    db.add(OrganizationMember(id=uuid.uuid4(), organization_id=org_id, user_id=user_id, role=role))
    await db.flush()


async def _org(db, creator: User, *, is_personal: bool = False) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        is_personal=is_personal,
        created_by_user_id=creator.id,
    )
    db.add(org)
    await db.flush()
    await _member(db, org.id, creator.id, "owner")
    return org


def _org_collection(org_id: uuid.UUID, collection_name: str) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name="Shared docs",
        scope=KBScope.ORG.value,
        collection_name=collection_name,
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        organization_id=org_id,
        visibility="org",
    )


def _private_secret(org_id: uuid.UUID, owner_id: uuid.UUID) -> OrganizationSecret:
    return OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="mine",
        purpose="openai",
        visibility="private",
        owner_user_id=owner_id,
        kind="api_key",
        sealed_secret="{}",
        hint="1234",
    )


class TestDeletingAUser:
    async def test_a_normally_registered_user_can_be_deleted(self, db):
        """Every signup creates a personal org whose creator FK is RESTRICT, so a
        bare `DELETE users` never worked for a real account (#9)."""
        user = _user()
        db.add(user)
        await db.flush()
        org = await _org(db, user, is_personal=True)

        await UserService(db).delete(user.id)

        assert await db.get(User, user.id) is None
        assert await db.get(Organization, org.id) is None

    async def test_deleting_a_member_promotes_their_private_secret_to_the_org(self, db):
        """`ck_secret_private_needs_owner` forbids the ownerless-private row the
        `SET NULL` would otherwise leave; the key stays reachable by the org."""
        creator = _user()
        db.add(creator)
        await db.flush()
        org = await _org(db, creator)

        leaver = _user()
        db.add(leaver)
        await db.flush()
        await _member(db, org.id, leaver.id, "member")
        secret = _private_secret(org.id, leaver.id)
        db.add(secret)
        await db.flush()

        await UserService(db).delete(leaver.id)

        await db.refresh(secret)
        assert secret.owner_user_id is None
        assert secret.visibility == "org"

    async def test_deleting_a_user_removes_an_org_scoped_collection_they_owned(self, db):
        """The personal-org teardown runs the same collection cleanup as an org
        delete, with no vector store wired in - the row still has to go."""
        user = _user()
        db.add(user)
        await db.flush()
        org = await _org(db, user, is_personal=True)
        kb = _org_collection(org.id, f"kbnine{uuid.uuid4().hex[:12]}")
        db.add(kb)
        await db.flush()

        await UserService(db).delete(user.id)

        assert await db.get(KnowledgeBase, kb.id) is None
        assert await db.get(Organization, org.id) is None

    async def test_the_sole_owner_of_a_shared_org_is_refused_not_500ed(self, db):
        """A shared org with no other owner has nobody to hand the creator FK to,
        so the delete is a clean refusal rather than a foreign-key 500."""
        from app.core.exceptions import BadRequestError

        owner = _user()
        db.add(owner)
        await db.flush()
        await _org(db, owner)  # shared: is_personal defaults to False

        with pytest.raises(BadRequestError):
            await UserService(db).delete(owner.id)

        assert await db.get(User, owner.id) is not None

    async def test_a_shared_org_is_handed_to_another_owner(self, db):
        """When a co-owner exists the org survives, reattributed to them."""
        creator = _user()
        heir = _user()
        db.add_all([creator, heir])
        await db.flush()
        org = await _org(db, creator)
        await _member(db, org.id, heir.id, "owner")

        await UserService(db).delete(creator.id)

        await db.refresh(org)
        assert org.created_by_user_id == heir.id
        assert await db.get(User, creator.id) is None

    async def test_deleting_the_sole_owner_of_an_org_they_did_not_create_is_refused(self, db):
        """Ownership moves without the creator FK, so a user can be the only Owner
        of an org they did not create. Deleting them would cascade that last owner
        membership away and orphan the org - refused, not silently orphaned, the
        way the created-org path already refuses a lone owner (#1117)."""
        from app.core.exceptions import BadRequestError

        creator = _user()
        db.add(creator)
        await db.flush()
        org = await _org(db, creator)  # creator is owner and creator
        owner = _user()
        db.add(owner)
        await db.flush()
        await _member(db, org.id, owner.id, "owner")
        # Demote the creator, leaving `owner` the sole Owner but not the creator.
        creator_membership = await member_repo.get(db, organization_id=org.id, user_id=creator.id)
        assert creator_membership is not None
        await member_repo.update_role(db, creator_membership, role="member")

        with pytest.raises(BadRequestError):
            await UserService(db).delete(owner.id)

        assert await db.get(User, owner.id) is not None

    async def test_deleting_a_non_creator_owner_beside_a_co_owner_succeeds(self, db):
        """With another owner present the org keeps one when this membership
        cascades, so a non-creator co-owner deletes cleanly rather than being
        refused (#1117)."""
        creator = _user()
        db.add(creator)
        await db.flush()
        org = await _org(db, creator)  # creator: owner and creator
        owner = _user()
        db.add(owner)
        await db.flush()
        await _member(db, org.id, owner.id, "owner")  # a second owner

        await UserService(db).delete(owner.id)

        assert await db.get(User, owner.id) is None
        assert await db.get(Organization, org.id) is not None


class TestDeletingAnOrg:
    async def test_it_drops_org_scoped_collections_and_their_vector_tables(
        self, engine: AsyncEngine
    ) -> None:
        """The org-scope check turns a `SET NULL` on delete into a 500; the row is
        removed explicitly, and the real vector table goes with it (#9)."""
        store = PgVectorStore(
            settings=app_settings.rag,
            embedding_service=MagicMock(),
            resolver=MagicMock(),
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbnine{uuid.uuid4().hex[:12]}"
        table = store._table(collection)
        try:
            async with factory() as s:
                user = _user()
                s.add(user)
                await s.flush()
                org = await _org(s, user)
                s.add(_org_collection(org.id, collection))
                await s.execute(text(f"CREATE TABLE {table} (id int)"))
                await s.commit()
                org_id = org.id

            async with factory() as s:
                assert (
                    await s.execute(text("SELECT to_regclass(:t)"), {"t": table})
                ).scalar() is not None

            async with factory() as s:
                org = await s.get(Organization, org_id)
                await OrganizationService(s, vector_store=store).purge(org)
                await s.commit()

            async with factory() as s:
                remaining = await s.execute(
                    select(KnowledgeBase).where(KnowledgeBase.organization_id == org_id)
                )
                assert remaining.scalars().all() == []
                assert (
                    await s.execute(text("SELECT to_regclass(:t)"), {"t": table})
                ).scalar() is None
                assert await s.get(Organization, org_id) is None
        finally:
            await store.aclose()

    async def test_a_personal_collection_survives_its_orgs_deletion(
        self, engine: AsyncEngine
    ) -> None:
        """A personal collection merely carrying the org's id is detached by the
        `SET NULL`, not deleted - its scope permits an absent org."""
        store = PgVectorStore(
            settings=app_settings.rag,
            embedding_service=MagicMock(),
            resolver=MagicMock(),
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as s:
                user = _user()
                s.add(user)
                await s.flush()
                org = await _org(s, user)
                personal = KnowledgeBase(
                    id=uuid.uuid4(),
                    name="My notes",
                    scope=KBScope.PERSONAL.value,
                    collection_name=f"kbnine{uuid.uuid4().hex[:12]}",
                    embedding_model="text-embedding-3-small",
                    embedding_dim=1536,
                    organization_id=org.id,
                    owner_user_id=user.id,
                    visibility="private",
                )
                s.add(personal)
                await s.commit()
                org_id, kb_id = org.id, personal.id

            async with factory() as s:
                org = await s.get(Organization, org_id)
                await OrganizationService(s, vector_store=store).purge(org)
                await s.commit()

            async with factory() as s:
                surviving = await s.get(KnowledgeBase, kb_id)
                assert surviving is not None
                assert surviving.organization_id is None
        finally:
            await store.aclose()


class TestConcurrentInsertsDuringDeletion:
    """The reconcile is check-then-act; a row inserted between the two would 500.

    #9 reconciled the FK/CHECK cascades in the service, but listing (or promoting)
    and then deleting is a check-then-act with no row lock, so a concurrent insert
    reopens the exact 500 #9 closed. The teardown now takes FOR UPDATE on the row
    it is about, so a concurrent insert - which takes FOR KEY SHARE on the same
    row through its own FK - waits, and the reconcile sees every child there is
    (#1115). Deterministic on purpose: the insert is held open (uncommitted) so
    the delete blocks on the lock rather than racing it.
    """

    async def test_an_org_scoped_collection_inserted_during_an_org_delete(
        self, engine: AsyncEngine
    ) -> None:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as setup:
            user = _user()
            setup.add(user)
            await setup.flush()
            org = await _org(setup, user)
            await setup.commit()
            org_id = org.id

        session_a = factory()
        delete_task: asyncio.Task[None] | None = None
        try:
            # A member inserts a new org-scoped collection and holds it open:
            # FOR KEY SHARE on the org row, uncommitted.
            session_a.add(_org_collection(org_id, f"kbrace{uuid.uuid4().hex[:12]}"))
            await session_a.flush()

            async def purge_org() -> None:
                async with factory() as session_b:
                    org = await session_b.get(Organization, org_id)
                    await OrganizationService(session_b).purge(org)
                    await session_b.commit()

            delete_task = asyncio.create_task(purge_org())
            await asyncio.sleep(0.4)
            assert not delete_task.done()  # A's uncommitted insert holds the delete off

            await session_a.commit()

            await delete_task  # succeeds rather than a ck_knowledge_bases_org_scope_has_org 500
            delete_task = None
        finally:
            if delete_task is not None:
                delete_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await delete_task
            await session_a.close()

        async with factory() as s:
            assert await s.get(Organization, org_id) is None
            remaining = await s.execute(
                select(KnowledgeBase).where(KnowledgeBase.organization_id == org_id)
            )
            assert remaining.scalars().all() == []  # the raced-in collection went too

    async def test_a_private_secret_inserted_during_a_user_delete(
        self, engine: AsyncEngine
    ) -> None:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as setup:
            creator = _user()
            setup.add(creator)
            await setup.flush()
            org = await _org(setup, creator)
            leaver = _user()
            setup.add(leaver)
            await setup.flush()
            await _member(setup, org.id, leaver.id, "member")
            await setup.commit()
            org_id, leaver_id = org.id, leaver.id

        session_a = factory()
        delete_task: asyncio.Task[None] | None = None
        try:
            # A private secret for the leaver, held open: FOR KEY SHARE on the
            # leaver's user row through its owner FK, uncommitted.
            session_a.add(_private_secret(org_id, leaver_id))
            await session_a.flush()

            async def delete_leaver() -> None:
                async with factory() as session_b:
                    await UserService(session_b).delete(leaver_id)
                    await session_b.commit()

            delete_task = asyncio.create_task(delete_leaver())
            await asyncio.sleep(0.4)
            assert not delete_task.done()  # A's uncommitted insert holds the delete off

            await session_a.commit()

            await delete_task  # succeeds rather than a ck_secret_private_needs_owner 500
            delete_task = None
        finally:
            if delete_task is not None:
                delete_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await delete_task
            await session_a.close()

        async with factory() as s:
            assert await s.get(User, leaver_id) is None
            secrets = (
                (
                    await s.execute(
                        select(OrganizationSecret).where(
                            OrganizationSecret.organization_id == org_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert secrets  # the raced-in secret survived, promoted rather than orphaned
            for secret in secrets:
                assert secret.owner_user_id is None
                assert secret.visibility == "org"
