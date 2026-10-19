"""Organization API keys, through the real app against a real database (#1794).

Every refusal a key depends on is asserted here end to end - one-time display,
expiry, revocation, narrowing by the issuer's current role, refusal on the
console's own routes and cross-tenant isolation - because each of them is a join
between a header, a row and a membership that a mocked session would simply agree
with.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

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
from app.services import rate_limit
from app.services.api_key import ApiKeyService
from app.services.platform_mcp import PlatformApi, platform_tools

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


class TestMembershipEnds:
    @pytest.mark.security
    async def test_a_key_stays_revoked_when_its_issuer_is_invited_back(
        self, db: AsyncSession, client: Client
    ) -> None:
        """Removing somebody revokes what they held, so rejoining - the same role or
        another - wakes none of it, nor any copy of it."""
        from app.services.member import MemberService

        owner = await _person(db)
        organization = await _organization(db, owner)
        member = await _join(db, organization, OrgRoleName.MEMBER)
        key = await _issue(db, organization, member, Perm.AGENTS_VIEW, role="member")

        await MemberService(db).remove(organization.id, member.id, owner.id)
        db.add(
            OrganizationMember(
                organization_id=organization.id, user_id=member.id, role=OrgRoleName.ADMIN
            )
        )
        await db.flush()

        async with client() as http:
            answer = await http.get(_url("/agents"), headers=_bearer(key))

        assert answer.status_code == 401
        held = (await db.execute(select(ApiKey).where(ApiKey.user_id == member.id))).scalar_one()
        assert held.revoked_at is not None


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


class _WindowCounter:
    """Stands in for Redis's per-window counter: each call is one more use of the key."""

    def __init__(self) -> None:
        self.uses: Counter[str] = Counter()

    async def count_in_window(self, key: str, *, ttl: int) -> int:
        self.uses[key] += 1
        return self.uses[key]

    async def get(self, key: str) -> str | None:
        return str(self.uses[key]) if key in self.uses else None


class TestLimits:
    @pytest.mark.security
    async def test_a_key_past_its_minute_is_refused_with_retry_after_and_another_key_is_not(
        self, db: AsyncSession, client: Client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each key is limited on its own, so one runaway script cannot starve
        another integration of the same issuer."""
        monkeypatch.setattr(rate_limit, "_redis", _WindowCounter())
        monkeypatch.setattr(settings, "RATE_LIMIT_API_KEY_PER_MINUTE", 2)
        owner = await _person(db)
        organization = await _organization(db, owner)
        busy = await _issue(db, organization, owner, Perm.AGENTS_VIEW)
        quiet = await _issue(db, organization, owner, Perm.AGENTS_VIEW)

        async with client() as http:
            answers = [await http.get(_url("/agents"), headers=_bearer(busy)) for _ in range(3)]
            other = await http.get(_url("/agents"), headers=_bearer(quiet))

        assert [answer.status_code for answer in answers] == [200, 200, 429]
        assert answers[2].headers["Retry-After"] == "60"
        assert answers[2].json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert other.status_code == 200


class TestLimitsBeforeTheLookup:
    @pytest.mark.security
    async def test_made_up_tokens_with_a_real_prefix_do_not_spend_its_allowance(
        self, db: AsyncSession, client: Client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Codex on #2062: the prefix is shown in listings and audit entries, and
        the allowance was keyed on it - anybody could spend a real key's minute."""
        monkeypatch.setattr(rate_limit, "_redis", _WindowCounter())
        monkeypatch.setattr(settings, "RATE_LIMIT_API_KEY_PER_MINUTE", 2)
        owner = await _person(db)
        organization = await _organization(db, owner)
        key = await _issue(db, organization, owner, Perm.AGENTS_VIEW)

        async with client() as http:
            for _ in range(3):
                forged = key[:12] + uuid.uuid4().hex
                await http.get(_url("/agents"), headers=_bearer(forged))
            real = await http.get(_url("/agents"), headers=_bearer(key))

        assert real.status_code == 200

    @pytest.mark.security
    async def test_made_up_keys_are_counted_per_address_and_then_cost_no_query(
        self, db: AsyncSession, client: Client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Codex on #2062: random `aos_` tokens were never counted, and each one
        cost an authentication query."""
        from app.repositories import api_key_repo

        monkeypatch.setattr(rate_limit, "_redis", _WindowCounter())
        monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 2)
        lookups = AsyncMock(return_value=None)
        monkeypatch.setattr(api_key_repo, "get_by_prefix", lookups)

        async with client() as http:
            answers = [
                await http.get(_url("/agents"), headers=_bearer(f"aos_{uuid.uuid4().hex}"))
                for _ in range(4)
            ]

        assert [answer.status_code for answer in answers] == [401, 401, 429, 429]
        assert lookups.await_count == 2

    @pytest.mark.security
    async def test_a_socket_handshake_meets_the_same_limits(
        self, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Codex on #2062: a socket opened with made-up keys was never counted."""
        from fastapi import WebSocket, WebSocketException

        from app.api.deps import get_current_user_ws
        from app.repositories import api_key_repo

        monkeypatch.setattr(rate_limit, "_redis", _WindowCounter())
        monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 2)
        lookups = AsyncMock(return_value=None)
        monkeypatch.setattr(api_key_repo, "get_by_prefix", lookups)

        async def handshake() -> int:
            protocol = f"access_token.aos_{uuid.uuid4().hex}, chat".encode()
            socket = WebSocket(
                {
                    "type": "websocket",
                    "path": "/api/v1/ws/events",
                    "headers": [(b"sec-websocket-protocol", protocol)],
                    "client": ("203.0.113.9", 4000),
                },
                receive=AsyncMock(),
                send=AsyncMock(),
            )
            with pytest.raises(WebSocketException) as refused:
                await get_current_user_ws(socket, access_token=None)
            return refused.value.code

        codes = [await handshake() for _ in range(4)]

        assert codes == [4001, 4001, 4029, 4029]
        assert lookups.await_count == 2


class TestSecrets:
    @pytest.mark.security
    async def test_a_key_is_in_no_log_line_response_or_published_document(
        self, db: AsyncSession, client: Client, caplog: pytest.LogCaptureFixture
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        key = await _issue(db, organization, owner, Perm.AGENTS_VIEW)
        wrong = key[:12] + "x" * (len(key) - 12)

        with caplog.at_level(logging.DEBUG):
            async with client() as http:
                used = await http.get(_url("/agents"), headers=_bearer(key))
                refused = await http.get(_url("/agents"), headers=_bearer(wrong))
                elsewhere = await http.get(_url("/api-keys"), headers=_bearer(key))
                document = await http.get(_url("/public/openapi.json"))

        assert (used.status_code, refused.status_code, elsewhere.status_code) == (200, 401, 403)
        for answer in (used, refused, elsewhere, document):
            assert key not in answer.text and wrong not in answer.text
            assert key not in str(answer.headers)
        logged = "\n".join(record.getMessage() + str(record.__dict__) for record in caplog.records)
        assert key not in logged and wrong not in logged


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
        manager = await _issue(db, organization, owner, Perm.MEMBERS_MANAGE, Perm.ROLES_MANAGE)
        members_only = await _issue(db, organization, owner, Perm.MEMBERS_MANAGE)
        reader = await _issue(db, organization, owner, Perm.AGENTS_VIEW)
        directory = await _issue(db, organization, owner, Perm.MEMBERS_VIEW)
        body = {"email": "new.hire@example.com", "role": "member"}

        async with client() as http:
            invited = await http.post(
                _url(f"/orgs/{organization.id}/invitations"), headers=_bearer(manager), json=body
            )
            refused = await http.post(
                _url(f"/orgs/{organization.id}/invitations"), headers=_bearer(reader), json=body
            )
            # An invitation assigns a role: a key without roles:manage invites nobody,
            # by email or by link (Codex on #2062).
            no_role = await http.post(
                _url(f"/orgs/{organization.id}/invitations"),
                headers=_bearer(members_only),
                json={"email": "admin.hire@example.com", "role": "admin"},
            )
            no_link = await http.post(
                _url(f"/orgs/{organization.id}/invitations/link"),
                headers=_bearer(members_only),
                json={"role": "admin"},
            )
            members = await http.get(
                _url(f"/orgs/{organization.id}/members"), headers=_bearer(directory)
            )
            unlisted = await http.get(
                _url(f"/orgs/{organization.id}/members"), headers=_bearer(reader)
            )

        assert invited.status_code == 201
        assert invited.json()["email"] == "new.hire@example.com"
        assert refused.status_code == 403
        assert (no_role.status_code, no_link.status_code) == (403, 403)
        assert [row["user_id"] for row in members.json()["items"]] == [str(owner.id)]
        # Every member may see who is in the organization; a key only when it was
        # issued for that, not because it holds some other scope.
        assert unlisted.status_code == 403

    async def test_a_key_that_may_run_agents_uploads_a_file_for_a_run(
        self, db: AsyncSession, client: Client
    ) -> None:
        """`file_ids` on the run API need an id, and this is where one comes from."""
        owner = await _person(db)
        organization = await _organization(db, owner)
        runner = await _issue(db, organization, owner, Perm.AGENTS_RUN)
        reader = await _issue(db, organization, owner, Perm.AGENTS_VIEW)
        upload = {"file": ("notes.txt", b"hello", "text/plain")}

        async with client() as http:
            accepted = await http.post(_url("/files/upload"), headers=_bearer(runner), files=upload)
            refused = await http.post(_url("/files/upload"), headers=_bearer(reader), files=upload)

        assert accepted.status_code == 201
        assert accepted.json()["filename"] == "notes.txt"
        assert refused.status_code == 403

    @pytest.mark.security
    async def test_a_key_changes_roles_only_when_issued_for_roles_manage(
        self, db: AsyncSession, client: Client
    ) -> None:
        """Codex on #2062: the service checked the issuer's role, not the key."""
        owner = await _person(db)
        organization = await _organization(db, owner)
        colleague = await _join(db, organization, OrgRoleName.MEMBER)
        members_only = await _issue(db, organization, owner, Perm.MEMBERS_MANAGE)
        roles = await _issue(db, organization, owner, Perm.ROLES_MANAGE)
        path = _url(f"/orgs/{organization.id}/members/{colleague.id}")

        async with client() as http:
            refused = await http.patch(path, headers=_bearer(members_only), json={"role": "admin"})
            changed = await http.patch(path, headers=_bearer(roles), json={"role": "admin"})

        assert refused.status_code == 403
        assert changed.status_code == 200
        assert changed.json()["role"] == "admin"

    @pytest.mark.security
    async def test_retention_is_read_only_by_a_key_issued_org_settings(
        self, db: AsyncSession, client: Client
    ) -> None:
        """Codex on #2062: the read re-checked the issuer's role, not the key."""
        owner = await _person(db)
        organization = await _organization(db, owner)
        narrow = await _issue(db, organization, owner, Perm.AGENTS_VIEW)
        settings_key = await _issue(db, organization, owner, Perm.ORG_SETTINGS)
        path = _url(f"/orgs/{organization.id}/retention")

        async with client() as http:
            refused = await http.get(path, headers=_bearer(narrow))
            read = await http.get(path, headers=_bearer(settings_key))

        assert refused.status_code == 403
        assert read.status_code == 200

    @pytest.mark.security
    async def test_a_settings_key_cannot_reach_the_budget_or_the_waiver(
        self, db: AsyncSession, client: Client
    ) -> None:
        """Each field of the PATCH needs its own permission on the key, as on the person."""
        owner = await _person(db)
        organization = await _organization(db, owner)
        settings_only = await _issue(db, organization, owner, Perm.ORG_SETTINGS)
        path = _url(f"/orgs/{organization.id}")

        async with client() as http:
            renamed = await http.patch(
                path, headers=_bearer(settings_only), json={"name": "Acme 2"}
            )
            budget = await http.patch(
                path, headers=_bearer(settings_only), json={"monthly_budget_usd": None}
            )
            waiver = await http.patch(
                path, headers=_bearer(settings_only), json={"chat_may_waive_approvals": True}
            )

        assert renamed.status_code == 200
        assert budget.status_code == 403
        assert waiver.status_code == 403

    @pytest.mark.security
    async def test_a_membership_key_cannot_set_a_department_cap(
        self, db: AsyncSession, client: Client
    ) -> None:
        """Codex on #2062: the cap is a budget, and the service re-read the issuer's role."""
        owner = await _person(db)
        organization = await _organization(db, owner)
        members_only = await _issue(db, organization, owner, Perm.MEMBERS_MANAGE)
        budgets = await _issue(db, organization, owner, Perm.MEMBERS_MANAGE, Perm.BUDGETS_MANAGE)
        path = _url(f"/orgs/{organization.id}/groups")

        async with client() as http:
            refused = await http.post(
                path,
                headers=_bearer(members_only),
                json={"name": "Finance", "monthly_budget_usd": "10"},
            )
            plain = await http.post(path, headers=_bearer(members_only), json={"name": "Finance"})
            group = plain.json()["id"]
            lifted = await http.patch(
                f"{path}/{group}", headers=_bearer(members_only), json={"monthly_budget_usd": None}
            )
            renamed = await http.patch(
                f"{path}/{group}", headers=_bearer(members_only), json={"name": "Finance EU"}
            )
            capped = await http.patch(
                f"{path}/{group}", headers=_bearer(budgets), json={"monthly_budget_usd": "25"}
            )

        assert refused.status_code == 403
        assert plain.status_code == 201
        assert lifted.status_code == 403
        assert renamed.status_code == 200
        assert capped.status_code == 200

    @pytest.mark.security
    async def test_department_lists_are_the_directory_too(
        self, db: AsyncSession, client: Client
    ) -> None:
        """`/groups` and a group's members name people as `/members` does, so a key
        reads them only with `members:view`."""
        owner = await _person(db)
        organization = await _organization(db, owner)
        reader = await _issue(db, organization, owner, Perm.AGENTS_VIEW)
        directory = await _issue(db, organization, owner, Perm.MEMBERS_VIEW)

        async with client() as http:
            refused = await http.get(
                _url(f"/orgs/{organization.id}/groups"), headers=_bearer(reader)
            )
            listed = await http.get(
                _url(f"/orgs/{organization.id}/groups"), headers=_bearer(directory)
            )

        assert refused.status_code == 403
        assert listed.status_code == 200

    @pytest.mark.security
    async def test_a_key_cannot_reach_another_organization_through_the_path(
        self, db: AsyncSession, client: Client
    ) -> None:
        owner = await _person(db)
        acme = await _organization(db, owner)
        globex = await _organization(db, owner)
        key = await _issue(db, acme, owner, Perm.MEMBERS_MANAGE, Perm.MEMBERS_VIEW)

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


class TestThePlatformServerAsAnAgentsBinding:
    """An agent binding AgenticOS's own MCP server acts as whoever it runs for (#2190).

    Through the very tools a run is handed, called in-process against the real
    API: what a Viewer could not do in the console, their agent cannot do through
    the platform's tools either, and what they could, it can.
    """

    async def test_a_viewer_s_agent_reads_but_cannot_create_an_agent(
        self, db: AsyncSession, client: Client
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        viewer = await _join(db, organization, OrgRoleName.VIEWER)
        credential = await ApiKeyService(db).issue_for_run(
            AuthContext(user_id=viewer.id, organization_id=organization.id, role="viewer")
        )
        refusals: list[str] = []

        def refuse(message: str) -> dict[str, str]:
            refusals.append(message)
            return {"refused": message}

        tools = {
            tool.name: tool.function
            for tool in platform_tools(
                PlatformApi(app, token=lambda: credential, on_refusal=refuse)
            )
        }

        async with client():
            listed = await tools["list_agents"]()
            created = await tools["create_agent_draft"](name="Sneaky", instructions="Do it.")

        assert "items" in listed
        assert "refused" in created
        assert refusals and refusals[0].startswith("403")
