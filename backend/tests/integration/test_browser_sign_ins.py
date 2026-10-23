"""Saved browser sign-ins against a real database and the real vault (#2129).

A sign-in is a person's session on somebody else's site, so what matters is who
it reaches: the person it was kept for, in the organization it was kept in, and
nobody else - not another member, not the same person in another organization,
and never anybody through the API, which names sites and nothing more.
"""

import uuid
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.browser_sign_ins import SignIn
from app.api import deps
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.security import create_access_token
from app.core.vault import VaultScope, seal, unseal
from app.db.models.browser_sign_in import BrowserSignIn
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.main import app
from app.services import browser_sign_in

pytestmark = pytest.mark.anyio

LINKEDIN = SignIn(
    site="linkedin.com",
    origin="https://www.linkedin.com",
    cookies=[{"name": "li_at", "value": "AQEDAR-secret-session", "domain": ".linkedin.com"}],
    local_storage={"voyager": "token-in-storage"},
)


@pytest.fixture
async def http(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_redis] = lambda: MagicMock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def _person(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _organization(db: AsyncSession, *members: User) -> Organization:
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=members[0].id
    )
    db.add(organization)
    await db.flush()
    for member in members:
        db.add(
            OrganizationMember(
                organization_id=organization.id, user_id=member.id, role=OrgRoleName.MEMBER
            )
        )
    await db.flush()
    return organization


def _as(user: User, organization: Organization) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(str(user.id))}",
        "X-Organization-Id": str(organization.id),
    }


class TestKeepingAndUsing:
    async def test_a_kept_sign_in_comes_back_for_the_same_person_and_is_marked_used(
        self, db: AsyncSession
    ) -> None:
        ada = await _person(db)
        acme = await _organization(db, ada)
        await db.commit()

        await browser_sign_in.remember(acme.id, ada.id, LINKEDIN)
        loaded = await browser_sign_in.load_for(acme.id, ada.id)

        assert loaded == [LINKEDIN]
        row = (await db.execute(select(BrowserSignIn))).scalar_one()
        assert row.last_used_at is not None

    @pytest.mark.security
    async def test_it_is_sealed_under_the_person_and_nothing_readable_is_stored(
        self, db: AsyncSession
    ) -> None:
        ada = await _person(db)
        acme = await _organization(db, ada)
        await db.commit()

        await browser_sign_in.remember(acme.id, ada.id, LINKEDIN)

        row = (await db.execute(select(BrowserSignIn))).scalar_one()
        assert "AQEDAR-secret-session" not in row.sealed_state
        with pytest.raises(BadRequestError):
            unseal(
                row.sealed_state,
                scope=VaultScope.organization(acme.id),
                key_version=row.secret_key_version,
            )

    async def test_signing_in_again_replaces_the_earlier_sign_in(self, db: AsyncSession) -> None:
        ada = await _person(db)
        acme = await _organization(db, ada)
        await db.commit()

        await browser_sign_in.remember(acme.id, ada.id, LINKEDIN)
        renewed = LINKEDIN.model_copy(update={"local_storage": {"voyager": "renewed"}})
        await browser_sign_in.remember(acme.id, ada.id, renewed)

        assert await browser_sign_in.load_for(acme.id, ada.id) == [renewed]

    @pytest.mark.security
    async def test_another_member_and_another_organization_get_nothing(
        self, db: AsyncSession
    ) -> None:
        ada, grace = await _person(db), await _person(db)
        acme = await _organization(db, ada, grace)
        globex = await _organization(db, ada)
        await db.commit()

        await browser_sign_in.remember(acme.id, ada.id, LINKEDIN)

        assert await browser_sign_in.load_for(acme.id, grace.id) == []
        assert await browser_sign_in.load_for(globex.id, ada.id) == []

    async def test_a_row_this_deployment_cannot_open_or_read_is_skipped(
        self, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The browse still runs - signed out on that site - rather than failing."""
        ada = await _person(db)
        acme = await _organization(db, ada)
        await db.commit()
        await browser_sign_in.remember(acme.id, ada.id, LINKEDIN)
        await browser_sign_in.remember(
            acme.id, ada.id, LINKEDIN.model_copy(update={"site": "github.com"})
        )
        rows = (await db.execute(select(BrowserSignIn).order_by(BrowserSignIn.site))).scalars()
        github, linkedin = list(rows)
        github.secret_key_version = 99
        linkedin.sealed_state = seal("not a sign-in", scope=VaultScope.user(ada.id)).ciphertext
        await db.commit()

        assert await browser_sign_in.load_for(acme.id, ada.id) == []


class TestTheApi:
    @pytest.mark.security
    async def test_the_list_names_sites_and_never_what_a_sign_in_holds(
        self, db: AsyncSession, http: AsyncClient
    ) -> None:
        ada = await _person(db)
        acme = await _organization(db, ada)
        await db.commit()
        await browser_sign_in.remember(acme.id, ada.id, LINKEDIN)

        answer = await http.get(f"{settings.API_V1_STR}/browser-sign-ins", headers=_as(ada, acme))

        assert answer.status_code == 200
        body = answer.json()
        assert body["total"] == 1
        assert body["items"][0]["site"] == "linkedin.com"
        assert set(body["items"][0]) == {"id", "site", "created_at", "updated_at", "last_used_at"}
        assert "secret-session" not in answer.text and "token-in-storage" not in answer.text

    async def test_forgetting_one_removes_it(self, db: AsyncSession, http: AsyncClient) -> None:
        ada = await _person(db)
        acme = await _organization(db, ada)
        await db.commit()
        await browser_sign_in.remember(acme.id, ada.id, LINKEDIN)
        [row] = (await db.execute(select(BrowserSignIn))).scalars()

        gone = await http.delete(
            f"{settings.API_V1_STR}/browser-sign-ins/{row.id}", headers=_as(ada, acme)
        )

        assert gone.status_code == 204
        # What `DBSession` does after the route; the override hands the test's own.
        await db.commit()
        assert await browser_sign_in.load_for(acme.id, ada.id) == []

    @pytest.mark.security
    async def test_nobody_can_forget_or_list_another_person_s(
        self, db: AsyncSession, http: AsyncClient
    ) -> None:
        ada, grace = await _person(db), await _person(db)
        acme = await _organization(db, ada, grace)
        await db.commit()
        await browser_sign_in.remember(acme.id, ada.id, LINKEDIN)
        [row] = (await db.execute(select(BrowserSignIn))).scalars()

        listed = await http.get(f"{settings.API_V1_STR}/browser-sign-ins", headers=_as(grace, acme))
        refused = await http.delete(
            f"{settings.API_V1_STR}/browser-sign-ins/{row.id}", headers=_as(grace, acme)
        )

        assert listed.json() == {"items": [], "total": 0}
        assert refused.status_code == 404
        await db.commit()
        assert len(await browser_sign_in.load_for(acme.id, ada.id)) == 1


class TestTheServiceDirectly:
    async def test_forgetting_reads_the_row_through_the_owner_s_keys(
        self, db: AsyncSession
    ) -> None:
        """Outside the app, so the coverage tracer sees the repository's read."""
        ada = await _person(db)
        acme = await _organization(db, ada)
        await db.commit()
        await browser_sign_in.remember(acme.id, ada.id, LINKEDIN)
        [row] = (await db.execute(select(BrowserSignIn))).scalars()
        ctx = AuthContext(user_id=ada.id, organization_id=acme.id, role=OrgRoleName.MEMBER)

        await browser_sign_in.BrowserSignInService(db).forget(ctx, row.id)
        await db.commit()

        assert await browser_sign_in.load_for(acme.id, ada.id) == []
