"""Routes only the platform's tools may call, through the real app against a real database.

An `ASSISTANT` route admits the Architect's run key and refuses an organization key
the way a console route does; what the Architect does there is the wizard's own
service, so its checks hold and its audit names the Architect acting for a person.
"""

import json
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, Perm
from app.db.models.api_key import ApiKey
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.oauth import OAuthClient, OAuthGrant
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.main import app
from app.schemas.api_key import ApiKeyCreate
from app.services.api_key import ApiKeyService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_improvement_pipeline import _ready_proposal
from tests.integration.test_platform_mcp import _owner_key, _run_context
from tests.integration.test_platform_mcp import served as served

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


async def _owner(db: AsyncSession) -> AuthContext:
    owner = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(owner)
    await db.flush()
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"))
    await db.flush()
    return AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")


async def _run_key(db: AsyncSession, ctx: AuthContext) -> str:
    key = await ApiKeyService(db).issue_for_run(ctx)
    assert key is not None
    return key


async def _organization_key(db: AsyncSession, ctx: AuthContext) -> str:
    created = await ApiKeyService(db).create(
        ctx,
        ApiKeyCreate(
            name="script", scopes=[Perm.AGENTS_VIEW, Perm.AGENTS_EDIT, Perm.DATASETS_VIEW]
        ),
    )
    return created.key


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _url(path: str) -> str:
    return f"{settings.API_V1_STR}{path}"


async def _agent(http: AsyncClient, key: str) -> str:
    created = await http.post(_url("/agents"), headers=_bearer(key), json={"spec": {"name": "Bot"}})
    assert created.status_code == 201, created.text
    return created.json()["id"]


class TestWhoMayCall:
    @pytest.mark.security
    async def test_an_organization_key_is_refused_as_on_a_console_route(
        self, db: AsyncSession, client: Client
    ) -> None:
        """Not yet a contract: an integration's key is told what a console route tells it."""
        ctx = await _owner(db)
        key = await _organization_key(db, ctx)

        async with client() as http:
            agent = await _agent(http, key)
            refused = [
                await http.get(_url(path), headers=_bearer(key))
                for path in (
                    f"/agents/{agent}/improvements",
                    "/datasets",
                    f"/eval-runs/{uuid.uuid4()}",
                )
            ]
            console = await http.get(_url("/api-keys"), headers=_bearer(key))

        assert [answer.status_code for answer in refused] == [403, 403, 403]
        assert {answer.json()["error"]["message"] for answer in refused} == {
            console.json()["error"]["message"]
        }

    async def test_the_architect_s_run_key_reaches_them(
        self, db: AsyncSession, client: Client
    ) -> None:
        ctx = await _owner(db)
        key = await _run_key(db, ctx)

        async with client() as http:
            agent = await _agent(http, key)
            sessions = await http.get(_url(f"/agents/{agent}/improvements"), headers=_bearer(key))
            datasets = await http.get(_url("/datasets"), headers=_bearer(key))

        assert sessions.status_code == 200
        assert sessions.json() == []
        assert datasets.status_code == 200

    async def test_an_mcp_client_s_oauth_key_reaches_them(
        self, db: AsyncSession, client: Client
    ) -> None:
        """A person's own grant to Claude Code calls the same tools, so the same routes."""
        ctx = await _owner(db)
        db.add(OAuthClient(client_id="claude-code", info={"client_name": "Claude Code"}))
        await db.flush()
        grant = OAuthGrant(
            client_id="claude-code",
            user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            scopes=[Perm.DATASETS_VIEW.value],
        )
        db.add(grant)
        await db.flush()
        key = await ApiKeyService(db).issue_for_grant(
            grant_id=grant.id,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            client_name="Claude Code",
            scopes=[Perm.DATASETS_VIEW.value],
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

        async with client() as http:
            datasets = await http.get(_url("/datasets"), headers=_bearer(key))

        assert datasets.status_code == 200

    @pytest.mark.security
    async def test_a_run_key_from_another_organization_finds_nothing(
        self, db: AsyncSession, client: Client
    ) -> None:
        mine = await _run_key(db, await _owner(db))
        theirs = await _run_key(db, await _owner(db))

        async with client() as http:
            agent = await _agent(http, theirs)
            answer = await http.get(_url(f"/agents/{agent}/improvements"), headers=_bearer(mine))

        assert answer.status_code == 404

    @pytest.mark.security
    async def test_an_expired_run_key_is_refused(self, db: AsyncSession, client: Client) -> None:
        key = await _run_key(db, await _owner(db))
        await db.execute(
            ApiKey.__table__.update()
            .where(ApiKey.prefix == key[:12])
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )

        async with client() as http:
            answer = await http.get(_url("/datasets"), headers=_bearer(key))

        assert answer.status_code == 401


class TestTheAuditTrail:
    async def _via(self, db: AsyncSession) -> dict[str, Any]:
        entries = (
            (await db.execute(select(AppAdminAuditLog).order_by(AppAdminAuditLog.seq)))
            .scalars()
            .all()
        )
        return [
            entry.details["via_api_key"]
            for entry in entries
            if "via_api_key" in (entry.details or {})
        ][-1]

    @pytest.mark.security
    async def test_the_architect_s_write_names_it_beside_the_person(
        self, db: AsyncSession, client: Client
    ) -> None:
        key = await _run_key(db, await _owner(db))

        async with client() as http:
            await _agent(http, key)

        via = await self._via(db)
        assert via == {
            "id": via["id"],
            "prefix": key[:12],
            "name": "Platform assistant",
            "internal": True,
        }
        assert key not in json.dumps(via)

    @pytest.mark.security
    async def test_an_organization_key_s_entry_is_unchanged(
        self, db: AsyncSession, client: Client
    ) -> None:
        key = await _organization_key(db, await _owner(db))

        async with client() as http:
            await _agent(http, key)

        assert set(await self._via(db)) == {"id", "prefix"}


@pytest.mark.usefixtures("_environment")
class TestAcceptingThroughTheTools:
    @pytest.mark.security
    async def test_accepting_a_session_whose_agent_changed_is_refused(
        self, db: AsyncSession, client: Client
    ) -> None:
        """The wizard's compare-and-set holds for the Architect: a draft edited since the
        session started is not overwritten by its candidate."""
        ctx, agent, ready = await _ready_proposal(db)
        key = await _run_key(db, ctx)
        agent.draft_spec = {**agent.draft_spec, "instructions": "Edited by a person meanwhile."}
        await db.flush()

        async with client() as http:
            refused = await http.post(
                _url(f"/agents/{agent.id}/improvements/{ready.id}/finish"),
                headers=_bearer(key),
                json={"confirmed": True, "publish": True},
            )

        assert refused.status_code == 409
        assert agent.draft_spec["instructions"] == "Edited by a person meanwhile."

    async def test_a_session_is_read_by_its_id_alone(
        self, db: AsyncSession, client: Client
    ) -> None:
        """The Architect keeps a session id across turns; it needs nothing else to read it."""
        ctx, agent, ready = await _ready_proposal(db)
        key = await _run_key(db, ctx)

        async with client() as http:
            read = await http.get(_url(f"/improvements/{ready.id}"), headers=_bearer(key))
            unknown = await http.get(_url(f"/improvements/{uuid.uuid4()}"), headers=_bearer(key))

        assert read.status_code == 200
        assert read.json()["agent_id"] == str(agent.id)
        assert read.json()["status"] == "ready"
        assert unknown.status_code == 404

    @pytest.mark.security
    async def test_another_organization_s_session_is_not_found_by_its_id(
        self, db: AsyncSession, client: Client
    ) -> None:
        _ctx, _agent, ready = await _ready_proposal(db)
        stranger = await _run_key(db, await _owner(db))

        async with client() as http:
            answer = await http.get(_url(f"/improvements/{ready.id}"), headers=_bearer(stranger))

        assert answer.status_code == 404

    async def test_accepting_as_a_draft_is_audited_as_the_architect_for_the_person(
        self, db: AsyncSession, client: Client
    ) -> None:
        ctx, agent, ready = await _ready_proposal(db)
        key = await _run_key(db, ctx)

        async with client() as http:
            accepted = await http.post(
                _url(f"/agents/{agent.id}/improvements/{ready.id}/finish"),
                headers=_bearer(key),
                json={"confirmed": True, "publish": False},
            )

        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["session"]["status"] == "accepted"
        entry = await db.scalar(
            select(AppAdminAuditLog)
            .where(AppAdminAuditLog.action == "improvement.accepted")
            .order_by(AppAdminAuditLog.seq.desc())
        )
        assert entry is not None
        assert entry.actor_user_id == ctx.user_id
        assert entry.details["via_api_key"]["name"] == "Platform assistant"
        assert entry.details["via_api_key"]["internal"] is True


@pytest.mark.security
async def test_the_architect_s_improve_writes_wait_for_a_card_and_its_reads_do_not(
    db: AsyncSession, served: None
) -> None:
    from app.agents.mcp import NEEDS_APPROVAL
    from app.agents.spec import PlatformMcpServerRef
    from app.services.mcp_connection import build_toolsets_for_agent

    key, organization = await _owner_key(db, Perm.AGENTS_VIEW, Perm.AGENTS_EDIT)
    resolved = await build_toolsets_for_agent(
        db,
        organization_id=organization.id,
        refs=[PlatformMcpServerRef(account="platform", approval="writes")],
        platform_credential=key,
    )
    [toolset] = resolved.toolsets
    tools = await toolset.get_tools(_run_context())

    def held(name: str) -> bool:
        return tools[f"agenticos_{name}"].tool_def.metadata[NEEDS_APPROVAL]

    assert all(
        held(name)
        for name in (
            "start_improvement",
            "use_attempt",
            "accept_improvement",
            "end_improvement",
            "improve_again",
            "draft_knowledge_topic",
        )
    )
    assert not any(
        held(name)
        for name in (
            "list_improvements",
            "get_improvement",
            "estimate_improvement",
            "estimate_improve_again",
            "list_datasets",
            "get_eval_run",
            "estimate_knowledge_draft",
        )
    )
