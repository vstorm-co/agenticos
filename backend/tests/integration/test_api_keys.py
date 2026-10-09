"""Organization API keys, through the real app against a real database (#1794).

Every refusal a key depends on is asserted here end to end - one-time display,
expiry, revocation, narrowing by the issuer's current role, refusal on the
console's own routes and cross-tenant isolation - because each of them is a join
between a header, a row and a membership that a mocked session would simply agree
with.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthenticationError, BadRequestError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.api_key import ApiKey
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.main import app
from app.schemas.api_key import ApiKeyCreate
from app.services.api_key import ApiKeyService

pytestmark = pytest.mark.anyio

Client = Callable[[], AbstractAsyncContextManager[AsyncClient]]


@pytest.fixture
def client(db: AsyncSession) -> AsyncIterator[Client]:
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_redis] = lambda: MagicMock()

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            yield http

    yield open_client
    app.dependency_overrides.clear()


async def _person(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _organization(db: AsyncSession, owner: User) -> Organization:
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"))
    await db.flush()
    return organization


async def _join(db: AsyncSession, organization: Organization, role: str) -> User:
    person = await _person(db)
    db.add(OrganizationMember(organization_id=organization.id, user_id=person.id, role=role))
    await db.flush()
    return person


async def _issue(
    db: AsyncSession,
    organization: Organization,
    user: User,
    *scopes: Perm,
    role: str = OrgRoleName.OWNER,
    expires_at: datetime | None = None,
) -> str:
    ctx = AuthContext(user_id=user.id, organization_id=organization.id, role=role)
    created = await ApiKeyService(db).create(
        ctx, ApiKeyCreate(name="script", scopes=list(scopes), expires_at=expires_at)
    )
    return created.key


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _url(path: str) -> str:
    return f"{settings.API_V1_STR}{path}"


class TestIssuing:
    async def test_the_key_is_shown_once_and_only_its_hash_is_stored(
        self, db: AsyncSession
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")

        created = await ApiKeyService(db).create(
            ctx, ApiKeyCreate(name="ci", scopes=[Perm.AGENTS_VIEW])
        )
        listed = await ApiKeyService(db).list_keys(ctx)

        assert created.key.startswith(created.prefix)
        row = (await db.execute(select(ApiKey))).scalar_one()
        assert row.key_hash != created.key
        assert created.key not in row.key_hash
        assert "key" not in listed.items[0].model_dump()
        audit = (await db.execute(select(AppAdminAuditLog))).scalars().all()
        assert all(created.key not in str(entry.details) for entry in audit)

    @pytest.mark.security
    async def test_a_scope_the_issuer_does_not_hold_is_refused(self, db: AsyncSession) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        member = await _join(db, organization, OrgRoleName.MEMBER)
        ctx = AuthContext(user_id=member.id, organization_id=organization.id, role="member")

        with pytest.raises(BadRequestError) as refused:
            await ApiKeyService(db).create(
                ctx, ApiKeyCreate(name="x", scopes=[Perm.MEMBERS_MANAGE])
            )

        assert refused.value.details["fields"][0]["field"] == "scopes"


class TestUsing:
    async def test_a_key_reads_what_it_was_issued_for_and_nothing_else(
        self, db: AsyncSession, client: Client
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        key = await _issue(db, organization, owner, Perm.AGENTS_VIEW)

        async with client() as http:
            listed = await http.get(_url("/agents"), headers=_bearer(key))
            created = await http.post(
                _url("/agents"), headers=_bearer(key), json={"spec": {"name": "Bot"}}
            )
            mine = await http.get(_url("/me/permissions"), headers=_bearer(key))

        assert listed.status_code == 200
        assert created.status_code == 403
        assert [entry["permission"] for entry in mine.json()["permissions"]] == ["agents:view"]

    @pytest.mark.security
    async def test_a_console_route_refuses_a_key_whatever_it_holds(
        self, db: AsyncSession, client: Client
    ) -> None:
        """Keys never manage keys, and the console's own routes are not a contract."""
        owner = await _person(db)
        organization = await _organization(db, owner)
        key = await _issue(db, organization, owner, Perm.AGENTS_VIEW)

        async with client() as http:
            keys = await http.get(_url("/api-keys"), headers=_bearer(key))
            me = await http.get(_url("/users/me"), headers=_bearer(key))

        assert keys.status_code == 403
        assert me.status_code == 403
        assert "not accepted" in keys.json()["error"]["message"]

    @pytest.mark.security
    async def test_revoked_expired_and_wrong_keys_get_the_same_refusal(
        self, db: AsyncSession, client: Client
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        revoked = await _issue(db, organization, owner, Perm.AGENTS_VIEW)
        row = (await db.execute(select(ApiKey))).scalar_one()
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")
        await ApiKeyService(db).revoke(ctx, row.id)
        expired = await _issue(
            db,
            organization,
            owner,
            Perm.AGENTS_VIEW,
            expires_at=datetime.now(UTC) + timedelta(seconds=1),
        )
        await db.execute(
            ApiKey.__table__.update()
            .where(ApiKey.prefix == expired[:12])
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        valid = await _issue(db, organization, owner, Perm.AGENTS_VIEW)
        wrong = valid[:12] + "x" * (len(valid) - 12)

        async with client() as http:
            answers = [
                await http.get(_url("/agents"), headers=_bearer(key))
                for key in (revoked, expired, wrong)
            ]

        assert [answer.status_code for answer in answers] == [401, 401, 401]
        assert len({answer.json()["error"]["message"] for answer in answers}) == 1


class TestNarrowing:
    @pytest.mark.security
    async def test_demoting_the_issuer_narrows_every_key_they_hold(
        self, db: AsyncSession, client: Client
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        builder = await _join(db, organization, OrgRoleName.BUILDER)
        key = await _issue(
            db, organization, builder, Perm.AGENTS_VIEW, Perm.RUNS_VIEW, role="builder"
        )
        membership = (
            await db.execute(
                select(OrganizationMember).where(OrganizationMember.user_id == builder.id)
            )
        ).scalar_one()
        membership.role = OrgRoleName.VIEWER
        await db.flush()

        async with client() as http:
            mine = await http.get(_url("/me/permissions"), headers=_bearer(key))
            runs = await http.get(_url("/runs"), headers=_bearer(key))

        held = {entry["permission"]: entry["scope"] for entry in mine.json()["permissions"]}
        assert held == {"agents:view": "shared"}
        assert runs.status_code == 403

    @pytest.mark.security
    async def test_a_removed_issuer_takes_their_keys_with_them(
        self, db: AsyncSession, client: Client
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        member = await _join(db, organization, OrgRoleName.MEMBER)
        key = await _issue(db, organization, member, Perm.AGENTS_VIEW, role="member")
        membership = (
            await db.execute(
                select(OrganizationMember).where(OrganizationMember.user_id == member.id)
            )
        ).scalar_one()
        await db.delete(membership)
        await db.flush()

        async with client() as http:
            answer = await http.get(_url("/agents"), headers=_bearer(key))

        assert answer.status_code == 401


class TestTenancy:
    @pytest.mark.security
    async def test_a_key_acts_in_its_own_organization_and_says_so_about_another(
        self, db: AsyncSession, client: Client
    ) -> None:
        owner = await _person(db)
        acme = await _organization(db, owner)
        globex = await _organization(db, owner)
        key = await _issue(db, acme, owner, Perm.AGENTS_VIEW)

        async with client() as http:
            mine = await http.get(_url("/me/permissions"), headers=_bearer(key))
            other = await http.get(
                _url("/agents"), headers={**_bearer(key), "X-Organization-Id": str(globex.id)}
            )
            same = await http.get(
                _url("/agents"), headers={**_bearer(key), "X-Organization-Id": str(acme.id)}
            )

        assert mine.json()["organization_id"] == str(acme.id)
        assert other.status_code == 400
        assert other.json()["error"]["details"]["header"] == "X-Organization-Id"
        assert same.status_code == 200


class TestAudit:
    async def test_an_audited_action_names_the_key_without_holding_it(
        self, db: AsyncSession, client: Client
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        key = await _issue(db, organization, owner, Perm.AGENTS_VIEW, Perm.AGENTS_EDIT)

        async with client() as http:
            created = await http.post(
                _url("/agents"), headers=_bearer(key), json={"spec": {"name": "Bot"}}
            )

        assert created.status_code == 201
        entries = (
            (await db.execute(select(AppAdminAuditLog).order_by(AppAdminAuditLog.seq)))
            .scalars()
            .all()
        )
        via = [
            entry.details["via_api_key"]
            for entry in entries
            if "via_api_key" in (entry.details or {})
        ]
        assert via and via[-1]["prefix"] == key[:12]
        assert all(key not in str(entry.details) for entry in entries)


class TestTheServiceDirectly:
    """The same paths without the ASGI hop, which the coverage tracer can lose
    lines across - and the issuer's own listing, which no HTTP test reaches."""

    async def test_a_valid_key_resolves_to_its_issuer_and_records_the_use(
        self, db: AsyncSession
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        key = await _issue(db, organization, owner, Perm.AGENTS_VIEW)

        caller = await ApiKeyService(db).authenticate(key)

        assert caller.user.id == owner.id
        assert caller.organization.id == organization.id
        assert caller.context.key_scopes == frozenset({Perm.AGENTS_VIEW})
        row = (await db.execute(select(ApiKey))).scalar_one()
        await db.refresh(row)
        assert row.last_used_at is not None
        assert repr(row).startswith("<ApiKey(")

    @pytest.mark.security
    async def test_an_expired_key_is_refused(self, db: AsyncSession) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        key = await _issue(
            db,
            organization,
            owner,
            Perm.AGENTS_VIEW,
            expires_at=datetime.now(UTC) + timedelta(seconds=1),
        )
        row = (await db.execute(select(ApiKey))).scalar_one()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.flush()

        with pytest.raises(AuthenticationError):
            await ApiKeyService(db).authenticate(key)

    async def test_a_member_lists_only_their_own_keys(self, db: AsyncSession) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        member = await _join(db, organization, OrgRoleName.MEMBER)
        await _issue(db, organization, owner, Perm.AGENTS_VIEW)
        await _issue(db, organization, member, Perm.AGENTS_VIEW, role="member")
        ctx = AuthContext(user_id=member.id, organization_id=organization.id, role="member")

        listed = await ApiKeyService(db).list_keys(ctx)

        assert [item.user_id for item in listed.items] == [member.id]
        assert listed.items[0].issuer_email == member.email


class TestSockets:
    @pytest.mark.security
    async def test_a_socket_opens_with_a_key_and_closes_with_its_revocation(
        self, db: AsyncSession
    ) -> None:
        """The live-update socket's handshake and its per-event re-check both
        resolve the key; a revoked key is refused the way an ended session is."""
        from app.services.ws_auth import authenticate_socket_key, authenticate_socket_token

        owner = await _person(db)
        organization = await _organization(db, owner)
        key = await _issue(db, organization, owner, Perm.AGENTS_VIEW, Perm.AGENTS_RUN)

        caller = await authenticate_socket_key(db, key)
        user = await authenticate_socket_token(db, key)

        assert caller is not None
        assert caller.context.key_scopes == frozenset({Perm.AGENTS_VIEW, Perm.AGENTS_RUN})
        assert user.id == owner.id
        assert await authenticate_socket_key(db, "eyJhbGciOiJIUzI1NiJ9.e30.x") is None

        row = (await db.execute(select(ApiKey))).scalar_one()
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")
        await ApiKeyService(db).revoke(ctx, row.id)

        with pytest.raises(AuthenticationError):
            await authenticate_socket_key(db, key)


class TestAdministration:
    """Inviting a person and listing members through a key - what the platform's
    own assistant and an MCP client need for "add a user" (#2057)."""

    async def test_a_key_with_members_manage_invites_and_one_without_is_refused(
        self, db: AsyncSession, client: Client
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        manager = await _issue(db, organization, owner, Perm.MEMBERS_MANAGE)
        reader = await _issue(db, organization, owner, Perm.AGENTS_VIEW)
        body = {"email": "new.hire@example.com", "role": "member"}

        async with client() as http:
            invited = await http.post(
                _url(f"/orgs/{organization.id}/invitations"), headers=_bearer(manager), json=body
            )
            refused = await http.post(
                _url(f"/orgs/{organization.id}/invitations"), headers=_bearer(reader), json=body
            )
            members = await http.get(
                _url(f"/orgs/{organization.id}/members"), headers=_bearer(reader)
            )

        assert invited.status_code == 201
        assert invited.json()["email"] == "new.hire@example.com"
        assert refused.status_code == 403
        assert [row["user_id"] for row in members.json()["items"]] == [str(owner.id)]

    @pytest.mark.security
    async def test_a_key_cannot_reach_another_organization_through_the_path(
        self, db: AsyncSession, client: Client
    ) -> None:
        owner = await _person(db)
        acme = await _organization(db, owner)
        globex = await _organization(db, owner)
        key = await _issue(db, acme, owner, Perm.MEMBERS_MANAGE)

        async with client() as http:
            members = await http.get(_url(f"/orgs/{globex.id}/members"), headers=_bearer(key))
            leave = await http.post(_url(f"/orgs/{acme.id}/leave"), headers=_bearer(key))

        assert members.status_code == 404
        assert leave.status_code == 403


class TestTheAssistantsCredential:
    """The key the runner mints for the in-app assistant (#1798)."""

    async def test_it_carries_the_caller_is_never_listed_and_lapsed_ones_are_swept(
        self, db: AsyncSession
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        member = await _join(db, organization, OrgRoleName.MEMBER)
        ctx = AuthContext(user_id=member.id, organization_id=organization.id, role="member")
        service = ApiKeyService(db)
        lapsed = await service.issue_for_run(ctx)
        assert lapsed is not None
        await db.execute(
            ApiKey.__table__.update()
            .where(ApiKey.prefix == lapsed[:12])
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )

        minted = await service.issue_for_run(ctx)

        assert minted is not None
        caller = await service.authenticate(minted)
        # Everything the member holds, except minting keys: no key manages keys.
        assert caller.context.permissions == {
            perm: scope
            for perm, scope in ctx.permissions.items()
            if perm is not Perm.API_KEYS_CREATE
        }
        rows = (await db.execute(select(ApiKey))).scalars().all()
        assert [row.prefix for row in rows] == [minted[:12]]
        assert rows[0].internal
        assert (await service.list_keys(ctx)).items == []

    async def test_nobody_behind_a_run_gets_nothing(self, db: AsyncSession) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)

        assert await ApiKeyService(db).issue_for_run(AuthContext.anonymous(organization.id)) is None

    @pytest.mark.security
    async def test_a_publisher_standing_in_for_a_stranger_lends_nothing(
        self, db: AsyncSession
    ) -> None:
        """A public widget or an unlinked channel member runs as the publisher only
        so the run has a subject; the stranger typing must not get their authority."""
        owner = await _person(db)
        organization = await _organization(db, owner)
        stand_in = AuthContext(
            user_id=owner.id,
            organization_id=organization.id,
            role=OrgRoleName.OWNER,
            subject_is_publisher_fallback=True,
        )

        assert await ApiKeyService(db).issue_for_run(stand_in) is None
        assert (await db.execute(select(ApiKey))).scalars().all() == []

    async def test_a_run_credential_is_usable_from_another_session_at_once(
        self, db: AsyncSession
    ) -> None:
        """A delegate is built mid-run, after the run's opening commit; its
        credential must not wait for the run's transaction to end."""
        from app.db.session import get_db_context
        from app.services.api_key import mint_for_run

        owner = await _person(db)
        organization = await _organization(db, owner)
        await db.commit()
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")

        minted = await mint_for_run(ctx)

        assert minted is not None
        async with get_db_context() as elsewhere:
            caller = await ApiKeyService(elsewhere).authenticate(minted)
        assert caller.user.id == owner.id
