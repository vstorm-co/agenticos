"""Flows across services, against a real database.

The unit suite proves each service in isolation, with the database replaced by
something that agrees with it. That is exactly why it cannot answer the
questions here: whether a listing query really stops at the tenant boundary,
whether publishing twice leaves two rows or one, whether a month of costs adds
up without drifting, and whether a grant written by one service is seen by
another.

Every test drives the real services, so what it asserts is what the platform
does - not what a stub was told to return.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from app.agents.capabilities.approval import approval_required_tools
from app.agents.capabilities.budget import BudgetExceeded, BudgetScope
from app.agents.spec import AgentSpec, CapabilityBindingSpec, SpecialistSpec
from app.api import deps
from app.core.config import settings
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope, unseal
from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.db.models.agent_exposure import AgentExposure
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, RunSurface, ToolApproval
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.channel_session import ChannelSession
from app.db.models.conversation import Conversation, Message
from app.db.models.credential import ModelProfile
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.models.resource_grant import GrantLevel, Visibility
from app.db.models.skill import Skill
from app.db.models.sync_log import SyncLog
from app.db.models.sync_source import SyncSource
from app.db.models.user import User
from app.main import app
from app.repositories import (
    agent_exposure_repo,
    agent_run_repo,
    channel_session_repo,
    conversation_repo,
    credential_repo,
    ingestion_spend_repo,
    mcp_connection_repo,
    member_repo,
    organization_secret_repo,
    rag_document_repo,
)
from app.repositories.agent_run import RunFilters
from app.schemas.agent_environment import EnvironmentCreate, EnvironmentUpdate
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.schemas.mcp_connection import OrgMcpConnectionCreate, OrgMcpConnectionUpdate
from app.services.access import AGENT, COLLECTION, SKILL, resolve_access
from app.services.agent_chat import ChatAgentRunner
from app.services.agent_environment import AgentEnvironmentService
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService, month_start
from app.services.approvals import ApprovalService
from app.services.channel_link import ChannelLinkService
from app.services.channels.mentions import ChannelAgentRouter, UnaddressedMessage
from app.services.ingestion_config import (
    ImageDescription,
    ImageDescriptionOverride,
    IngestionConfig,
    IngestionConfigService,
    IngestionOverride,
    PdfParserName,
    deployment_defaults,
)
from app.services.knowledge_base import KnowledgeBaseService
from app.services.mcp_connection import McpConnectionService, build_toolsets_for_agent
from app.services.model_profile import ModelProfileService
from app.services.organization_secret import OrganizationSecretService
from app.services.rag.documents import LiteParseParser
from app.services.rag_document import RAGDocumentService
from app.services.sharing import SharingService
from app.services.skills import SkillService

pytestmark = pytest.mark.anyio


@dataclass
class Tenant:
    """One organization, its owner, and the context that owner calls with."""

    organization: Organization
    user: User
    ctx: AuthContext


async def _new_user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _tenant(db, *, name: str, monthly_budget_usd: Decimal | None = None) -> Tenant:
    user = await _new_user(db)
    organization = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
        monthly_budget_usd=monthly_budget_usd,
    )
    db.add(organization)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid.uuid4(),
            organization_id=organization.id,
            user_id=user.id,
            role=OrgRoleName.OWNER.value,
        )
    )
    await db.flush()
    return Tenant(
        organization=organization,
        user=user,
        ctx=AuthContext(
            user_id=user.id, organization_id=organization.id, role=OrgRoleName.OWNER.value
        ),
    )


async def _join(db, tenant: Tenant, role: OrgRoleName) -> AuthContext:
    """Add a second member to an organization and return their context."""
    user = await _new_user(db)
    db.add(
        OrganizationMember(
            id=uuid.uuid4(),
            organization_id=tenant.organization.id,
            user_id=user.id,
            role=role.value,
        )
    )
    await db.flush()
    return AuthContext(user_id=user.id, organization_id=tenant.organization.id, role=role.value)


async def _default_model(db, tenant: Tenant) -> ModelProfile:
    """A default model profile, without which no spec can be published."""
    profile = ModelProfile(
        id=uuid.uuid4(),
        organization_id=tenant.organization.id,
        label="Default",
        provider="openai",
        model="gpt-4.1",
    )
    db.add(profile)
    await db.flush()
    return profile


async def _keyed_model_profile(db, tenant: Tenant) -> ModelProfile:
    """A default profile with credentials behind it, so a run can be *built*.

    `_default_model` above is enough to publish a spec - publishing only
    checks that a profile exists. Assembling a run resolves the profile and
    unseals its key, so anything that actually executes needs this one.
    """
    sealed = seal_secret(
        ApiKeySecret(api_key="sk-test-key"),
        scope=VaultScope.organization(tenant.organization.id),
    )
    secret = OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=tenant.organization.id,
        name="Key",
        purpose="openai",
        visibility="org",
        kind=SecretKind.API_KEY.value,
        sealed_secret=sealed.ciphertext,
        hint=sealed.hint,
    )
    db.add(secret)
    await db.flush()
    profile = ModelProfile(
        id=uuid.uuid4(),
        organization_id=tenant.organization.id,
        label="Default",
        provider="openai",
        model="gpt-4.1",
        secret_id=secret.id,
    )
    db.add(profile)
    await db.flush()
    return profile


async def _published_agent(db, tenant: Tenant, *, spec: AgentSpec) -> Agent:
    """An agent with a live version, created through the registry that guards it.

    A spec that names no model is given whichever one the test already created.
    Publishing refuses a spec without one - there is no organization-wide
    default to fall back on - and every test here that does not care which model
    an agent runs on would otherwise have to say so anyway.
    """
    if spec.model_profile_id is None:
        profiles = await credential_repo.list_profiles(db, organization_id=tenant.organization.id)
        if profiles:
            spec = spec.model_copy(update={"model_profile_id": profiles[0].id})
    registry = AgentRegistryService(db)
    agent = await registry.create(tenant.ctx, spec)
    await registry.publish(tenant.ctx, agent.id)
    return agent


def _answering_model() -> FunctionModel:
    """A model that answers in one turn without leaving the process.

    Enough to prove a budget: the guard runs *before* the request, so a run
    already over its cap never reaches this, and one under it comes back with
    the answer below.
    """

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("thirty days")])

    return FunctionModel(respond)


async def _answer(prepared) -> str:
    """Execute a prepared run against that model and return what it said."""
    with prepared.built.agent.override(model=_answering_model()):
        result = await prepared.built.agent.run("what is the refund window", deps=prepared.deps)
    return str(result.output)


async def _mcp_connection(
    db, tenant: Tenant, *, name: str, scope: str, **overrides
) -> McpConnection:
    """One MCP connection row, always carrying its organization.

    A personal connection keeps `organization_id` too - that is the case worth
    having rows for, because filtering on the organization alone would let a
    member's own token into a shared agent.

    Ownership follows the scope, because the table's check constraints require
    it: a personal row has an owner, an organization row has none and records
    its author instead, so that closing that account cannot take the
    organization's server down with it.
    """
    owned_by_a_member = scope == "user"
    connection = McpConnection(
        id=uuid.uuid4(),
        user_id=tenant.user.id if owned_by_a_member else None,
        created_by_user_id=None if owned_by_a_member else tenant.user.id,
        organization_id=tenant.organization.id,
        scope=scope,
        name=name,
        url="https://mcp.example.com/mcp",
        auth_token=None,
        allowed_tools=None,
        is_enabled=True,
        auth_type="bearer",
        **overrides,
    )
    db.add(connection)
    await db.flush()
    return connection


async def _agent_row(db, *, organization_id: uuid.UUID, owner_user_id: uuid.UUID, slug: str):
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        slug=slug,
        name=slug.title(),
        draft_spec=AgentSpec(name=slug.title()).model_dump(mode="json"),
        visibility=Visibility.PRIVATE.value,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _bot_row(db, *, organization_id: uuid.UUID, platform: str = "slack") -> ChannelBot:
    bot = ChannelBot(
        id=uuid.uuid4(),
        organization_id=organization_id,
        platform=platform,
        name=f"{platform.title()} bot",
        token_encrypted="sealed",
    )
    db.add(bot)
    await db.flush()
    return bot


async def _exposure_row(
    db, *, agent: Agent, bot: ChannelBot, is_active: bool = True
) -> AgentExposure:
    exposure = AgentExposure(
        id=uuid.uuid4(),
        organization_id=agent.organization_id,
        agent_id=agent.id,
        surface=bot.platform,
        channel_bot_id=bot.id,
        is_active=is_active,
    )
    db.add(exposure)
    await db.flush()
    return exposure


async def _run_row(
    db,
    *,
    organization_id,
    agent_id,
    cost: Decimal,
    started_at: datetime,
    status: str = RunStatus.COMPLETED.value,
):
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=organization_id,
        agent_id=agent_id,
        status=status,
        cost_usd=cost,
        started_at=started_at,
    )
    db.add(run)
    await db.flush()
    return run


# -- tenant isolation ---------------------------------------------------------


@dataclass
class TwoTenants:
    """Two organizations with the same shape of data, and one user in both sets.

    The second tenant's rows are *owned* by the first tenant's user. That is the
    case a scope check alone gets wrong: ownership is the usual reason a row is
    visible, so a query that filters on the owner and forgets the organization
    passes every single-tenant test and leaks here.
    """

    home: Tenant
    other: Tenant
    home_agent: Agent
    other_agent: Agent
    home_skill: Skill
    other_skill: Skill
    home_collection: KnowledgeBase
    other_collection: KnowledgeBase
    home_run: AgentRun
    other_run: AgentRun


@pytest.fixture
async def estate(db) -> TwoTenants:
    home = await _tenant(db, name="Home")
    other = await _tenant(db, name="Other")

    home_agent = await _agent_row(
        db, organization_id=home.organization.id, owner_user_id=home.user.id, slug="support"
    )
    other_agent = await _agent_row(
        db, organization_id=other.organization.id, owner_user_id=home.user.id, slug="support"
    )

    skills = []
    for tenant in (home, other):
        skill = Skill(
            id=uuid.uuid4(),
            organization_id=tenant.organization.id,
            owner_user_id=home.user.id,
            name="refunds",
            description="How refunds work",
        )
        db.add(skill)
        skills.append(skill)

    collections = []
    for tenant in (home, other):
        collection = KnowledgeBase(
            id=uuid.uuid4(),
            organization_id=tenant.organization.id,
            owner_user_id=home.user.id,
            name="Handbook",
            collection_name=f"kb_{uuid.uuid4().hex[:8]}",
            ingestion_config=deployment_defaults().model_dump(mode="json"),
            embedding_model=settings.EMBEDDING_MODEL,
            embedding_dim=settings.rag.embeddings_config.dim,
        )
        db.add(collection)
        collections.append(collection)
    await db.flush()

    now = datetime.now(UTC)
    home_run = await _run_row(
        db,
        organization_id=home.organization.id,
        agent_id=home_agent.id,
        cost=Decimal("1.000000"),
        started_at=now,
    )
    other_run = await _run_row(
        db,
        organization_id=other.organization.id,
        agent_id=other_agent.id,
        cost=Decimal("9.000000"),
        started_at=now,
    )

    return TwoTenants(
        home=home,
        other=other,
        home_agent=home_agent,
        other_agent=other_agent,
        home_skill=skills[0],
        other_skill=skills[1],
        home_collection=collections[0],
        other_collection=collections[1],
        home_run=home_run,
        other_run=other_run,
    )


@dataclass
class RagEstate:
    """Two organizations, each with a full set of RAG rows, plus one shared name.

    The collections are `org`-scoped, which is what both `POST /kb` and
    `POST /rag/collections/{name}` actually create - and the other tenant's
    carries the *home* user as its owner, for the same reason `TwoTenants`
    does: ownership must not be a way in.

    `home_private` is the second boundary in this system and is easy to miss
    while looking at the first: a personal collection belonging to another
    member of your *own* organization.
    """

    home: Tenant
    other: Tenant
    home_member: AuthContext
    home_collection: KnowledgeBase
    other_collection: KnowledgeBase
    home_private: KnowledgeBase
    home_document: RAGDocument
    other_document: RAGDocument
    home_source: SyncSource
    other_source: SyncSource
    home_sync: SyncLog
    other_sync: SyncLog


async def _kb_row(
    db,
    *,
    tenant: Tenant,
    collection_name: str,
    scope: KBScope = KBScope.ORG,
    owner_user_id: uuid.UUID | None = None,
    is_default: bool = False,
    ingestion_config: IngestionConfig | None = None,
    embedding_model: str | None = None,
    visibility: str | None = None,
) -> KnowledgeBase:
    """One knowledge base row, always saying what its vectors were built with.

    `embedding_model` has no database default on purpose - see
    `app.repositories.knowledge_base.create` - so every row that exists in a
    test says the same thing a row in production would.

    Org rows default to org-wide visibility, which is what every ownerless org
    row in production carries after `0063_kb_org_visibility` - a private one
    is a deliberate choice a test states explicitly.
    """
    if visibility is None:
        visibility = Visibility.ORG.value if scope is KBScope.ORG else Visibility.PRIVATE.value
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        name=collection_name,
        collection_name=collection_name,
        scope=scope.value,
        organization_id=tenant.organization.id,
        owner_user_id=owner_user_id,
        is_default=is_default,
        visibility=visibility,
        ingestion_config=(ingestion_config or deployment_defaults()).model_dump(mode="json"),
        embedding_model=embedding_model or settings.EMBEDDING_MODEL,
        embedding_dim=settings.rag.embeddings_config.dim,
    )
    db.add(kb)
    await db.flush()
    return kb


async def _rag_document(db, *, collection_name: str, filename: str) -> RAGDocument:
    doc = RAGDocument(
        id=uuid.uuid4(),
        collection_name=collection_name,
        filename=filename,
        filesize=12,
        filetype="txt",
        status=DocumentStatus.DONE,
        vector_document_id=str(uuid.uuid4()),
    )
    db.add(doc)
    await db.flush()
    return doc


async def _sync_source_row(db, *, tenant: Tenant, collection_name: str) -> SyncSource:
    source = SyncSource(
        id=uuid.uuid4(),
        organization_id=tenant.organization.id,
        name="Drive",
        connector_type="gdrive",
        collection_name=collection_name,
        config={"folder_id": "abc"},
    )
    db.add(source)
    await db.flush()
    return source


async def _sync_log_row(
    db, *, collection_name: str, sync_source_id: uuid.UUID | None = None
) -> SyncLog:
    log = SyncLog(
        id=uuid.uuid4(),
        source="gdrive",
        collection_name=collection_name,
        mode="full",
        status="running",
        sync_source_id=sync_source_id,
    )
    db.add(log)
    await db.flush()
    return log


@pytest.fixture
async def rag_estate(db, estate: TwoTenants) -> RagEstate:
    home, other = estate.home, estate.other
    home_collection = await _kb_row(db, tenant=home, collection_name="home_handbook")
    other_collection = await _kb_row(
        db, tenant=other, collection_name="other_handbook", owner_user_id=home.user.id
    )
    home_private = await _kb_row(
        db,
        tenant=home,
        collection_name="home_notes",
        scope=KBScope.PERSONAL,
        owner_user_id=home.user.id,
    )
    return RagEstate(
        home=home,
        other=other,
        home_member=await _join(db, home, OrgRoleName.MEMBER),
        home_collection=home_collection,
        other_collection=other_collection,
        home_private=home_private,
        home_document=await _rag_document(
            db, collection_name=home_collection.collection_name, filename="ours.txt"
        ),
        other_document=await _rag_document(
            db, collection_name=other_collection.collection_name, filename="theirs.txt"
        ),
        home_source=await _sync_source_row(
            db, tenant=home, collection_name=home_collection.collection_name
        ),
        other_source=await _sync_source_row(
            db, tenant=other, collection_name=other_collection.collection_name
        ),
        home_sync=await _sync_log_row(db, collection_name=home_collection.collection_name),
        other_sync=await _sync_log_row(db, collection_name=other_collection.collection_name),
    )


class _NeverAsked:
    """A collaborator that fails the test if a refusal let a request reach it.

    Every refusal below has to happen before the collection is opened. A stub
    that politely returned an empty answer would let a route that checks nothing
    pass a test which only reads the status code - so this one is louder.
    """

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"refused too late: {name}() was reached")


RagClient = Callable[[AuthContext], AsyncClient]


@pytest.fixture
async def rag_api(db, mock_redis: MagicMock) -> AsyncIterator[RagClient]:
    """Real requests to the routes under `/rag`, against the real database.

    Everything else in this file drives services directly, because the service
    is where the decision lives. That was exactly what made this class of bug
    invisible for `/rag`: the services were fine and the routes never asked
    them anything about an organization, so a service-level test would have
    passed while `GET /rag/collections/{someone else's}/info` answered 200.
    Here the request is the unit under test.

    The vector store, retriever and ingester are `_NeverAsked`: these tests
    assert refusals, and a refusal that arrives after the vectors have been read
    is a filter on the way out, not a boundary.
    """
    never = _NeverAsked()
    app.dependency_overrides[deps.get_db_session] = lambda: db
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_vectorstore] = lambda: never
    app.dependency_overrides[deps.get_retrieval_service] = lambda: never
    app.dependency_overrides[deps.get_ingestion_service] = lambda: never

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:

        def as_caller(ctx: AuthContext) -> AsyncClient:
            app.dependency_overrides[deps.get_auth_context] = lambda: ctx
            return client

        yield as_caller

    app.dependency_overrides.clear()


def _rag(path: str) -> str:
    return f"{settings.API_V1_STR}/rag{path}"


KbClient = Callable[[Tenant], AsyncClient]


@pytest.fixture
async def kb_api(db) -> AsyncIterator[KbClient]:
    """Real requests to the routes under `/kb`, as one of the tenants.

    Its own client because `/kb` resolves three things about a caller where
    `/rag` resolves one: the user, the active organization and the auth
    context. A caller is therefore a whole tenant here, not a context - passing
    only the context would leave the other two dependencies real, and the
    request would be refused for having no token rather than for the reason
    under test.
    """
    app.dependency_overrides[deps.get_db_session] = lambda: db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:

        def as_caller(tenant: Tenant) -> AsyncClient:
            app.dependency_overrides[deps.get_current_user] = lambda: tenant.user
            app.dependency_overrides[deps.get_active_organization] = lambda: tenant.organization
            app.dependency_overrides[deps.get_auth_context] = lambda: tenant.ctx
            return client

        yield as_caller

    app.dependency_overrides.clear()


class TestTenantIsolation:
    """An owner of one organization is a stranger to every other one.

    Owner is the strongest role there is - `Scope.ALL` on everything - so if
    the boundary holds for them it holds for everyone.
    """

    async def test_listing_agents_stops_at_the_boundary(self, db, estate: TwoTenants) -> None:
        items, total = await AgentRegistryService(db).list_agents(estate.home.ctx)

        assert [agent.id for agent in items] == [estate.home_agent.id]
        assert total == 1

    async def test_an_agent_in_another_tenant_is_not_found_by_its_own_owner(
        self, db, estate: TwoTenants
    ) -> None:
        """Owning the row is not access - the organization is checked first."""
        with pytest.raises(NotFoundError):
            await AgentRegistryService(db).get(estate.home.ctx, estate.other_agent.id)

    async def test_listing_skills_stops_at_the_boundary(self, db, estate: TwoTenants) -> None:
        items, total = await SkillService(db).list_skills(estate.home.ctx)

        assert [skill.id for skill in items] == [estate.home_skill.id]
        # The count is the tenant's, not the table's - a pager built on a total
        # that counted another organization's rows offers a page that is empty.
        assert total == 1

    async def test_a_skill_in_another_tenant_is_not_found_by_its_own_owner(
        self, db, estate: TwoTenants
    ) -> None:
        with pytest.raises(NotFoundError):
            await SkillService(db).get(estate.home.ctx, estate.other_skill.id)

    async def test_a_collection_in_another_tenant_is_unreachable(
        self, db, estate: TwoTenants
    ) -> None:
        """Checked through `resolve_access`: every collection read goes through it."""
        assert await resolve_access(
            db,
            estate.home.ctx,
            estate.home_collection,
            Perm.COLLECTIONS_VIEW,
            resource_type=COLLECTION,
        )
        assert not await resolve_access(
            db,
            estate.home.ctx,
            estate.other_collection,
            Perm.COLLECTIONS_VIEW,
            resource_type=COLLECTION,
        )

    async def test_run_history_stops_at_the_boundary(self, db, estate: TwoTenants) -> None:
        items, total = await agent_run_repo.list_runs(
            db, organization_id=estate.home.organization.id
        )

        assert [run.id for run in items] == [estate.home_run.id]
        assert total == 1

    async def test_a_status_list_narrows_both_the_page_and_the_total(
        self, db, estate: TwoTenants
    ) -> None:
        """The count must carry the same predicate as the page - a total counted
        without it offers a pager full of rows the filter then removes."""
        now = datetime.now(UTC)
        failed = await _run_row(
            db,
            organization_id=estate.home.organization.id,
            agent_id=estate.home_agent.id,
            cost=Decimal("0.100000"),
            started_at=now,
            status=RunStatus.FAILED.value,
        )
        broke = await _run_row(
            db,
            organization_id=estate.home.organization.id,
            agent_id=estate.home_agent.id,
            cost=Decimal("0.200000"),
            started_at=now,
            status=RunStatus.BUDGET_EXCEEDED.value,
        )

        items, total = await agent_run_repo.list_runs(
            db,
            organization_id=estate.home.organization.id,
            filters=RunFilters(statuses=[RunStatus.FAILED.value, RunStatus.BUDGET_EXCEEDED.value]),
        )

        assert {run.id for run in items} == {failed.id, broke.id}
        assert total == 2

    async def test_spend_counts_only_the_callers_own_runs(self, db, estate: TwoTenants) -> None:
        """The other tenant's run costs nine dollars; it must not appear on this bill."""
        assert await AgentRunnerService(db).monthly_spend(estate.home.ctx) == Decimal("1")

    async def test_an_approval_from_another_tenant_cannot_be_decided(
        self, db, estate: TwoTenants
    ) -> None:
        approval = ToolApproval(
            id=uuid.uuid4(),
            organization_id=estate.other.organization.id,
            run_id=estate.other_run.id,
            agent_id=estate.other_agent.id,
            tool_id="send_email",
        )
        db.add(approval)
        await db.flush()

        with pytest.raises(NotFoundError):
            await ApprovalService(db).decide(estate.home.ctx, approval.id, approved=True)

    # -- the same boundary, through the /rag API ----------------------------
    #
    # These go through the app rather than a service because that is where the
    # hole was: 18 of the 24 routes under /rag took the caller's *platform*
    # role and never mentioned an organization, so `GET /rag/collections`
    # answered `[]` for a stranger while `/rag/collections/{name}/info` on the
    # very next line answered 200 with another tenant's statistics.

    async def test_a_collection_the_listing_omits_is_not_reachable_by_name(
        self, rag_api: RagClient, rag_estate: RagEstate
    ) -> None:
        """The listing and the collection itself must agree, or the listing is decoration.

        Both halves in one test on purpose: they were inconsistent, and it is
        the inconsistency - not either answer alone - that was the bug.

        Containment rather than equality because `estate` contributes two
        *personal* collections that this same user owns, one of them created
        inside the other organization. A personal knowledge base belongs to its
        owner rather than to an organization, so it follows them between org
        contexts - deliberate, and the reason this asserts on the org-scoped
        rows the fixture names.
        """
        client = rag_api(rag_estate.home.ctx)

        listed = await client.get(_rag("/collections"))
        assert listed.status_code == 200
        names = listed.json()["items"]
        assert {"home_handbook", "home_notes"} <= set(names)
        assert "other_handbook" not in names

        refused = await client.get(_rag("/collections/other_handbook/info"))
        assert refused.status_code == 404

    async def test_a_refusal_is_indistinguishable_from_a_collection_that_never_existed(
        self, rag_api: RagClient, rag_estate: RagEstate
    ) -> None:
        """Otherwise the API is an oracle for collection names.

        Names are derived from what people call their knowledge bases, so
        "exists but not yours" is worth guessing for. Same status, same body.
        """
        client = rag_api(rag_estate.home.ctx)

        theirs = await client.get(_rag("/collections/other_handbook/documents"))
        invented = await client.get(_rag("/collections/no_such_collection/documents"))

        assert theirs.status_code == invented.status_code == 404
        assert theirs.json()["error"]["message"] == invented.json()["error"]["message"]
        assert set(theirs.json()["error"]["details"]) == set(invented.json()["error"]["details"])

    async def test_a_personal_collection_is_private_from_the_rest_of_the_organization(
        self, rag_api: RagClient, rag_estate: RagEstate
    ) -> None:
        """The second boundary: same organization, somebody else's own collection."""
        response = await rag_api(rag_estate.home_member).get(_rag("/collections/home_notes/info"))

        assert response.status_code == 404

    async def test_the_document_listing_answers_with_the_callers_collections(
        self, rag_api: RagClient, rag_estate: RagEstate
    ) -> None:
        """Unfiltered used to mean every document in the deployment."""
        response = await rag_api(rag_estate.home.ctx).get(_rag("/documents"))

        assert response.status_code == 200
        assert [item["filename"] for item in response.json()["items"]] == ["ours.txt"]

    async def test_a_tracked_document_in_another_tenant_cannot_be_deleted(
        self, db, rag_api: RagClient, rag_estate: RagEstate
    ) -> None:
        response = await rag_api(rag_estate.home.ctx).delete(
            _rag(f"/documents/{rag_estate.other_document.id}")
        )

        assert response.status_code == 404
        assert await db.get(RAGDocument, rag_estate.other_document.id) is not None

    async def test_dropping_a_collection_that_is_not_there_is_not_reported_as_success(
        self, db, rag_api: RagClient, rag_estate: RagEstate
    ) -> None:
        """204 for any name at all made this route unusable as a confirmation.

        It also made "not yours" and "not there" the same *successful* answer,
        while the drop itself went ahead: the SQL document rows and the KB row
        were deleted by collection name, whoever owned them.
        """
        client = rag_api(rag_estate.home.ctx)

        invented = await client.delete(_rag("/collections/no_such_collection"))
        theirs = await client.delete(_rag("/collections/other_handbook"))

        assert invented.status_code == 404
        assert theirs.status_code == 404
        assert theirs.json()["error"]["message"] == invented.json()["error"]["message"]
        assert await db.get(KnowledgeBase, rag_estate.other_collection.id) is not None
        assert await db.get(RAGDocument, rag_estate.other_document.id) is not None

    async def test_a_search_naming_one_unreachable_collection_is_refused_entirely(
        self, rag_api: RagClient, rag_estate: RagEstate
    ) -> None:
        """A partial answer that looks complete is worse than an error.

        The retriever is `_NeverAsked`, so this also asserts the request is
        refused before the reachable half of it has been searched.
        """
        response = await rag_api(rag_estate.home.ctx).post(
            _rag("/search"),
            json={"query": "salary bands", "collection_names": ["home_handbook", "other_handbook"]},
        )

        assert response.status_code == 404

    async def test_a_file_cannot_be_ingested_into_another_tenants_collection(
        self, rag_api: RagClient, rag_estate: RagEstate
    ) -> None:
        """The write half of the boundary: poisoning an index nobody can audit."""
        response = await rag_api(rag_estate.home.ctx).post(
            _rag("/collections/other_handbook/ingest"),
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

        assert response.status_code == 404

    async def test_claiming_a_collection_name_another_tenant_owns_is_refused(
        self, db, rag_api: RagClient, rag_estate: RagEstate
    ) -> None:
        """Two knowledge bases with one collection name share one vector table.

        Creating over their name used to answer 201 and hand back *their* KB
        row, which is either a hijack or a lie depending on which side you read
        it from.
        """
        response = await rag_api(rag_estate.home.ctx).post(_rag("/collections/other_handbook"))

        assert response.status_code == 409
        rows = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.collection_name == "other_handbook")
        )
        assert [kb.organization_id for kb in rows.scalars()] == [rag_estate.other.organization.id]

    async def test_another_tenants_sync_source_cannot_be_deleted(
        self, db, rag_api: RagClient, rag_estate: RagEstate
    ) -> None:
        """A sync source holds credentials, which is what made this one expensive."""
        response = await rag_api(rag_estate.home.ctx).delete(
            _rag(f"/sync/sources/{rag_estate.other_source.id}")
        )

        assert response.status_code == 404
        assert await db.get(SyncSource, rag_estate.other_source.id) is not None

    async def test_another_tenants_integration_cannot_be_cloned_for_its_credentials(
        self, rag_api: RagClient, rag_estate: RagEstate
    ) -> None:
        """Cloning re-encrypts the credentials it finds, into the caller's org."""
        response = await rag_api(rag_estate.home.ctx).post(
            _rag(f"/sync/sources/{rag_estate.other_source.id}/clone"),
            json={"collection_name": "home_handbook"},
        )

        assert response.status_code == 404

    async def test_another_tenants_sync_run_cannot_be_cancelled(
        self, db, rag_api: RagClient, rag_estate: RagEstate
    ) -> None:
        response = await rag_api(rag_estate.home.ctx).delete(
            _rag(f"/sync/{rag_estate.other_sync.id}")
        )

        assert response.status_code == 404
        await db.refresh(rag_estate.other_sync)
        assert rag_estate.other_sync.status == "running"

    async def test_sync_history_stops_at_the_boundary(
        self, rag_api: RagClient, rag_estate: RagEstate
    ) -> None:
        response = await rag_api(rag_estate.home.ctx).get(_rag("/sync/logs"))

        assert response.status_code == 200
        assert [item["collection_name"] for item in response.json()["items"]] == ["home_handbook"]

    # -- the same boundary, on the /kb write path ----------------------------
    #
    # Through the service rather than the app, unlike the /rag block above: /kb's
    # routes always resolved an organization, so the decision was in the service
    # and so was the bug. Its read path reports an unreachable base as missing;
    # its *write* path answered 403, which is an answer about a row and therefore
    # a way to confirm one exists.
    #
    # The clone below is the exception, and goes through the app: what it checks
    # lives in the route.

    async def test_another_tenants_integration_cannot_be_cloned_into_a_knowledge_base(
        self, db, kb_api: KbClient, rag_estate: RagEstate
    ) -> None:
        """A clone has two ends, and this route used to check only the near one.

        The knowledge base in the path was resolved inside the caller's
        organization; the source id was taken as given, and cloning decrypts
        whatever credentials it finds and re-encrypts them into the
        destination. So owning any collection was enough to pull another
        tenant's Drive into it. It is also the route the reusable-integration
        list on `/kb` posts to, which is why the assertion is on the request
        rather than on the service behind it.
        """
        response = await kb_api(rag_estate.home).post(
            f"{settings.API_V1_STR}/kb/{rag_estate.home_collection.id}"
            f"/sync-sources/{rag_estate.other_source.id}/clone",
            json={"collection_name": rag_estate.home_collection.collection_name},
        )

        assert response.status_code == 404
        landed = await db.execute(
            select(SyncSource).where(
                SyncSource.collection_name == rag_estate.home_collection.collection_name
            )
        )
        assert [source.id for source in landed.scalars()] == [rag_estate.home_source.id]

    async def test_a_write_refusal_is_indistinguishable_from_a_base_that_never_existed(
        self, db, rag_estate: RagEstate
    ) -> None:
        """Otherwise the write path is an oracle for knowledge base ids.

        Everything the client sees has to match, not just the status: the error
        envelope carries a code and a message too, and either of them differing
        answers the question the status was hidden to avoid.
        """
        service = KnowledgeBaseService(db)
        rename = KnowledgeBaseUpdate(name="mine now")
        home = rag_estate.home

        with pytest.raises(NotFoundError) as theirs:
            await service.update(rag_estate.other_collection.id, rename, ctx=home.ctx)
        with pytest.raises(NotFoundError) as invented:
            await service.update(uuid.uuid4(), rename, ctx=home.ctx)

        assert theirs.value.status_code == invented.value.status_code == 404
        assert theirs.value.code == invented.value.code
        assert theirs.value.message == invented.value.message
        assert set(theirs.value.details or {}) == set(invented.value.details or {})

    async def test_a_knowledge_base_in_another_tenant_cannot_be_deleted_by_its_own_owner(
        self, db, rag_estate: RagEstate
    ) -> None:
        """`other_collection` carries the home user as its owner: owning it is not access."""
        home = rag_estate.home

        with pytest.raises(NotFoundError):
            await KnowledgeBaseService(db).delete(rag_estate.other_collection.id, ctx=home.ctx)

        assert await db.get(KnowledgeBase, rag_estate.other_collection.id) is not None

    async def test_another_tenants_default_base_is_not_reported_as_undeletable(
        self, db, rag_estate: RagEstate
    ) -> None:
        """ "Cannot delete the default knowledge base" is a statement about a row.

        The rule ran before the access check, so answering it for an id outside
        the caller's organization confirmed two things at once: that the id
        exists, and that it is that organization's default base.
        """
        theirs = await _kb_row(db, tenant=rag_estate.other, collection_name="other_default")
        home = rag_estate.home

        with pytest.raises(NotFoundError):
            await KnowledgeBaseService(db).delete(theirs.id, ctx=home.ctx)

    async def test_a_deployment_wide_base_is_refused_as_forbidden_rather_than_missing(
        self, db, rag_estate: RagEstate
    ) -> None:
        """The one write refusal that stays a 403 - and the reason it is not a leak.

        An app-scoped base is readable by every caller in the deployment by
        design, which this test asserts first: the `get` succeeds. Reporting the
        write as "not found" would therefore conceal nothing at all, while costing
        the caller the one sentence that explains why they were refused.
        """
        shared = await _kb_row(
            db, tenant=rag_estate.other, collection_name="deployment_wide", scope=KBScope.APP
        )
        service = KnowledgeBaseService(db)
        home = rag_estate.home

        assert await service.get(shared.id, ctx=home.ctx)

        with pytest.raises(AuthorizationError):
            await service.update(shared.id, KnowledgeBaseUpdate(name="renamed"), ctx=home.ctx)


async def _joined_tenant(db, tenant: Tenant, role: OrgRoleName) -> Tenant:
    """A second member of the same organization, shaped for `kb_api`."""
    ctx = await _join(db, tenant, role)
    user = await db.get(User, ctx.user_id)
    return Tenant(organization=tenant.organization, user=user, ctx=ctx)


class TestWritingToAKnowledgeBaseTakesMoreThanReading:
    """The per-KB write routes resolve write access, where they resolved read.

    A Viewer holds `collections:view` and nothing else, and these six routes
    used to ask only whether the base was *visible* - so a Viewer could upload,
    delete documents and point sync sources at any base they could see. Through
    the app rather than the service on purpose: the bug was the routes calling
    the read resolver, and a service-level test cannot say which resolver a
    route asks.
    """

    async def test_a_viewer_cannot_upload_into_a_base_they_can_read(
        self, db, kb_api: KbClient, rag_estate: RagEstate
    ) -> None:
        viewer = await _joined_tenant(db, rag_estate.home, OrgRoleName.VIEWER)
        # The refusal must arrive before the vector store is ever consulted.
        app.dependency_overrides[deps.get_vectorstore] = lambda: _NeverAsked()

        response = await kb_api(viewer).post(
            f"{settings.API_V1_STR}/kb/{rag_estate.home_collection.id}/documents",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

        assert response.status_code == 403

    async def test_a_viewer_cannot_delete_a_document(
        self, db, kb_api: KbClient, rag_estate: RagEstate
    ) -> None:
        viewer = await _joined_tenant(db, rag_estate.home, OrgRoleName.VIEWER)

        response = await kb_api(viewer).delete(
            f"{settings.API_V1_STR}/kb/{rag_estate.home_collection.id}"
            f"/documents/{rag_estate.home_document.id}",
        )

        assert response.status_code == 403
        assert await db.get(RAGDocument, rag_estate.home_document.id) is not None

    async def test_a_viewer_cannot_wire_a_sync_source(
        self, db, kb_api: KbClient, rag_estate: RagEstate
    ) -> None:
        """A sync source is a standing feed into the collection, not a one-off write."""
        viewer = await _joined_tenant(db, rag_estate.home, OrgRoleName.VIEWER)

        response = await kb_api(viewer).post(
            f"{settings.API_V1_STR}/kb/{rag_estate.home_collection.id}/sync-sources",
            json={"name": "Drive", "connector_type": "gdrive", "config": {"folder_id": "abc"}},
        )

        assert response.status_code == 403
        rows = await db.execute(
            select(SyncSource).where(
                SyncSource.collection_name == rag_estate.home_collection.collection_name
            )
        )
        assert [source.id for source in rows.scalars()] == [rag_estate.home_source.id]

    async def test_a_viewer_cannot_trigger_or_remove_a_sync_source(
        self, db, kb_api: KbClient, rag_estate: RagEstate
    ) -> None:
        viewer = await _joined_tenant(db, rag_estate.home, OrgRoleName.VIEWER)
        base = (
            f"{settings.API_V1_STR}/kb/{rag_estate.home_collection.id}"
            f"/sync-sources/{rag_estate.home_source.id}"
        )

        triggered = await kb_api(viewer).post(f"{base}/trigger")
        removed = await kb_api(viewer).delete(base)

        assert triggered.status_code == 403
        assert removed.status_code == 403
        assert await db.get(SyncSource, rag_estate.home_source.id) is not None

    async def test_an_owner_still_removes_a_sync_source(
        self, db, kb_api: KbClient, rag_estate: RagEstate
    ) -> None:
        """The check refuses a role, not the route: an editor's write still lands."""
        response = await kb_api(rag_estate.home).delete(
            f"{settings.API_V1_STR}/kb/{rag_estate.home_collection.id}"
            f"/sync-sources/{rag_estate.home_source.id}",
        )

        assert response.status_code == 204
        assert await db.get(SyncSource, rag_estate.home_source.id) is None

    async def test_an_edit_grant_lets_a_viewer_feed_the_shared_base(
        self, db, rag_estate: RagEstate
    ) -> None:
        """The reason the routes carry no `require(collections:edit)` gate.

        A role gate would refuse this Viewer before their grant was ever read;
        the service consults the grant and admits them on this one base.
        """
        viewer = await _join(db, rag_estate.home, OrgRoleName.VIEWER)
        service = KnowledgeBaseService(db)

        with pytest.raises(AuthorizationError):
            await service.get_for_write(rag_estate.home_collection.id, ctx=viewer)

        await SharingService(db).share(
            rag_estate.home.ctx,
            rag_estate.home_collection,
            resource_type=COLLECTION,
            subject_user_id=viewer.user_id,
            level=GrantLevel.EDIT,
        )

        resolved = await service.get_for_write(rag_estate.home_collection.id, ctx=viewer)
        assert resolved.id == rag_estate.home_collection.id


class TestReadingOneSyncSourcesHistory:
    """The log listing resolves the source first, rather than thinning its rows.

    It used to read every log carrying that source id, apply `limit` in SQL, and
    then drop the rows whose `collection_name` was not this base's. Nothing leaked
    - but a source can be repointed at another base, since `SyncSourceUpdate`
    carries `collection_name`, and its earlier runs keep the name they ran
    against. So the thinning happened after the page had been cut, and there was
    no way to page past the gap (#233).
    """

    async def test_a_source_from_another_base_is_missing_rather_than_empty(
        self, db, kb_api: KbClient, rag_estate: RagEstate
    ) -> None:
        """`200 []` says "this source has never run" for a source that is not ours.

        Both are a page rendering "no syncs yet", and one of them is a request that
        should have failed. Every other per-resource read on this surface reports a
        row it may not have as missing.
        """
        elsewhere = await _sync_source_row(
            db, tenant=rag_estate.home, collection_name=rag_estate.home_private.collection_name
        )
        await _sync_log_row(
            db,
            collection_name=rag_estate.home_private.collection_name,
            sync_source_id=elsewhere.id,
        )

        response = await kb_api(rag_estate.home).get(
            f"{settings.API_V1_STR}/kb/{rag_estate.home_collection.id}"
            f"/sync-sources/{elsewhere.id}/logs",
        )

        assert response.status_code == 404

    async def test_a_full_page_of_one_sources_history_comes_back_full(
        self, db, kb_api: KbClient, rag_estate: RagEstate
    ) -> None:
        """`limit` and `total` have to describe the same set of rows.

        This source ran twice against this base and once, before it was moved,
        against another. Asking for three runs used to answer with two and call it
        the whole history.
        """
        for collection_name in (
            rag_estate.home_collection.collection_name,
            rag_estate.home_private.collection_name,
            rag_estate.home_collection.collection_name,
        ):
            await _sync_log_row(
                db,
                collection_name=collection_name,
                sync_source_id=rag_estate.home_source.id,
            )

        response = await kb_api(rag_estate.home).get(
            f"{settings.API_V1_STR}/kb/{rag_estate.home_collection.id}"
            f"/sync-sources/{rag_estate.home_source.id}/logs?limit=3",
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 3
        assert body["total"] == 3


# -- how a collection reads its documents -------------------------------------


class _AcceptingStore:
    """A vector store that agrees a collection exists and records nothing else.

    The upload path creates the collection lazily before queueing the parse.
    These tests are about what is *recorded* and what is *refused*, both of
    which happen before a vector is written.
    """

    def __init__(self) -> None:
        self.created: list[str] = []

    async def create_collection(self, name: str) -> None:
        self.created.append(name)


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    """Accept uploads without writing files or starting a parse.

    Storage and task dispatch are stubbed; everything that decides *how* a
    document will be read is real, because that is what is under test. The
    queued call is captured so a test can assert an upload was accepted at all.
    """
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    storage = MagicMock()
    storage.save = AsyncMock(return_value="rag/collection/file.pdf")
    queued: list[str] = []

    monkeypatch.setattr(
        "app.services.rag_document.get_file_storage",
        lambda: storage,
    )

    def capture(session, coroutine, *, name: str) -> None:
        """Record the dispatch and close what would have parsed the file.

        It patches `spawn_after_commit` rather than `spawn` because that is what
        the upload path now hands the flow to (#417), and these tests run
        against a real session: left queued, the flow would start for real when
        the session committed.
        """
        coroutine.close()
        queued.append(name)

    monkeypatch.setattr("app.core.background.spawn_after_commit", capture)
    return queued


async def _collection_with(
    db, tenant: Tenant, *, name: str, config: IngestionConfig
) -> KnowledgeBase:
    """A collection created through the service that guards its configuration."""
    return await KnowledgeBaseService(db).create(
        KnowledgeBaseCreate(name=name, scope="org", collection_name=name, ingestion_config=config),
        ctx=tenant.ctx,
    )


async def _upload(
    db,
    tenant: Tenant,
    collection: KnowledgeBase,
    *,
    filename: str = "handbook.pdf",
    override: IngestionOverride | None = None,
) -> RAGDocument:
    """Put one file into a collection and return the row that records it."""
    service = RAGDocumentService(db)
    accepted = await service.dispatch_upload(
        ctx=tenant.ctx,
        collection=collection,
        file_data=b"%PDF-1.4 fake",
        filename=filename,
        replace=False,
        vector_store=_AcceptingStore(),
        override=override,
        organization_id=tenant.organization.id,
        knowledge_base_id=collection.id,
    )
    return await service.get_document(accepted.id)


class TestHowACollectionReadsItsDocuments:
    """The choice that used to be one environment variable per deployment.

    Two properties matter and neither is visible from a unit test: that what a
    collection was configured with is what its documents are actually parsed
    with, and that a departure for one upload stays inside that one upload.
    """

    async def test_a_collection_is_created_with_the_configuration_it_was_given(self, db) -> None:
        tenant = await _tenant(db, name="Legal")

        collection = await _collection_with(
            db,
            tenant,
            name="contracts",
            config=IngestionConfig(pdf_parser=PdfParserName.LITEPARSE, chunk_size=1024),
        )

        assert collection.ingestion_config["pdf_parser"] == "liteparse"
        assert collection.ingestion_config["chunk_size"] == 1024

    async def test_a_collection_with_no_opinion_gets_the_deployments(self, db) -> None:
        tenant = await _tenant(db, name="Casual")

        collection = await KnowledgeBaseService(db).create(
            KnowledgeBaseCreate(name="notes", scope="org", collection_name="notes"),
            ctx=tenant.ctx,
        )

        assert collection.ingestion_config == deployment_defaults().model_dump(mode="json")

    async def test_an_uploaded_document_is_read_the_way_its_collection_says(
        self, db, uploads
    ) -> None:
        """The record is not decoration: it is what the worker builds a parser from.

        Asserting on the stored JSON alone would pass against a pipeline that
        went on reading the environment, so this builds the parser the worker
        would build and looks at what it is.
        """
        tenant = await _tenant(db, name="Archive")
        collection = await _collection_with(
            db, tenant, name="scans", config=IngestionConfig(pdf_parser=PdfParserName.LITEPARSE)
        )

        document = await _upload(db, tenant, collection)

        assert document.ingestion_config["pdf_parser"] == "liteparse"
        processor = await IngestionConfigService(db).build_processor(
            document.organization_id, IngestionConfig.model_validate(document.ingestion_config)
        )
        assert isinstance(processor.pdf_parser, LiteParseParser)

    async def test_a_parser_that_cannot_be_built_is_refused_not_quietly_swapped(
        self, db, uploads, monkeypatch
    ) -> None:
        """LlamaParse without a key must not fall back to the local parser.

        A collection whose owner chose the cloud parser for scanned contracts
        and silently got PyMuPDF has an index full of blank pages and nothing
        anywhere saying so.
        """
        monkeypatch.setattr(settings, "LLAMAPARSE_API_KEY", "")
        tenant = await _tenant(db, name="Cloudless")
        collection = await _collection_with(
            db, tenant, name="cloud", config=IngestionConfig(pdf_parser=PdfParserName.LLAMAPARSE)
        )
        document = await _upload(db, tenant, collection)

        with pytest.raises(ValueError, match="LLAMAPARSE_API_KEY"):
            await IngestionConfigService(db).build_processor(
                document.organization_id, IngestionConfig.model_validate(document.ingestion_config)
            )

    async def test_an_override_wins_for_that_document_and_no_other(self, db, uploads) -> None:
        """The whole point of a per-upload setting, and the whole risk of one."""
        tenant = await _tenant(db, name="Mixed")
        collection = await _collection_with(
            db, tenant, name="mixed", config=IngestionConfig(pdf_parser=PdfParserName.PYMUPDF)
        )

        ordinary = await _upload(db, tenant, collection, filename="memo.pdf")
        odd_one = await _upload(
            db,
            tenant,
            collection,
            filename="scan.pdf",
            override=IngestionOverride(pdf_parser=PdfParserName.LITEPARSE, chunk_size=2048),
        )

        assert ordinary.ingestion_config["pdf_parser"] == "pymupdf"
        assert odd_one.ingestion_config["pdf_parser"] == "liteparse"
        assert odd_one.ingestion_config["chunk_size"] == 2048
        # and the collection itself is untouched, so the next upload is ordinary again
        await db.refresh(collection)
        assert collection.ingestion_config["pdf_parser"] == "pymupdf"
        assert (await _upload(db, tenant, collection)).ingestion_config["pdf_parser"] == "pymupdf"

    async def test_the_override_itself_is_recorded_so_the_departure_is_explainable(
        self, db, uploads
    ) -> None:
        """ "Why was this one parsed differently" has to survive the request.

        Only what was asked for is stored, not the merged result: a collection's
        configuration moves on, and a stored copy of it would later make every
        upload look like a departure.
        """
        tenant = await _tenant(db, name="Forensics")
        collection = await _collection_with(db, tenant, name="forensics", config=IngestionConfig())

        ordinary = await _upload(db, tenant, collection, filename="a.pdf")
        overridden = await _upload(
            db,
            tenant,
            collection,
            filename="b.pdf",
            override=IngestionOverride(pdf_parser=PdfParserName.LITEPARSE),
        )

        assert ordinary.ingestion_override is None
        assert overridden.ingestion_override == {"pdf_parser": "liteparse"}

    async def test_an_override_that_asks_for_nothing_is_not_a_departure(self, db, uploads) -> None:
        tenant = await _tenant(db, name="Empty")
        collection = await _collection_with(db, tenant, name="empty", config=IngestionConfig())

        document = await _upload(db, tenant, collection, override=IngestionOverride())

        assert document.ingestion_override is None

    async def test_the_override_travels_on_the_multipart_form_the_client_posts(
        self, db, uploads, kb_api: KbClient
    ) -> None:
        """The wire format, asserted where a client actually meets it.

        An upload is `multipart/form-data`, so the settings cannot ride along
        as a JSON body - they are one form field holding JSON. Proving the merge
        through the service would say nothing about whether that field is wired
        up, which is the half a frontend depends on.
        """
        tenant = await _tenant(db, name="Wire")
        collection = await _collection_with(
            db, tenant, name="wire", config=IngestionConfig(pdf_parser=PdfParserName.PYMUPDF)
        )
        app.dependency_overrides[deps.get_vectorstore] = lambda: _AcceptingStore()

        response = await kb_api(tenant).post(
            f"{settings.API_V1_STR}/kb/{collection.id}/documents",
            files={"file": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"ingestion": '{"pdf_parser": "liteparse", "chunk_size": 2048}'},
        )

        assert response.status_code == 202
        document = await RAGDocumentService(db).get_document(response.json()["id"])
        assert document.ingestion_config["pdf_parser"] == "liteparse"
        assert document.ingestion_config["chunk_size"] == 2048
        assert document.ingestion_override == {"pdf_parser": "liteparse", "chunk_size": 2048}

    async def test_a_malformed_override_is_refused_rather_than_quietly_ignored(
        self, db, uploads, kb_api: KbClient
    ) -> None:
        """A dropped setting would index the file the collection's way while
        the caller believed it had asked for something else."""
        tenant = await _tenant(db, name="Typo")
        collection = await _collection_with(db, tenant, name="typo", config=IngestionConfig())
        app.dependency_overrides[deps.get_vectorstore] = lambda: _AcceptingStore()

        response = await kb_api(tenant).post(
            f"{settings.API_V1_STR}/kb/{collection.id}/documents",
            files={"file": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"ingestion": '{"pdf_parser": "tesseract"}'},
        )

        assert response.status_code == 400
        rows = await db.execute(select(RAGDocument).where(RAGDocument.collection_name == "typo"))
        assert rows.scalars().all() == []

    async def test_a_document_names_the_model_that_read_its_images(self, db, uploads) -> None:
        """A profile can be renamed or deleted; what read this document cannot."""
        tenant = await _tenant(db, name="Diagrams")
        profile = await _keyed_model_profile(db, tenant)
        collection = await _collection_with(
            db,
            tenant,
            name="diagrams",
            config=IngestionConfig(
                describe_images=True,
                image_description=ImageDescription(model_profile_id=profile.id, temperature=0.2),
            ),
        )

        document = await _upload(db, tenant, collection)

        assert document.image_description_model == "openai:gpt-4.1"
        assert document.ingestion_config["image_description"]["temperature"] == 0.2

    async def test_a_collection_asking_for_a_model_the_org_has_not_got_is_refused_at_creation(
        self, db
    ) -> None:
        """The message belongs on the form that turned it on.

        Left to ingestion it would surface as a failed document, hours later,
        for somebody who did not configure anything.
        """
        tenant = await _tenant(db, name="Modelless")

        with pytest.raises(NotFoundError):
            await _collection_with(
                db,
                tenant,
                name="modelless",
                config=IngestionConfig(describe_images=True),
            )

    async def test_an_upload_naming_a_model_profile_that_is_not_the_organizations_is_refused(
        self, db, uploads
    ) -> None:
        """The one new way an override reaches outside the document it belongs to.

        Resolution is organization-scoped, so a profile id from another tenant
        is not "forbidden" but simply not found - the same answer their
        collections give.
        """
        home = await _tenant(db, name="Home")
        stranger = await _tenant(db, name="Stranger")
        theirs = await _keyed_model_profile(db, stranger)
        collection = await _collection_with(db, home, name="home_docs", config=IngestionConfig())

        with pytest.raises(NotFoundError):
            await _upload(
                db,
                home,
                collection,
                override=IngestionOverride(
                    describe_images=True,
                    image_description=ImageDescriptionOverride(model_profile_id=theirs.id),
                ),
            )

        rows = await db.execute(
            select(RAGDocument).where(RAGDocument.collection_name == "home_docs")
        )
        assert rows.scalars().all() == []


class TestTheEmbeddingModelACollectionWasBuiltWith:
    """The one setting that is not a preference.

    `PgVectorStore` creates a collection's table once, as
    `embedding vector(N)`. Until this was recorded per collection the only
    record was an environment variable, so changing it broke every existing
    collection with no error anybody could trace: either the width no longer
    matched and inserts failed, or - between two models that share a width -
    vectors from a different space were written next to the old ones and search
    went on answering, wrongly.
    """

    async def test_a_new_collection_records_the_model_and_width_it_was_built_at(self, db) -> None:
        tenant = await _tenant(db, name="Indexed")

        collection = await _collection_with(db, tenant, name="indexed", config=IngestionConfig())

        assert collection.embedding_model == settings.EMBEDDING_MODEL
        assert collection.embedding_dim == settings.rag.embeddings_config.dim

    async def test_a_changed_deployment_default_no_longer_strands_a_collection(
        self, db, uploads, monkeypatch
    ) -> None:
        """The store embeds each collection with its own recorded model.

        Changing `EMBEDDING_MODEL` used to make every existing collection
        refuse ingestion until the variable was restored. The default now only
        decides what *new* collections are built with - this one keeps
        indexing, and its documents keep recording the model that actually
        produced their vectors.
        """
        tenant = await _tenant(db, name="Switched")
        collection = await _collection_with(db, tenant, name="switched", config=IngestionConfig())
        built_with = collection.embedding_model
        monkeypatch.setattr(settings, "EMBEDDING_MODEL", "voyage-3")

        document = await _upload(db, tenant, collection)

        assert document.embedding_model == built_with

    async def test_a_document_records_the_model_its_vectors_came_from(self, db, uploads) -> None:
        tenant = await _tenant(db, name="Traceable")
        collection = await _collection_with(db, tenant, name="traceable", config=IngestionConfig())

        document = await _upload(db, tenant, collection)

        assert document.embedding_model == collection.embedding_model

    async def test_an_update_cannot_change_it(self, db) -> None:
        """There is no field for it on the update schema, and no back door.

        Asserted through the schema a client actually posts to rather than by
        reading the model definition: a field added later "for completeness"
        would pass a test that only looked at the service.
        """
        tenant = await _tenant(db, name="Persistent")
        collection = await _collection_with(db, tenant, name="persistent", config=IngestionConfig())
        built_with = collection.embedding_model

        await KnowledgeBaseService(db).update(
            collection.id,
            KnowledgeBaseUpdate.model_validate(
                {"name": "renamed", "embedding_model": "voyage-3", "embedding_dim": 1024}
            ),
            ctx=tenant.ctx,
        )

        await db.refresh(collection)
        assert collection.name == "renamed"
        assert collection.embedding_model == built_with

    async def test_changing_the_configuration_leaves_indexed_documents_alone(
        self, db, uploads
    ) -> None:
        """Re-parsing what is already indexed is not what an edit means."""
        tenant = await _tenant(db, name="Evolving")
        collection = await _collection_with(
            db, tenant, name="evolving", config=IngestionConfig(pdf_parser=PdfParserName.PYMUPDF)
        )
        already_there = await _upload(db, tenant, collection)

        await KnowledgeBaseService(db).update(
            collection.id,
            KnowledgeBaseUpdate(
                ingestion_config=IngestionConfig(pdf_parser=PdfParserName.LITEPARSE)
            ),
            ctx=tenant.ctx,
        )

        await db.refresh(already_there)
        assert already_there.ingestion_config["pdf_parser"] == "pymupdf"
        await db.refresh(collection)
        assert collection.ingestion_config["pdf_parser"] == "liteparse"


class TestWhatACollectionReportsItHolds:
    """The counts a picker shows, against a real `GROUP BY`.

    Aggregation is the half a mock cannot check: whether the grouping keys on
    the right column, whether the `FILTER` clause counts what it claims, and
    whether a collection with nothing in it comes back absent rather than zero.
    """

    async def test_counts_are_grouped_per_collection_and_do_not_bleed(self, db) -> None:
        """Two collections in one query must not pool their documents."""
        tenant = await _tenant(db, name="Counted")
        busy = await _collection_with(db, tenant, name="busy", config=IngestionConfig())
        quiet = await _collection_with(db, tenant, name="quiet", config=IngestionConfig())
        for index in range(3):
            await _rag_document(db, collection_name=busy.collection_name, filename=f"{index}.txt")
        await _rag_document(db, collection_name=quiet.collection_name, filename="only.txt")

        counts = await rag_document_repo.counts_by_collection(
            db, collections=[busy.collection_name, quiet.collection_name]
        )

        assert counts[busy.collection_name].documents == 3
        assert counts[quiet.collection_name].documents == 1

    async def test_a_collection_nothing_was_uploaded_to_is_absent_not_zero(self, db) -> None:
        """No row to group means no key, which is what the route defaults."""
        tenant = await _tenant(db, name="Empty")
        collection = await _collection_with(db, tenant, name="empty", config=IngestionConfig())

        counts = await rag_document_repo.counts_by_collection(
            db, collections=[collection.collection_name]
        )

        assert collection.collection_name not in counts

    async def test_only_finished_documents_count_as_indexed(self, db) -> None:
        """A failed upload stays in `documents` and drops out of `indexed`.

        This is what makes a half-broken collection legible on a listing: the
        two numbers disagreeing is the only signal that something died, since
        the vectors it never wrote leave no trace anywhere else.

        The statuses are `DocumentStatus` members rather than strings, and that
        is the whole of #148: this test used to set `"completed"` and
        `"failed"`, neither of which anything in the product writes, so it
        agreed with the query instead of with the pipeline and passed while
        every knowledge base reported `indexed_count: 0`.
        """
        tenant = await _tenant(db, name="Partial")
        collection = await _collection_with(db, tenant, name="partial", config=IngestionConfig())
        done = await _rag_document(
            db, collection_name=collection.collection_name, filename="ok.txt"
        )
        done.status = DocumentStatus.DONE
        done.chunk_count = 7
        broken = await _rag_document(
            db, collection_name=collection.collection_name, filename="dead.txt"
        )
        broken.status = DocumentStatus.ERROR
        broken.chunk_count = 0
        await db.flush()

        counts = await rag_document_repo.counts_by_collection(
            db, collections=[collection.collection_name]
        )

        assert counts[collection.collection_name].documents == 2
        assert counts[collection.collection_name].indexed == 1
        assert counts[collection.collection_name].chunks == 7

    async def test_the_pipeline_marking_a_document_done_makes_it_count_as_indexed(self, db) -> None:
        """The writer and the reader, in one test, with no status written by hand.

        `complete_ingestion` is the only thing that finishes a document, and
        `counts_by_collection` is what the listing reads - so a filter on a
        value the pipeline does not write can only be caught by running both.
        Nothing here names a status literal, which is the point: the two agree
        or this fails.
        """
        tenant = await _tenant(db, name="Finished")
        collection = await _collection_with(db, tenant, name="finished", config=IngestionConfig())
        doc = await _rag_document(
            db, collection_name=collection.collection_name, filename="handbook.md"
        )
        doc.status = DocumentStatus.PROCESSING
        await db.flush()

        await RAGDocumentService(db).complete_ingestion(
            str(doc.id),
            vector_document_id=doc.vector_document_id,
            chunk_count=4,
            replaced_document_id=None,
        )

        counts = await rag_document_repo.counts_by_collection(
            db, collections=[collection.collection_name]
        )

        assert counts[collection.collection_name].documents == 1
        assert counts[collection.collection_name].indexed == 1
        assert counts[collection.collection_name].chunks == 4

    async def test_re_ingesting_a_document_does_not_count_it_twice(self, db) -> None:
        """The vector store keeps one document; `rag_documents` gained a second row.

        Every ingest path creates a fresh tracking row, the replacing one
        included, so before the replaced row was retired a nightly sync reported
        a collection growing by its own size every night while the vectors never
        moved. `documents` was already wrong this way; the chunk sum only became
        visibly wrong once a real number was recorded (#147).
        """
        tenant = await _tenant(db, name="Reingested")
        collection = await _collection_with(db, tenant, name="again", config=IngestionConfig())
        first = await _rag_document(
            db, collection_name=collection.collection_name, filename="handbook.md"
        )
        first.chunk_count = 12
        second = await _rag_document(
            db, collection_name=collection.collection_name, filename="handbook.md"
        )
        second.chunk_count = 12
        await db.flush()

        await RAGDocumentService(db).complete_ingestion(
            str(second.id),
            vector_document_id=second.vector_document_id,
            chunk_count=12,
            replaced_document_id=first.vector_document_id,
        )

        counts = await rag_document_repo.counts_by_collection(
            db, collections=[collection.collection_name]
        )

        assert counts[collection.collection_name].documents == 1
        assert counts[collection.collection_name].chunks == 12
        assert await rag_document_repo.get_by_id(db, first.id) is None

    async def test_another_tenants_documents_are_not_counted(self, db) -> None:
        """The counts are keyed on `collection_name`, and `rag_documents` carries a
        nullable `organization_id` that a sync task never stamps - so the tenant
        boundary here is the set of collection names the caller was allowed to see,
        not a column on the document.

        That makes it worth asserting rather than assuming: a collection name is
        slug-plus-random and unique in practice, but the query is only ever safe
        because the caller hands it names `list_accessible` already filtered.
        """
        mine = await _tenant(db, name="Mine")
        theirs = await _tenant(db, name="Theirs")
        my_collection = await _collection_with(db, mine, name="mine", config=IngestionConfig())
        their_collection = await _collection_with(
            db, theirs, name="theirs", config=IngestionConfig()
        )
        await _rag_document(db, collection_name=my_collection.collection_name, filename="a.txt")
        for index in range(5):
            await _rag_document(
                db, collection_name=their_collection.collection_name, filename=f"{index}.txt"
            )

        # What the route does: count only over the names this caller may read.
        counts = await rag_document_repo.counts_by_collection(
            db, collections=[my_collection.collection_name]
        )

        assert counts[my_collection.collection_name].documents == 1
        assert their_collection.collection_name not in counts


# -- publish, run, approve ----------------------------------------------------


class TestPublishAndRollback:
    """What runs is a frozen version, and history stays linear."""

    async def test_publishing_freezes_a_version_the_agent_then_points_at(self, db) -> None:
        tenant = await _tenant(db, name="Publisher")
        model = await _default_model(db, tenant)
        registry = AgentRegistryService(db)
        agent = await registry.create(
            tenant.ctx, AgentSpec(name="Support", model_profile_id=model.id)
        )

        version = await registry.publish(tenant.ctx, agent.id, note="first cut")

        stored = (
            (await db.execute(select(AgentVersion).where(AgentVersion.agent_id == agent.id)))
            .scalars()
            .all()
        )
        assert [row.id for row in stored] == [version.id]
        assert version.version == 1
        assert agent.current_version_id == version.id
        assert agent.status == AgentStatus.PUBLISHED.value

    async def test_a_draft_edit_does_not_change_what_runs(self, db) -> None:
        """The whole reason an agent is two tables: editing is not deploying."""
        tenant = await _tenant(db, name="Editor")
        model = await _default_model(db, tenant)
        registry = AgentRegistryService(db)
        agent = await registry.create(
            tenant.ctx, AgentSpec(name="Support", model_profile_id=model.id)
        )
        published = await registry.publish(tenant.ctx, agent.id)

        await registry.save_draft(
            tenant.ctx,
            agent.id,
            AgentSpec(name="Support", model_profile_id=model.id, instructions="rewritten"),
        )

        assert agent.current_version_id == published.id
        stored = await db.get(AgentVersion, published.id)
        # The published version keeps what it was published with - which is the
        # starting prompt a new agent is created with, not the rewrite that only
        # ever reached the draft.
        assert stored.spec["instructions"] != "rewritten"
        assert stored.spec["instructions"].startswith("You are a helpful assistant.")

    async def test_rolling_back_writes_a_new_version_instead_of_moving_the_pointer(
        self, db
    ) -> None:
        """History must show that a rollback happened, not that v2 never existed.

        Moving `current_version_id` backwards would be cheaper and would make
        every run recorded against v2 unexplainable.
        """
        tenant = await _tenant(db, name="Roller")
        model = await _default_model(db, tenant)
        registry = AgentRegistryService(db)
        agent = await registry.create(
            tenant.ctx, AgentSpec(name="Support", model_profile_id=model.id)
        )

        first = await registry.publish(tenant.ctx, agent.id)
        await registry.save_draft(
            tenant.ctx,
            agent.id,
            AgentSpec(name="Support", model_profile_id=model.id, instructions="a regrettable idea"),
        )
        second = await registry.publish(tenant.ctx, agent.id)

        third = await registry.rollback(tenant.ctx, agent.id, to_version_id=first.id)

        versions, total = await registry.list_versions(tenant.ctx, agent.id)
        assert sorted(row.version for row in versions) == [1, 2, 3]
        assert total == 3
        assert third.id not in (first.id, second.id)
        # And the pointer stays where the default environment is: a rollback is a
        # publish of an older spec, so it lands the same way. Putting the old
        # version back in front of people is a promotion, one click on its
        # history row - not a side effect of restoring the draft.
        assert agent.current_version_id == first.id
        restored = await db.get(AgentVersion, third.id)
        original = await db.get(AgentVersion, first.id)
        assert restored.spec == original.spec

    async def test_the_oldest_versions_stay_reachable_a_page_at_a_time(self, db) -> None:
        """The listing was capped at fifty with no offset, and reported the cap
        as the total. An agent published past that had versions no page could
        reach - including whichever one an environment is still pinned to."""
        tenant = await _tenant(db, name="Prolific")
        model = await _default_model(db, tenant)
        registry = AgentRegistryService(db)
        agent = await registry.create(
            tenant.ctx, AgentSpec(name="Support", model_profile_id=model.id)
        )
        for turn in range(6):
            await registry.save_draft(
                tenant.ctx,
                agent.id,
                AgentSpec(
                    name="Support", model_profile_id=model.id, instructions=f"attempt {turn}"
                ),
            )
            await registry.publish(tenant.ctx, agent.id)

        first, total = await registry.list_versions(tenant.ctx, agent.id, limit=4)
        last, _ = await registry.list_versions(tenant.ctx, agent.id, skip=4, limit=4)

        # Newest first, and the total is every version rather than this page's.
        assert [row.version for row in first] == [6, 5, 4, 3]
        assert [row.version for row in last] == [2, 1]
        assert total == 6

    async def test_an_agent_that_was_never_published_cannot_be_run(self, db) -> None:
        tenant = await _tenant(db, name="Hasty")
        model = await _default_model(db, tenant)
        registry = AgentRegistryService(db)
        agent = await registry.create(
            tenant.ctx, AgentSpec(name="Support", model_profile_id=model.id)
        )

        with pytest.raises(BadRequestError):
            await registry.get_runnable_spec(tenant.ctx, agent.id)


class TestPromotingASpecialist:
    """Keeping a specialist without losing where it came from (agenticos#177).

    A specialist that earned its own version has one honest exit: become a draft
    agent, owned by whoever promoted it, checked and published like any other. These
    prove the exit does exactly that and no more - it does not publish, does not pin,
    and does not touch what it came from.
    """

    async def test_a_dynamic_specialist_publishes_unedited_and_runs_as_it_did(self, db) -> None:
        """The acceptance criterion for the chat half: a specialist a model invented
        becomes a draft that publishes with no further editing, and the published
        agent carries its instructions and its model - so it answers as it did."""
        tenant = await _tenant(db, name="Promoter")
        profile = await _keyed_model_profile(db, tenant)
        registry = AgentRegistryService(db)
        # As a model invents one: instructions and a model, and nothing else.
        specialist = SpecialistSpec(
            name="invoice-parser",
            description="Pulls the line items out of an invoice",
            instructions="Read the invoice and return its line items as JSON.",
            model_profile_id=profile.id,
        )

        draft = await registry.promote_specialist(
            tenant.ctx, specialist, fallback_model_profile_id=None
        )
        # Publishes without a single further edit - the whole claim of the issue.
        await registry.publish(tenant.ctx, draft.id)
        _, runnable, _ = await registry.get_runnable_spec(tenant.ctx, draft.id)

        assert draft.owner_user_id == tenant.user.id
        assert runnable.instructions == specialist.instructions
        assert runnable.model_profile_id == profile.id
        # A dynamic specialist has none, and promotion invents none for it.
        assert runnable.capabilities == []
        prepared = await AgentRunnerService(db).prepare(tenant.ctx, draft.id)
        assert await _answer(prepared) == "thirty days"

    async def test_promoting_an_inline_specialist_leaves_the_parent_untouched(self, db) -> None:
        """The acceptance criterion for the Builder half: the parent is unchanged -
        the specialist is not removed from it and the new agent is not pinned back
        onto it. A specialist on 'the same model as its parent' takes the parent's
        model as a standalone agent, which is what the fallback is for."""
        tenant = await _tenant(db, name="Parent owner")
        model = await _default_model(db, tenant)
        registry = AgentRegistryService(db)
        specialist = SpecialistSpec(
            name="summariser",
            description="Summarises in three bullets",
            instructions="Summarise the input in three bullets.",
        )
        parent = await registry.create(
            tenant.ctx,
            AgentSpec(
                name="Desk",
                model_profile_id=model.id,
                capabilities=[
                    CapabilityBindingSpec(
                        id="subagents",
                        config={"inline": [specialist.model_dump(mode="json")]},
                    )
                ],
            ),
        )
        before = copy.deepcopy(parent.draft_spec)

        promoted = await registry.promote_specialist(
            tenant.ctx, specialist, fallback_model_profile_id=model.id
        )

        refreshed = await registry.get(tenant.ctx, parent.id)
        # Parent unchanged: the inline specialist is still there and nothing was
        # pinned onto it.
        assert refreshed.draft_spec == before
        assert promoted.id != parent.id
        assert promoted.owner_user_id == tenant.user.id
        assert promoted.draft_spec["instructions"] == specialist.instructions
        # "Same model as its parent" resolved to a concrete model on the standalone,
        # and no delegates pinned onto the new agent.
        assert promoted.draft_spec["model_profile_id"] == str(model.id)
        assert promoted.draft_spec["subagents"] == []

    async def test_it_is_owned_by_whoever_promoted_it_not_whoever_ran_it(self, db) -> None:
        """The security-shaped criterion. A specialist a model invented inside one
        member's run does not become that member's agent - it becomes the agent of
        whoever kept it. `create` stamps the promoter as owner; the `agents:edit`
        gate a run's audience does not clear is proven at the route in
        tests/api/test_platform_routes.py."""
        tenant = await _tenant(db, name="Org")
        profile = await _keyed_model_profile(db, tenant)
        keeper = await _join(db, tenant, OrgRoleName.MEMBER)
        specialist = SpecialistSpec(
            name="researcher",
            description="Finds and cites sources",
            instructions="Research the topic and cite your sources.",
            model_profile_id=profile.id,
        )

        draft = await AgentRegistryService(db).promote_specialist(
            keeper, specialist, fallback_model_profile_id=None
        )

        assert draft.owner_user_id == keeper.user_id
        assert draft.owner_user_id != tenant.user.id


class TestRenamingAToolOnAPublishedAgent:
    """`tool_overrides` through publish and back out of the database.

    Both halves need real rows. The refusals are only real if the publish path
    actually runs them - a spec that saves as a draft and fails on the way to a
    version is the whole point of validating there. And the gate's names have to
    survive the round trip through JSONB: the spec that decides them is not the
    object somebody built, it is the one a run reads back.
    """

    @staticmethod
    async def _draft(db, tenant: Tenant, binding: dict) -> Agent:
        model = await _default_model(db, tenant)
        return await AgentRegistryService(db).create(
            tenant.ctx, AgentSpec(name="Support", model_profile_id=model.id, capabilities=[binding])
        )

    async def test_an_override_for_a_tool_the_capability_does_not_have_is_refused(self, db) -> None:
        """The dangerous typo: it changes nothing and says nothing at run time."""
        tenant = await _tenant(db, name="Typo")
        agent = await self._draft(
            db,
            tenant,
            {"id": "knowledge", "tool_overrides": {"search_docuemnts": {"name": "search_orders"}}},
        )

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(db).publish(tenant.ctx, agent.id)

        assert any("search_docuemnts" in problem for problem in refused.value.details["problems"])

    async def test_a_name_the_model_could_not_call_is_refused(self, db) -> None:
        """The model has to emit this string; a space makes the tool unreachable."""
        tenant = await _tenant(db, name="Spacey")
        agent = await self._draft(
            db,
            tenant,
            {"id": "knowledge", "tool_overrides": {"search_documents": {"name": "search orders"}}},
        )

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(db).publish(tenant.ctx, agent.id)

        assert any("cannot call" in problem for problem in refused.value.details["problems"])

    async def test_a_renamed_tool_is_still_the_one_a_run_asks_a_human_about(self, db) -> None:
        """Decided by the tool's id, answered with the name the model will call.

        The gate matches what the model called. If the stored spec resolved back
        to the *declared* name, the gate would wait for a tool nobody calls and
        the renamed one would run unattended - with nothing reporting it.
        """
        tenant = await _tenant(db, name="Renamer")
        agent = await self._draft(
            db,
            tenant,
            {
                "id": "knowledge",
                "approval": "required",
                "tool_overrides": {"search_documents": {"name": "search_refund_policy"}},
            },
        )
        registry = AgentRegistryService(db)
        await registry.publish(tenant.ctx, agent.id)

        _, published, _ = await registry.get_runnable_spec(tenant.ctx, agent.id)

        assert published.capabilities[0].tool_approval == {}
        assert approval_required_tools(published) == frozenset({"search_refund_policy"})


class TestManagingTheOrganizationsMcpServers:
    """The write half of the scope rule, against real rows.

    The read half is proven below: a personal connection carrying the right
    `organization_id` does not satisfy an org binding. The same trap exists on
    every write - a filter on the organization alone would let one member edit
    or delete another member's personal connection through routes that never ask
    whose it is, and would let an admin in one tenant reach into another.
    """

    # A literal address, so the SSRF validator short-circuits instead of
    # resolving a hostname that does not exist.
    URL = "https://93.184.216.34/mcp"

    async def test_the_credential_is_sealed_for_this_organization_and_no_other(self, db) -> None:
        """The row is the vault's whole point. A ciphertext that another tenant
        could unwrap would make the envelope decoration."""
        tenant = await _tenant(db, name="Sealed")

        connection = await McpConnectionService(db).create_for_org(
            tenant.ctx,
            OrgMcpConnectionCreate(name="github", url=self.URL, auth_token="ghp-secret-9876"),
        )

        assert connection.auth_token is not None
        assert "ghp-secret-9876" not in connection.auth_token
        assert (
            unseal(
                connection.auth_token,
                scope=VaultScope.organization(tenant.organization.id),
                key_version=connection.secret_key_version,
            )
            == "ghp-secret-9876"
        )
        with pytest.raises(BadRequestError):
            unseal(
                connection.auth_token,
                scope=VaultScope.organization(uuid.uuid4()),
                key_version=connection.secret_key_version,
            )

    async def test_a_created_server_belongs_to_the_organization_and_to_nobody(self, db) -> None:
        tenant = await _tenant(db, name="Owned")

        connection = await McpConnectionService(db).create_for_org(
            tenant.ctx,
            OrgMcpConnectionCreate(name="linear", url=self.URL, catalog_key="linear"),
        )

        assert (connection.scope, connection.user_id) == ("org", None)
        assert connection.organization_id == tenant.organization.id
        assert connection.created_by_user_id == tenant.user.id
        assert connection.catalog_key == "linear"

    async def test_listing_shows_the_organizations_servers_and_nothing_else(self, db) -> None:
        tenant = await _tenant(db, name="Listing")
        other = await _tenant(db, name="Neighbour")
        shared = await _mcp_connection(db, tenant, name="linear", scope="org")
        await _mcp_connection(db, tenant, name="notion", scope="user")
        await _mcp_connection(db, other, name="github", scope="org")

        items, total = await McpConnectionService(db).list_for_org(tenant.ctx)

        assert ([c.id for c in items], total) == ([shared.id], 1)

    @pytest.mark.parametrize(
        "write",
        [
            pytest.param(
                lambda service, ctx, connection_id: service.update_for_org(
                    ctx,
                    connection_id=connection_id,
                    data=OrgMcpConnectionUpdate(is_enabled=False),
                ),
                id="update",
            ),
            pytest.param(
                lambda service, ctx, connection_id: service.delete_for_org(
                    ctx, connection_id=connection_id
                ),
                id="delete",
            ),
            pytest.param(
                lambda service, ctx, connection_id: service.test_for_org(
                    ctx, connection_id=connection_id
                ),
                id="test",
            ),
        ],
    )
    async def test_another_organizations_server_cannot_be_written_to(self, db, write) -> None:
        mine = await _tenant(db, name="Mine")
        theirs = await _tenant(db, name="Theirs")
        connection = await _mcp_connection(db, theirs, name="linear", scope="org")

        with pytest.raises(NotFoundError):
            await write(McpConnectionService(db), mine.ctx, connection.id)

        await db.refresh(connection)
        assert connection.is_enabled is True

    @pytest.mark.parametrize(
        "write",
        [
            pytest.param(
                lambda service, ctx, connection_id: service.update_for_org(
                    ctx,
                    connection_id=connection_id,
                    data=OrgMcpConnectionUpdate(is_enabled=False),
                ),
                id="update",
            ),
            pytest.param(
                lambda service, ctx, connection_id: service.delete_for_org(
                    ctx, connection_id=connection_id
                ),
                id="delete",
            ),
        ],
    )
    async def test_a_members_own_connection_cannot_be_written_to_as_the_organizations(
        self, db, write
    ) -> None:
        """The row carries this exact `organization_id`, so a filter on the
        organization alone finds it. It is still refused, and it has to be: this
        is somebody's personal credential, reachable here by an admin who never
        asked whose it was - and editable into pointing anywhere.
        """
        tenant = await _tenant(db, name="Personal")
        personal = await _mcp_connection(db, tenant, name="notion", scope="user")

        with pytest.raises(NotFoundError):
            await write(McpConnectionService(db), tenant.ctx, personal.id)

        await db.refresh(personal)
        assert (personal.is_enabled, personal.scope) == (True, "user")


class TestBindingAnMcpServerToAnAgent:
    """`mcp_server_ids` against real rows - the only place the scope rule is real.

    A mock can be told that a connection is organization-scoped. Whether the
    query actually says so - and therefore whether a member's personal token can
    be smuggled into an agent everybody runs - is a question only Postgres
    answers.
    """

    @staticmethod
    async def _draft(db, tenant: Tenant, connection_ids: list[uuid.UUID]) -> Agent:
        model = await _default_model(db, tenant)
        return await AgentRegistryService(db).create(
            tenant.ctx,
            AgentSpec(name="Support", model_profile_id=model.id, mcp_server_ids=connection_ids),
        )

    async def test_an_organization_connection_publishes(self, db) -> None:
        tenant = await _tenant(db, name="Bound")
        connection = await _mcp_connection(db, tenant, name="linear", scope="org")
        agent = await self._draft(db, tenant, [connection.id])

        version = await AgentRegistryService(db).publish(tenant.ctx, agent.id)

        assert version.spec["mcp_server_ids"] == [str(connection.id)]

    async def test_a_personal_connection_cannot_be_bound_to_a_published_agent(self, db) -> None:
        """The row belongs to this organization and to the person publishing it.

        It is still refused: a published agent runs for everybody, and a token
        one member pasted into their own settings is not everybody's to spend.
        """
        tenant = await _tenant(db, name="Personal")
        connection = await _mcp_connection(db, tenant, name="linear", scope="user")
        agent = await self._draft(db, tenant, [connection.id])

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(db).publish(tenant.ctx, agent.id)

        assert str(connection.id) in refused.value.details["problems"][0]

    async def test_another_organizations_connection_is_refused_at_publish(self, db) -> None:
        """Ids in a spec are just data - an exported spec can name anything."""
        mine = await _tenant(db, name="Mine")
        theirs = await _tenant(db, name="Theirs")
        connection = await _mcp_connection(db, theirs, name="linear", scope="org")
        agent = await self._draft(db, mine, [connection.id])

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(db).publish(mine.ctx, agent.id)

        assert str(connection.id) in refused.value.details["problems"][0]

    async def test_a_run_attaches_the_bound_server_and_nothing_else(self, db, monkeypatch) -> None:
        """What the agent reaches is what it named - not everything the org has.

        The probe is replaced because it would dial out; everything up to it is
        real, which is the part that decides which servers a run may talk to.
        """
        tenant = await _tenant(db, name="Runner")
        bound = await _mcp_connection(db, tenant, name="linear", scope="org")
        await _mcp_connection(db, tenant, name="github", scope="org")
        personal = await _mcp_connection(db, tenant, name="notion", scope="user")
        seen: list[list[str]] = []

        async def fake_build(specs) -> list[str]:
            seen.append([spec.name for spec in specs])
            return []

        monkeypatch.setattr("app.services.mcp_connection.build_mcp_toolsets", fake_build)

        await build_toolsets_for_agent(
            db,
            organization_id=tenant.organization.id,
            connection_ids=[bound.id, personal.id],
        )

        assert seen == [["linear"]]


class TestLockingAnMcpConnectionBeforeSpendingItsRefreshToken:
    """The row lock that stops two chat turns redeeming one refresh token.

    A compiled statement can show that the eager join was dropped and that
    `populate_existing` was asked for. Only a database can say what those two
    options are worth, and both answers are severe: Postgres refuses
    `FOR UPDATE` on the nullable side of an outer join outright, so a lock
    taken with `McpConnection.user` still joined does not merely serialize
    badly - it raises, and every OAuth refresh becomes a failed turn. And a lock
    granted over a stale identity-map copy would hand back exactly the expired
    token the caller waited for the lock to stop using.
    """

    async def test_the_row_can_be_locked_despite_the_models_eager_join(self, db) -> None:
        tenant = await _tenant(db, name="Locker")
        connection = await _mcp_connection(db, tenant, name="linear", scope="org")

        locked = await mcp_connection_repo.get_by_id_for_update(db, connection.id)

        assert locked is not None
        assert locked.id == connection.id

    async def test_the_locked_row_shows_what_the_database_holds_not_what_the_session_cached(
        self, db
    ) -> None:
        """The winner of the lock writes a new payload; the loser is holding an
        ORM instance that predates it. Re-reading the columns is the whole
        mechanism by which the loser stops re-spending the old refresh token -
        without it SQLAlchemy keeps every attribute the session already loaded
        and hands back the expired token the lock was waited on to replace.

        The row is loaded the way a chat turn loads it, because that is what
        puts a fully populated copy in the identity map; the competing write is
        raw SQL, which is what a second transaction looks like from here.
        """
        tenant = await _tenant(db, name="Loser")
        created = await _mcp_connection(db, tenant, name="linear", scope="org")
        connection = await mcp_connection_repo.get_by_id(db, created.id)
        assert connection is not None and connection.oauth_payload is None

        await db.execute(
            text("UPDATE mcp_connections SET oauth_payload = :payload WHERE id = :id"),
            {"payload": "written-by-the-winner", "id": created.id},
        )
        assert connection.oauth_payload is None  # the session still believes otherwise

        locked = await mcp_connection_repo.get_by_id_for_update(db, created.id)

        assert locked is not None
        assert locked.oauth_payload == "written-by-the-winner"


class TestDecidingAnApproval:
    async def test_a_decision_records_who_made_it(self, db) -> None:
        """The point of the queue is attribution - an anonymous approval is a rubber stamp."""
        tenant = await _tenant(db, name="Approver")
        agent = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="support",
        )
        run = await _run_row(
            db,
            organization_id=tenant.organization.id,
            agent_id=agent.id,
            cost=Decimal("0"),
            started_at=datetime.now(UTC),
        )
        approvals = ApprovalService(db)
        approval = await approvals.request(
            approval_id=uuid.uuid4(),
            organization_id=tenant.organization.id,
            run_id=run.id,
            agent_id=agent.id,
            tool_id="send_email",
            tool_args={"to": "customer@example.com"},
        )

        decided = await approvals.decide(tenant.ctx, approval.id, approved=True, note="fine")

        assert decided.status == ApprovalStatus.APPROVED.value
        assert decided.decided_by_user_id == tenant.user.id
        assert decided.decided_at is not None

    async def test_a_decided_call_cannot_be_decided_again(self, db) -> None:
        """Two decisions would leave the trail unable to say who authorised the action."""
        tenant = await _tenant(db, name="Twice")
        agent = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="support",
        )
        run = await _run_row(
            db,
            organization_id=tenant.organization.id,
            agent_id=agent.id,
            cost=Decimal("0"),
            started_at=datetime.now(UTC),
        )
        approvals = ApprovalService(db)
        approval = await approvals.request(
            approval_id=uuid.uuid4(),
            organization_id=tenant.organization.id,
            run_id=run.id,
            agent_id=agent.id,
            tool_id="send_email",
            tool_args={},
        )
        await approvals.decide(tenant.ctx, approval.id, approved=False)

        with pytest.raises(BadRequestError):
            await approvals.decide(tenant.ctx, approval.id, approved=True)

        assert (await db.get(ToolApproval, approval.id)).status == ApprovalStatus.REJECTED.value


# -- money --------------------------------------------------------------------


class TestBudgetAccumulation:
    """Costs are what a budget stops a runaway agent against, so they must add up."""

    async def test_a_months_runs_sum_exactly(self, db) -> None:
        """The same three values as floats give 0.6000000000000001.

        Numeric all the way through - column, sum, and the value the service
        returns - is what keeps a monthly total reconcilable against an invoice.
        """
        tenant = await _tenant(db, name="Spender")
        agent = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="support",
        )
        now = datetime.now(UTC)
        for cost in (Decimal("0.1"), Decimal("0.2"), Decimal("0.3")):
            await _run_row(
                db,
                organization_id=tenant.organization.id,
                agent_id=agent.id,
                cost=cost,
                started_at=now,
            )

        total = await AgentRunnerService(db).monthly_spend(tenant.ctx)

        assert isinstance(total, Decimal)
        assert total == Decimal("0.6")

    async def test_last_months_spend_is_not_carried_over(self, db) -> None:
        """A calendar month, not a rolling window: budgets reset on the first."""
        tenant = await _tenant(db, name="Carryover")
        agent = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="support",
        )
        boundary = month_start()
        await _run_row(
            db,
            organization_id=tenant.organization.id,
            agent_id=agent.id,
            cost=Decimal("50"),
            started_at=boundary - timedelta(seconds=1),
        )
        await _run_row(
            db,
            organization_id=tenant.organization.id,
            agent_id=agent.id,
            cost=Decimal("0.25"),
            started_at=boundary,
        )

        assert await AgentRunnerService(db).monthly_spend(tenant.ctx) == Decimal("0.25")
        assert await agent_run_repo.sum_cost_since(
            db,
            organization_id=tenant.organization.id,
            since=boundary - timedelta(days=40),
        ) == Decimal("50.25")

    async def test_one_agents_spend_excludes_its_neighbours(self, db) -> None:
        """A per-agent budget must not be spent by a different agent."""
        tenant = await _tenant(db, name="Neighbours")
        watched = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="watched",
        )
        noisy = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="noisy",
        )
        now = datetime.now(UTC)
        await _run_row(
            db,
            organization_id=tenant.organization.id,
            agent_id=watched.id,
            cost=Decimal("0.75"),
            started_at=now,
        )
        await _run_row(
            db,
            organization_id=tenant.organization.id,
            agent_id=noisy.id,
            cost=Decimal("12.5"),
            started_at=now,
        )

        runner = AgentRunnerService(db)
        assert await runner.monthly_spend(tenant.ctx, agent_id=watched.id) == Decimal("0.75")
        assert await runner.monthly_spend(tenant.ctx) == Decimal("13.25")


class TestIngestionUnderTheOrganizationsCap:
    """Ingesting is spending, so the cap that stops a run stops an upload too.

    Real rows, because the seam under test is the sum: the spend that blocks
    this upload is itself an ingestion row, which is exactly the money the
    organization's total used to be blind to.
    """

    async def test_an_upload_against_a_spent_cap_is_refused_before_anything_is_kept(
        self, db, uploads
    ) -> None:
        tenant = await _tenant(db, name="CappedDocs", monthly_budget_usd=Decimal("10"))
        collection = await _collection_with(
            db, tenant, name="capped_docs", config=IngestionConfig()
        )
        await ingestion_spend_repo.record(
            db,
            organization_id=tenant.organization.id,
            rag_document_id=None,
            model="text-embedding-3-large",
            input_tokens=80_000_000,
            output_tokens=0,
            cost_usd=Decimal("10.40"),
            cost_is_partial=False,
        )

        with pytest.raises(BudgetExceeded) as refused:
            await _upload(db, tenant, collection)

        assert refused.value.scope is BudgetScope.ORGANIZATION
        # Refused before anything was persisted: no parse was queued and no
        # document row sits in the listing waiting for a worker that will
        # never come.
        assert uploads == []
        remaining = await db.execute(
            select(RAGDocument).where(RAGDocument.collection_name == "capped_docs")
        )
        assert remaining.scalars().all() == []

    async def test_an_upload_under_the_cap_is_accepted(self, db, uploads) -> None:
        """A ceiling that refuses uploads below it is an outage, not a budget."""
        tenant = await _tenant(db, name="RoomyDocs", monthly_budget_usd=Decimal("10"))
        collection = await _collection_with(db, tenant, name="roomy_docs", config=IngestionConfig())

        document = await _upload(db, tenant, collection)

        assert document.status == "processing"
        assert len(uploads) == 1


class TestTheOrganizationsMonthlyCap:
    """The ceiling over every agent an organization has, enforced on a real run.

    An organization used to have as many caps as it had agents and no ceiling:
    each agent's own limit could be right and the bill still be twelve times
    what anybody signed off. The runner accepted an organization-wide cap and no
    caller ever supplied one, so the parameter looked like the control existed.

    These drive the real runner against real rows, because that is the part that
    was wrong. A unit test with the cap handed in would have passed against the
    broken code - the number was never the problem, the lookup was.
    """

    @staticmethod
    async def _prepare(db, tenant: Tenant, *, spec: AgentSpec, spent: Decimal):
        """A published agent under this tenant, with `spent` already booked.

        Committed, not only flushed: the budget baseline is read on a session
        of its own (#12), the way production reads it, and what it can see is
        what the database has agreed to - which a terminal run row always is.
        """
        await _keyed_model_profile(db, tenant)
        agent = await _published_agent(db, tenant, spec=spec)
        await _run_row(
            db,
            organization_id=tenant.organization.id,
            agent_id=agent.id,
            cost=spent,
            started_at=datetime.now(UTC),
        )
        await db.commit()
        return await AgentRunnerService(db).prepare(tenant.ctx, agent.id)

    async def test_a_run_is_refused_once_the_organization_is_over_its_cap(self, db) -> None:
        """No caller passes this cap, so nothing but the lookup can produce it.

        The agent below has no budget of its own - under the old code its run
        was unlimited, which is the whole defect.
        """
        tenant = await _tenant(db, name="Capped", monthly_budget_usd=Decimal("10"))
        prepared = await self._prepare(
            db, tenant, spec=AgentSpec(name="Support"), spent=Decimal("10.5")
        )

        with pytest.raises(BudgetExceeded) as refused:
            await _answer(prepared)

        assert refused.value.limit_usd == Decimal("10")
        assert refused.value.spent_usd == Decimal("10.5")
        # Which of two possible caps stopped it. An operator told only "budget
        # exhausted" has to guess, and guessing wrong means editing an agent
        # that was never the constraint.
        assert refused.value.scope is BudgetScope.ORGANIZATION
        assert "Organization monthly budget exhausted" in str(refused.value)

    async def test_a_run_under_the_cap_answers_normally(self, db) -> None:
        """A ceiling that stops runs below it is an outage, not a budget."""
        tenant = await _tenant(db, name="Roomy", monthly_budget_usd=Decimal("10"))
        prepared = await self._prepare(
            db, tenant, spec=AgentSpec(name="Support"), spent=Decimal("2")
        )

        assert await _answer(prepared) == "thirty days"

    async def test_an_agents_own_cap_tightens_the_organizations(self, db) -> None:
        """$5 under a $50 ceiling binds at $5, and says it was the agent's."""
        tenant = await _tenant(db, name="Tightened", monthly_budget_usd=Decimal("50"))
        prepared = await self._prepare(
            db,
            tenant,
            spec=AgentSpec(name="Support", budget={"monthly_usd": 5}),
            spent=Decimal("6"),
        )

        with pytest.raises(BudgetExceeded) as refused:
            await _answer(prepared)

        assert refused.value.limit_usd == Decimal("5")
        assert refused.value.scope is BudgetScope.AGENT

    async def test_an_agents_own_cap_cannot_loosen_the_organizations(self, db) -> None:
        """$100 asked for under a $10 ceiling still stops at $10.

        The direction that matters: anyone who can edit an agent could otherwise
        raise its monthly number and spend past the organization's limit without
        touching a setting they are not allowed to touch.
        """
        tenant = await _tenant(db, name="Ambitious", monthly_budget_usd=Decimal("10"))
        prepared = await self._prepare(
            db,
            tenant,
            spec=AgentSpec(name="Support", budget={"monthly_usd": 100}),
            spent=Decimal("12"),
        )

        with pytest.raises(BudgetExceeded) as refused:
            await _answer(prepared)

        assert refused.value.limit_usd == Decimal("10")
        assert refused.value.scope is BudgetScope.ORGANIZATION

    async def test_the_cap_is_read_for_the_organization_that_is_running(self, db) -> None:
        """One organization's ceiling must not stop another organization's agent.

        Spend is per organization and so is the cap; a lookup that fetched the
        wrong tenant's row would be both a leak and a wrong answer, and with a
        single capped organization in the fixture it would still pass every
        other test here.
        """
        capped = await _tenant(db, name="Capped", monthly_budget_usd=Decimal("10"))
        uncapped = await _tenant(db, name="Uncapped")
        await self._prepare(
            db,
            capped,
            spec=AgentSpec(name="Support"),
            spent=Decimal("99"),
        )
        prepared = await self._prepare(
            db,
            uncapped,
            spec=AgentSpec(name="Support"),
            spent=Decimal("99"),
        )

        assert await _answer(prepared) == "thirty days"


class TestAnAgentsOwnMonthlyCap:
    """`AgentSpec.budget.monthly_usd` is a cap on *this agent*, not on the org.

    It used to be metered against the organization's month-to-date total, which
    made it a second organization-wide cap wearing an agent's name: an agent with
    a $10 limit was refused because its neighbours had spent $10, and its own
    spend was never isolated. Both caps were then collapsed with `min()` and
    compared to that one number - two ceilings measured against one quantity.

    These need real rows for the same reason the organization's do. The number
    was never the problem; the lookup was, and a unit test handed the spend would
    have passed against the broken code.
    """

    @staticmethod
    async def _published(db, tenant: Tenant, *, spec: AgentSpec, spent: Decimal) -> Agent:
        """A published agent with `spent` already booked against *it*.

        Committed, not only flushed - see `TestTheOrganizationsMonthlyCap._prepare`.
        """
        # For the side effect: publishing needs a resolvable model profile.
        await _keyed_model_profile(db, tenant)
        agent = await _published_agent(db, tenant, spec=spec)
        if spent:
            await _run_row(
                db,
                organization_id=tenant.organization.id,
                agent_id=agent.id,
                cost=spent,
                started_at=datetime.now(UTC),
            )
        await db.commit()
        return agent

    @staticmethod
    async def _neighbour(db, tenant: Tenant, *, spent: Decimal) -> None:
        """Another agent in the same organization, with spend of its own."""
        neighbour = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug=f"neighbour-{uuid.uuid4().hex[:8]}",
        )
        await _run_row(
            db,
            organization_id=tenant.organization.id,
            agent_id=neighbour.id,
            cost=spent,
            started_at=datetime.now(UTC),
        )

    async def test_a_neighbours_spending_does_not_exhaust_this_agents_cap(self, db) -> None:
        """The defect, stated as a run: a $10 agent refused for somebody else's $12.

        Nothing about this agent has changed - it has spent nothing all month -
        so a cap on it cannot be exhausted.
        """
        tenant = await _tenant(db, name="Neighbourly")
        await self._neighbour(db, tenant, spent=Decimal("12"))
        agent = await self._published(
            db,
            tenant,
            spec=AgentSpec(name="Support", budget={"monthly_usd": 10}),
            spent=Decimal("0"),
        )

        prepared = await AgentRunnerService(db).prepare(tenant.ctx, agent.id)

        assert await _answer(prepared) == "thirty days"

    async def test_an_agent_is_refused_once_its_own_spend_reaches_its_cap(self, db) -> None:
        """The cap still has to bind - on the spend that is actually the agent's.

        The neighbour is what makes the reported figure worth asserting: metered
        organization-wide the refusal would read $15.50 against a $10 agent limit,
        and an operator would go looking for $5 this agent never spent.
        """
        tenant = await _tenant(db, name="Overspent")
        await self._neighbour(db, tenant, spent=Decimal("5"))
        agent = await self._published(
            db,
            tenant,
            spec=AgentSpec(name="Support", budget={"monthly_usd": 10}),
            spent=Decimal("10.5"),
        )

        prepared = await AgentRunnerService(db).prepare(tenant.ctx, agent.id)

        with pytest.raises(BudgetExceeded) as refused:
            await _answer(prepared)

        assert refused.value.limit_usd == Decimal("10")
        assert refused.value.spent_usd == Decimal("10.5")
        assert refused.value.scope is BudgetScope.AGENT

    async def test_a_tighter_agent_cap_binds_on_its_own_spend(self, db) -> None:
        """$5 under a $50 ceiling, and the $6 that binds it is this agent's own.

        Both caps are in force and the tighter one stops the run - but it stops
        it at $6, not at the $26 the organization has spent. Taking `min()` of
        the two and checking it against the organization's total gave the right
        verdict here for the wrong reason, and the wrong verdict above.
        """
        tenant = await _tenant(db, name="Tighter", monthly_budget_usd=Decimal("50"))
        await self._neighbour(db, tenant, spent=Decimal("20"))
        agent = await self._published(
            db,
            tenant,
            spec=AgentSpec(name="Support", budget={"monthly_usd": 5}),
            spent=Decimal("6"),
        )

        prepared = await AgentRunnerService(db).prepare(tenant.ctx, agent.id)

        with pytest.raises(BudgetExceeded) as refused:
            await _answer(prepared)

        assert refused.value.limit_usd == Decimal("5")
        assert refused.value.spent_usd == Decimal("6")
        assert refused.value.scope is BudgetScope.AGENT

    async def test_a_looser_agent_cap_does_not_lift_the_organizations(self, db) -> None:
        """Two caps, two quantities, and the one that binds names itself.

        The agent asks for $100 and has spent $4 of it, so its own cap is nowhere
        near. The organization's $10 is exhausted by $12 across both agents -
        which is the number that stops the run, and the number an operator has to
        raise. Under one shared lookup this pair was indistinguishable.
        """
        tenant = await _tenant(db, name="Ambitious", monthly_budget_usd=Decimal("10"))
        await self._neighbour(db, tenant, spent=Decimal("8"))
        agent = await self._published(
            db,
            tenant,
            spec=AgentSpec(name="Support", budget={"monthly_usd": 100}),
            spent=Decimal("4"),
        )

        prepared = await AgentRunnerService(db).prepare(tenant.ctx, agent.id)

        with pytest.raises(BudgetExceeded) as refused:
            await _answer(prepared)

        assert refused.value.limit_usd == Decimal("10")
        assert refused.value.spent_usd == Decimal("12")
        assert refused.value.scope is BudgetScope.ORGANIZATION


# -- grants -------------------------------------------------------------------


class TestGrantWidenedAccess:
    """A grant lifts access for one row, and taking it back lowers it again.

    Written by :class:`SharingService` and read by the registry through
    `resolve_access` - two services that only agree if the row in between says
    what both of them think it says.
    """

    async def test_a_viewer_reaches_a_private_agent_only_while_the_grant_stands(self, db) -> None:
        tenant = await _tenant(db, name="Sharer")
        viewer = await _join(db, tenant, OrgRoleName.VIEWER)
        agent = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="support",
        )
        registry = AgentRegistryService(db)
        sharing = SharingService(db)

        with pytest.raises(NotFoundError):
            await registry.get(viewer, agent.id)

        await sharing.share(
            tenant.ctx,
            agent,
            resource_type=AGENT,
            subject_user_id=viewer.user_id,
            level=GrantLevel.READ,
        )
        assert (await registry.get(viewer, agent.id)).id == agent.id

        await sharing.revoke(tenant.ctx, agent, resource_type=AGENT, subject_user_id=viewer.user_id)
        with pytest.raises(NotFoundError):
            await registry.get(viewer, agent.id)

    async def test_a_shared_agent_appears_in_the_viewers_listing(self, db) -> None:
        """A row you can open but cannot find is not shared in any useful sense."""
        tenant = await _tenant(db, name="Lister")
        viewer = await _join(db, tenant, OrgRoleName.VIEWER)
        agent = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="support",
        )
        registry = AgentRegistryService(db)

        items, total = await registry.list_agents(viewer)
        assert (items, total) == ([], 0)

        await SharingService(db).share(
            tenant.ctx,
            agent,
            resource_type=AGENT,
            subject_user_id=viewer.user_id,
            level=GrantLevel.READ,
        )

        items, total = await registry.list_agents(viewer)
        assert [row.id for row in items] == [agent.id]
        assert total == 1

    async def test_a_read_grant_does_not_let_a_viewer_edit(self, db) -> None:
        """Levels are ordered for a reason: seeing a thing is not changing it."""
        tenant = await _tenant(db, name="Reader")
        viewer = await _join(db, tenant, OrgRoleName.VIEWER)
        agent = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="support",
        )
        await SharingService(db).share(
            tenant.ctx,
            agent,
            resource_type=AGENT,
            subject_user_id=viewer.user_id,
            level=GrantLevel.READ,
        )

        with pytest.raises(NotFoundError):
            await AgentRegistryService(db).get(viewer, agent.id, perm=Perm.AGENTS_EDIT)

    async def test_an_edit_grant_lets_a_viewer_edit_that_one_agent(self, db) -> None:
        """The case the API is shaped around.

        A viewer's role gives no edit anywhere, so a role-level check on the
        write routes would refuse this call before the grant was ever read.
        The routes therefore hand the decision to the registry, and this is
        what the registry is expected to answer: yes on the shared agent, and
        still no on the one next to it.
        """
        tenant = await _tenant(db, name="Editor")
        viewer = await _join(db, tenant, OrgRoleName.VIEWER)
        shared = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="support",
        )
        untouched = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="billing",
        )
        registry = AgentRegistryService(db)
        await SharingService(db).share(
            tenant.ctx,
            shared,
            resource_type=AGENT,
            subject_user_id=viewer.user_id,
            level=GrantLevel.EDIT,
        )

        edited = await registry.save_draft(viewer, shared.id, AgentSpec(name="Support v2"))
        assert edited.draft_spec["name"] == "Support v2"

        with pytest.raises(NotFoundError):
            await registry.save_draft(viewer, untouched.id, AgentSpec(name="Billing v2"))

    async def test_sharing_outside_the_organization_is_refused(self, db) -> None:
        """A grant row pointing at an outsider is a hole that opens later."""
        tenant = await _tenant(db, name="Closed")
        outsider = await _new_user(db)
        agent = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="support",
        )

        with pytest.raises(BadRequestError):
            await SharingService(db).share(
                tenant.ctx,
                agent,
                resource_type=AGENT,
                subject_user_id=outsider.id,
                level=GrantLevel.READ,
            )


class TestMentioningAnAgentFromAChannel:
    """`@slug` in Slack, resolved against real rows.

    The unit suite proves the parsing and the refusals with the database
    stubbed. What it cannot prove is that the slug lookup, the membership lookup
    and the *binding* lookup agree with the tables they read - which is the whole
    of what this path does before it spends a token.

    Every test that expects an answer has to bind the agent to the bot. That is
    the change these tests exist to hold: a handle used to resolve against every
    published agent in the organization, so one Slack app reached all of them.
    """

    @staticmethod
    def _router(db) -> tuple[ChannelAgentRouter, AsyncMock]:
        router = ChannelAgentRouter(db)
        # A run row, not `None`: the answer now carries what the turn cost, and
        # the real `execute` always returns one. A stub that did not would be
        # testing a state this platform cannot reach.
        run = MagicMock(
            id=uuid.uuid4(),
            conversation_id=None,
            input_tokens=120,
            output_tokens=40,
            cost_usd=Decimal("0.0012"),
        )
        execute = AsyncMock(return_value=("answered", run))
        router.runner.execute = execute
        return router, execute

    async def test_a_bound_handle_reaches_the_agent_that_holds_it(self, db) -> None:
        tenant = await _tenant(db, name="Mentions")
        agent = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="support",
        )
        bot = await _bot_row(db, organization_id=tenant.organization.id)
        await _exposure_row(db, agent=agent, bot=bot)
        router, execute = self._router(db)

        answer = await router.answer(
            "@support what is the refund window",
            platform="slack",
            organization_id=tenant.organization.id,
            bot_id=bot.id,
            user_id=tenant.user.id,
        )

        assert answer.text == "answered"
        assert execute.call_args.args[1] == agent.id
        assert execute.call_args.args[2] == "what is the refund window"

    async def test_an_agent_nobody_bound_to_this_bot_answers_nothing(self, db) -> None:
        """The hole this closed: a published agent used to be reachable from any bot.

        No backfill was written, so the agent below is exactly what every agent
        in an upgraded deployment looks like - reachable by handle, bound to
        nothing, and now refused.
        """
        tenant = await _tenant(db, name="Unbound")
        await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="support",
        )
        bot = await _bot_row(db, organization_id=tenant.organization.id)
        router, execute = self._router(db)

        with pytest.raises(BadRequestError) as refused:
            await router.answer(
                "@support hello",
                platform="slack",
                organization_id=tenant.organization.id,
                bot_id=bot.id,
                user_id=tenant.user.id,
            )

        assert "Where this agent is available" in refused.value.message
        execute.assert_not_called()

    async def test_a_binding_on_one_bot_does_not_carry_to_another(self, db) -> None:
        """Two bots in one workspace are two doors, and each is opened separately.

        Without this the binding would only be per-organization wearing a
        per-bot name, and adding a second Slack app would silently reopen every
        agent the first one could reach.
        """
        tenant = await _tenant(db, name="TwoBots")
        agent = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="support",
        )
        bound = await _bot_row(db, organization_id=tenant.organization.id)
        other = await _bot_row(db, organization_id=tenant.organization.id)
        await _exposure_row(db, agent=agent, bot=bound)
        router, execute = self._router(db)

        with pytest.raises(BadRequestError):
            await router.answer(
                "@support hello",
                platform="slack",
                organization_id=tenant.organization.id,
                bot_id=other.id,
                user_id=tenant.user.id,
            )
        execute.assert_not_called()

    async def test_a_paused_binding_stops_the_agent_answering(self, db) -> None:
        """Pausing is how a binding is switched off without losing who made it."""
        tenant = await _tenant(db, name="Paused")
        agent = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="support",
        )
        bot = await _bot_row(db, organization_id=tenant.organization.id)
        await _exposure_row(db, agent=agent, bot=bot, is_active=False)
        router, execute = self._router(db)

        with pytest.raises(BadRequestError):
            await router.answer(
                "@support hello",
                platform="slack",
                organization_id=tenant.organization.id,
                bot_id=bot.id,
                user_id=tenant.user.id,
            )
        execute.assert_not_called()

    async def test_a_handle_from_another_workspace_does_not_resolve(self, db) -> None:
        """Two organizations may both publish `@support`; a bot reaches only its own.

        The other workspace's agent is bound to the other workspace's bot, so
        this is the tenant boundary rather than an unbound agent: even a fully
        exposed agent is invisible from outside its organization.
        """
        mine = await _tenant(db, name="Mine")
        theirs = await _tenant(db, name="Theirs")
        theirs_agent = await _agent_row(
            db,
            organization_id=theirs.organization.id,
            owner_user_id=theirs.user.id,
            slug="support",
        )
        theirs_bot = await _bot_row(db, organization_id=theirs.organization.id)
        await _exposure_row(db, agent=theirs_agent, bot=theirs_bot)
        my_bot = await _bot_row(db, organization_id=mine.organization.id)
        router, execute = self._router(db)

        with pytest.raises(NotFoundError):
            await router.answer(
                "@support hello",
                platform="slack",
                organization_id=mine.organization.id,
                bot_id=my_bot.id,
                user_id=mine.user.id,
            )
        execute.assert_not_called()

    async def test_a_sender_who_is_not_a_member_here_is_refused(self, db) -> None:
        """A real account, a real bound agent - and no standing in this workspace."""
        tenant = await _tenant(db, name="Closed")
        outsider = await _new_user(db)
        agent = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="support",
        )
        bot = await _bot_row(db, organization_id=tenant.organization.id)
        await _exposure_row(db, agent=agent, bot=bot)
        router, execute = self._router(db)

        with pytest.raises(AuthorizationError):
            await router.answer(
                "@support hello",
                platform="slack",
                organization_id=tenant.organization.id,
                bot_id=bot.id,
                user_id=outsider.id,
            )
        execute.assert_not_called()

    async def test_an_ordinary_message_is_left_to_the_bots_own_assistant(self, db) -> None:
        tenant = await _tenant(db, name="Chatty")
        bot = await _bot_row(db, organization_id=tenant.organization.id)
        router, execute = self._router(db)

        with pytest.raises(UnaddressedMessage):
            await router.answer(
                "how do refunds work?",
                platform="slack",
                organization_id=tenant.organization.id,
                bot_id=bot.id,
                user_id=tenant.user.id,
            )
        execute.assert_not_called()


class TestChattingWithAPublishedAgent:
    """The web chat, against real rows.

    The unit suite proves the accounting with the database stubbed. What only a
    real database can answer is whether the chat reaches the same rows every
    other surface does - whether the run it opens is the one `/runs` lists, and
    whether a socket that authenticated a person is still bound by that person's
    role once they name an agent.
    """

    @staticmethod
    async def _publish(db, tenant: Tenant, *, name: str = "Support") -> Agent:
        """An agent with a live version and a model it can actually resolve."""
        sealed = seal_secret(
            ApiKeySecret(api_key="sk-test-key"),
            scope=VaultScope.organization(tenant.organization.id),
        )
        secret = OrganizationSecret(
            id=uuid.uuid4(),
            organization_id=tenant.organization.id,
            name="Key",
            purpose="openai",
            visibility="org",
            kind=SecretKind.API_KEY.value,
            sealed_secret=sealed.ciphertext,
            hint=sealed.hint,
        )
        db.add(secret)
        await db.flush()
        profile = ModelProfile(
            id=uuid.uuid4(),
            organization_id=tenant.organization.id,
            label="Default",
            provider="openai",
            model="gpt-4.1",
            secret_id=secret.id,
        )
        db.add(profile)
        await db.flush()

        registry = AgentRegistryService(db)
        agent = await registry.create(tenant.ctx, AgentSpec(name=name, model_profile_id=profile.id))
        await registry.publish(tenant.ctx, agent.id)
        return agent

    @staticmethod
    async def _chat(db, user: User, organization_id: uuid.UUID, agent_id: uuid.UUID):
        """One chat turn whose surface never advances the run.

        Not iterating means no model request leaves the process, which is the
        point: everything up to the first token is real - the membership, the
        published version, the model profile, the run row - and the run then
        ends the way a surface that died mid-stream would end it.
        """
        return await ChatAgentRunner(db).run(
            user=user,
            organization_id=organization_id,
            agent_id=agent_id,
            user_input="what is the refund window",
            message_history=[],
            conversation_id=None,
            ask_user=AsyncMock(return_value=[]),
            stream=AsyncMock(return_value=None),
        )

    @staticmethod
    async def _runs(db) -> list[AgentRun]:
        return list((await db.execute(select(AgentRun))).scalars())

    async def test_a_chat_turn_lands_in_run_history_as_a_web_run(self, db) -> None:
        """A chat run missing from `/runs` is a run nobody is accountable for.

        It records the version it executed and the person it belonged to, and it
        is there even though this turn ended badly - the tokens up to the point
        it broke were still spent.
        """
        tenant = await _tenant(db, name="Chatters")
        agent = await self._publish(db, tenant)

        with pytest.raises(RuntimeError):
            await self._chat(db, tenant.user, tenant.organization.id, agent.id)

        run = (await self._runs(db))[0]
        assert run.surface == RunSurface.WEB.value
        assert run.agent_id == agent.id
        assert run.agent_version_id == agent.current_version_id
        assert run.user_id == tenant.user.id
        assert run.organization_id == tenant.organization.id
        assert run.status == RunStatus.FAILED.value
        assert run.ended_at is not None

    async def test_an_unpublished_agent_is_refused_instead_of_answered(self, db) -> None:
        """Falling back to the general assistant would answer as something else."""
        tenant = await _tenant(db, name="Drafters")
        agent = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="draft",
        )

        with pytest.raises(BadRequestError):
            await self._chat(db, tenant.user, tenant.organization.id, agent.id)

        assert await self._runs(db) == []

    async def test_an_agent_in_another_organization_is_not_reachable(self, db) -> None:
        """The socket's active organization is where the id is resolved, and only there."""
        mine = await _tenant(db, name="Mine")
        theirs = await _tenant(db, name="Theirs")
        agent = await self._publish(db, theirs)

        with pytest.raises(NotFoundError):
            await self._chat(db, mine.user, mine.organization.id, agent.id)

        assert await self._runs(db) == []

    async def test_a_viewer_cannot_run_an_agent_that_was_never_shared_with_them(self, db) -> None:
        """The run carries the chatter's role, so the chat cannot widen it."""
        tenant = await _tenant(db, name="Restricted")
        agent = await self._publish(db, tenant)
        viewer = await _join(db, tenant, OrgRoleName.VIEWER)
        viewer_user = await db.get(User, viewer.user_id)

        with pytest.raises(NotFoundError):
            await self._chat(db, viewer_user, tenant.organization.id, agent.id)

        assert await self._runs(db) == []

    async def test_someone_who_left_the_organization_cannot_run_anything_in_it(self, db) -> None:
        """A long-lived socket must not outlive the membership behind it."""
        tenant = await _tenant(db, name="Closed")
        agent = await self._publish(db, tenant)
        outsider = await _new_user(db)

        with pytest.raises(AuthorizationError):
            await self._chat(db, outsider, tenant.organization.id, agent.id)

        assert await self._runs(db) == []


class TestManyKeysForOneProvider:
    """Five OpenAI keys, five agents, one key each.

    The shape a real deployment arrives in: separate keys per team, per client
    or per cost centre, all with the same provider, and each agent billed to
    its own. Vault names are unique per organization rather than per provider
    precisely so this is possible - the name is what forces the five to be
    told apart in a dropdown.

    Worth an integration test rather than a unit one because the guarantee is
    the *chain*: vault secret → profile → spec → the key the run actually
    unseals. Every link is a different service, and a stub agrees with whatever
    it is told.
    """

    @staticmethod
    async def _five(db, tenant) -> list[tuple[str, uuid.UUID]]:
        """Five keys for one provider, each behind its own named profile."""
        vault = OrganizationSecretService(db)
        profiles = ModelProfileService(db)
        made = []
        for index in range(5):
            secret = f"sk-openai-team-{index}"
            stored = await vault.create(
                tenant.ctx,
                name=f"OpenAI team {index}",
                value=ApiKeySecret(api_key=secret),
                purpose="openai",
            )
            profile = await profiles.create_profile(
                tenant.ctx,
                label=f"GPT for team {index}",
                provider="openai",
                model="gpt-4.1",
                secret_id=stored.id,
            )
            made.append((secret, profile.id))
        return made

    async def test_one_provider_holds_as_many_keys_as_the_org_needs(self, db) -> None:
        tenant = await _tenant(db, name="ManyKeys")

        await self._five(db, tenant)
        secrets = await OrganizationSecretService(db).list_secrets(tenant.ctx)

        assert len([row for row in secrets if row.purpose == "openai"]) == 5

    async def test_each_agent_resolves_the_key_its_own_profile_points_at(self, db) -> None:
        """The point of the whole chain: no agent reaches another's key."""
        tenant = await _tenant(db, name="Routed")
        made = await self._five(db, tenant)
        service = ModelProfileService(db)

        for expected_secret, profile_id in made:
            resolved = await service.resolve(tenant.ctx, profile_id=profile_id)
            assert resolved.credential.secret.api_key.get_secret_value() == expected_secret

    async def test_a_published_agent_carries_its_profile_into_the_run(self, db) -> None:
        made = await self._five(db, (tenant := await _tenant(db, name="Bound")))
        registry = AgentRegistryService(db)
        service = ModelProfileService(db)

        for index, (expected_secret, profile_id) in enumerate(made):
            agent = await registry.create(
                tenant.ctx, AgentSpec(name=f"Team {index}", model_profile_id=profile_id)
            )
            await registry.publish(tenant.ctx, agent.id, note="bound")
            _, spec, _ = await registry.get_runnable_spec(tenant.ctx, agent.id)

            assert spec.model_profile_id == profile_id
            resolved = await service.resolve(tenant.ctx, profile_id=spec.model_profile_id)
            assert resolved.credential.secret.api_key.get_secret_value() == expected_secret

    async def test_two_keys_cannot_share_a_name(self, db) -> None:
        """Five rows all called "OpenAI" would be five keys nobody can tell apart.

        This used to assert `IntegrityError`, which was the truth and the bug:
        the constraint was doing the refusing, so a person who reused a name
        was answered with a 500. The refusal now comes from the service, before
        the write, with something the reader can act on.
        """
        tenant = await _tenant(db, name="Named")
        vault = OrganizationSecretService(db)
        await vault.create(
            tenant.ctx,
            name="OpenAI",
            value=ApiKeySecret(api_key="sk-first"),
            purpose="openai",
        )

        with pytest.raises(AlreadyExistsError) as refused:
            await vault.create(
                tenant.ctx,
                name="OpenAI",
                value=ApiKeySecret(api_key="sk-second"),
                purpose="openai",
            )
        assert refused.value.status_code == 409

        # The session is still usable, which is the other half of refusing
        # before the flush: an IntegrityError leaves the transaction in a state
        # where every later statement fails too.
        assert len(await vault.list_secrets(tenant.ctx)) == 1

    async def test_deleting_one_key_leaves_the_other_agents_running(self, db) -> None:
        """Retiring one team's key must not take the other four down with it."""
        tenant = await _tenant(db, name="Retired")
        made = await self._five(db, tenant)
        service = ModelProfileService(db)
        profile = await credential_repo.get_profile(
            db, made[0][1], organization_id=tenant.organization.id
        )
        assert profile is not None and profile.secret_id is not None

        await OrganizationSecretService(db).delete(tenant.ctx, profile.secret_id)

        with pytest.raises(BadRequestError):
            await service.resolve(tenant.ctx, profile_id=made[0][1])
        for expected_secret, profile_id in made[1:]:
            resolved = await service.resolve(tenant.ctx, profile_id=profile_id)
            assert resolved.credential.secret.api_key.get_secret_value() == expected_secret


class TestTheOrganizationsSecrets:
    """The general secret store, against real rows.

    Worth an integration test rather than a unit one because the guarantee is
    the *pair*: the query is scoped to one organization, and the envelope is
    bound to it as well. Either alone would be a boundary with one lock, and a
    mock agrees with whichever one it was told about.
    """

    @staticmethod
    async def _store(db, tenant: Tenant, *, name: str, key: str) -> uuid.UUID:
        secret = await OrganizationSecretService(db).create(
            tenant.ctx, name=name, value=ApiKeySecret(api_key=key)
        )
        return secret.id

    async def test_a_stored_secret_keeps_only_a_hint_in_the_clear(self, db) -> None:
        tenant = await _tenant(db, name="Secretive")

        secret_id = await self._store(db, tenant, name="Weather API", key="wx-live-abcd4242")

        [row] = await OrganizationSecretService(db).list_secrets(tenant.ctx)
        assert row.id == secret_id
        assert row.hint == "4242"
        # The listing is what a client sees. Serialised whole rather than
        # field-by-field, so a field added later cannot smuggle the value out
        # without this failing.
        assert "wx-live-abcd4242" not in row.model_dump_json()

        stored = await organization_secret_repo.get(
            db, secret_id, organization_id=tenant.organization.id
        )
        assert stored is not None
        assert "wx-live-abcd4242" not in stored.sealed_secret

    async def test_a_secret_from_another_organization_is_unreachable(self, db) -> None:
        """Both locks, in one test.

        The query is scoped, so the row is not found; and even handed the
        ciphertext directly, the other tenant's envelope does not open it.
        """
        theirs = await _tenant(db, name="Theirs")
        mine = await _tenant(db, name="Mine")
        secret_id = await self._store(db, theirs, name="Weather API", key="wx-live-abcd4242")
        row = await organization_secret_repo.get(
            db, secret_id, organization_id=theirs.organization.id
        )
        assert row is not None

        assert (
            await organization_secret_repo.get(db, secret_id, organization_id=mine.organization.id)
            is None
        )
        assert await OrganizationSecretService(db).resolve_for_bindings(mine.ctx, [secret_id]) == {}
        with pytest.raises(BadRequestError, match="Failed to decrypt"):
            unseal(
                row.sealed_secret,
                scope=VaultScope.organization(mine.organization.id),
                key_version=row.key_version,
            )

    async def test_two_organizations_may_use_the_same_name(self, db) -> None:
        """Uniqueness is per organization; a shared vocabulary is not a collision."""
        theirs = await _tenant(db, name="TheirNames")
        mine = await _tenant(db, name="MyNames")

        await self._store(db, theirs, name="Weather API", key="wx-theirs-1111")
        await self._store(db, mine, name="Weather API", key="wx-mine-2222")

        assert len(await OrganizationSecretService(db).list_secrets(mine.ctx)) == 1

    async def test_a_name_cannot_be_used_twice_in_one_organization(self, db) -> None:
        """The name plus four characters is all anyone can see of a secret."""
        tenant = await _tenant(db, name="Duplicates")
        await self._store(db, tenant, name="Weather API", key="wx-first-1111")

        with pytest.raises(AlreadyExistsError):
            await self._store(db, tenant, name="Weather API", key="wx-second-2222")

    async def test_a_rotation_replaces_the_value_behind_a_stable_id(self, db) -> None:
        """The whole point of referencing by id: agents keep working across a rotation."""
        tenant = await _tenant(db, name="Rotators")
        service = OrganizationSecretService(db)
        secret_id = await self._store(db, tenant, name="Weather API", key="wx-old-1111")

        await service.update(tenant.ctx, secret_id, value=ApiKeySecret(api_key="wx-new-2222"))

        resolved = await service.resolve_for_bindings(tenant.ctx, [secret_id])
        assert resolved[secret_id].api_key.get_secret_value() == "wx-new-2222"

    async def test_several_secrets_resolve_in_one_query(self, db) -> None:
        """A run reads every secret its bindings name; one query, not one each."""
        tenant = await _tenant(db, name="Batched")
        first = await self._store(db, tenant, name="Weather", key="wx-1111")
        second = await self._store(db, tenant, name="Maps", key="mp-2222")

        resolved = await OrganizationSecretService(db).resolve_for_bindings(
            tenant.ctx, [first, second]
        )

        assert {secret.api_key.get_secret_value() for secret in resolved.values()} == {
            "wx-1111",
            "mp-2222",
        }

    async def test_deleting_the_organization_takes_its_secrets_with_it(self, db) -> None:
        tenant = await _tenant(db, name="Departing")
        await self._store(db, tenant, name="Weather API", key="wx-live-1111")

        await db.delete(tenant.organization)
        await db.flush()

        assert (
            await organization_secret_repo.list_secrets(db, organization_id=tenant.organization.id)
            == []
        )

    async def test_a_deleted_secret_is_gone_and_a_second_delete_says_so(self, db) -> None:
        tenant = await _tenant(db, name="Deleters")
        service = OrganizationSecretService(db)
        secret_id = await self._store(db, tenant, name="Weather API", key="wx-live-1111")

        await service.delete(tenant.ctx, secret_id)

        assert await service.list_secrets(tenant.ctx) == []
        assert (
            await organization_secret_repo.delete(
                db, secret_id, organization_id=tenant.organization.id
            )
            is False
        )

    async def test_a_secret_is_found_by_name_inside_its_own_organization_only(self, db) -> None:
        theirs = await _tenant(db, name="NamedTheirs")
        mine = await _tenant(db, name="NamedMine")
        await self._store(db, theirs, name="Weather API", key="wx-live-1111")

        assert (
            await organization_secret_repo.get_by_name(
                db, "Weather API", organization_id=theirs.organization.id
            )
            is not None
        )
        assert (
            await organization_secret_repo.get_by_name(
                db, "Weather API", organization_id=mine.organization.id
            )
            is None
        )


class TestFilteringConversationsByAgent:
    """The admin filter, against a real database.

    Worth an integration test rather than a unit one for a reason this actually
    hit: the filter is a correlated `EXISTS`, and its failure mode is a query
    SQLAlchemy refuses to compile. A mocked session accepts any expression and
    reports nothing; only a database says "no FROM clauses due to
    auto-correlation" - which is what the route returned as a 500.
    """

    async def _conversation(self, db, tenant: Tenant, *, title: str) -> Conversation:
        conversation = Conversation(
            id=uuid.uuid4(),
            organization_id=tenant.organization.id,
            user_id=tenant.user.id,
            title=title,
        )
        db.add(conversation)
        await db.flush()
        return conversation

    async def _answer(self, db, conversation: Conversation, agent_id: uuid.UUID | None) -> None:
        db.add(
            Message(
                id=uuid.uuid4(),
                conversation_id=conversation.id,
                role="assistant",
                content="…",
                agent_id=agent_id,
            )
        )
        await db.flush()

    async def test_only_threads_that_agent_answered_in_come_back(self, db) -> None:
        tenant = await _tenant(db, name="Filtering")
        agent = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="support",
        )
        other = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="sales",
        )

        answered = await self._conversation(db, tenant, title="Handled by support")
        await self._answer(db, answered, agent.id)
        elsewhere = await self._conversation(db, tenant, title="Handled by sales")
        await self._answer(db, elsewhere, other.id)

        rows, total = await conversation_repo.admin_list_with_users(db, agent_id=agent.id)

        assert total == 1
        assert [row[0].id for row in rows] == [answered.id]

    async def test_a_thread_two_agents_answered_in_matches_both(self, db) -> None:
        """The picker can be changed mid-thread, which is why this is an EXISTS
        on messages and not a column on the conversation."""
        tenant = await _tenant(db, name="Handover")
        first = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="triage",
        )
        second = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="escalation",
        )

        conversation = await self._conversation(db, tenant, title="Escalated")
        await self._answer(db, conversation, first.id)
        await self._answer(db, conversation, second.id)

        for agent in (first, second):
            rows, total = await conversation_repo.admin_list_with_users(db, agent_id=agent.id)
            assert total == 1
            assert [row[0].id for row in rows] == [conversation.id]

    async def test_the_message_count_is_not_multiplied_by_the_filter(self, db) -> None:
        """A join instead of an EXISTS would count each message once per match
        and inflate every row on the page."""
        tenant = await _tenant(db, name="Counting")
        agent = await _agent_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=tenant.user.id,
            slug="chatty",
        )
        conversation = await self._conversation(db, tenant, title="Three turns")
        for _ in range(3):
            await self._answer(db, conversation, agent.id)

        rows, _total = await conversation_repo.admin_list_with_users(db, agent_id=agent.id)

        assert rows[0][1] == 3


class TestWhichSecretsAMemberSees:
    """The visibility predicate, against real rows.

    A mock session accepts any expression and reports nothing, so the only way
    to know that "mine, the organization's, or shared with me" is actually what
    the SQL says is to ask a database. It is also a security boundary: getting
    it wrong shows one member another member's private key.
    """

    @staticmethod
    async def _store(
        db,
        tenant: Tenant,
        *,
        name: str,
        purpose: str = "openai",
        visibility: Visibility = Visibility.ORG,
        ctx=None,
    ):
        return await OrganizationSecretService(db).create(
            ctx or tenant.ctx,
            name=name,
            value=ApiKeySecret(api_key=f"sk-{name}"),
            purpose=purpose,
            visibility=visibility,
        )

    async def test_a_member_sees_the_organizations_keys_and_their_own(self, db) -> None:
        owner = await _tenant(db, name="Shared")
        member_user = await _new_user(db)
        db.add(
            OrganizationMember(
                id=uuid.uuid4(),
                organization_id=owner.organization.id,
                user_id=member_user.id,
                role=OrgRoleName.MEMBER.value,
            )
        )
        await db.flush()
        member_ctx = AuthContext(
            user_id=member_user.id,
            organization_id=owner.organization.id,
            role=OrgRoleName.MEMBER.value,
        )

        await self._store(db, owner, name="Team OpenAI")
        await self._store(db, owner, name="Owner's own", visibility=Visibility.PRIVATE)
        await self._store(
            db, owner, name="Member's own", visibility=Visibility.PRIVATE, ctx=member_ctx
        )

        visible = {row.name for row in await OrganizationSecretService(db).list_secrets(member_ctx)}

        assert visible == {"Team OpenAI", "Member's own"}

    async def test_an_owner_sees_every_key_including_private_ones(self, db) -> None:
        """An owner's role reaches the whole organization, so the predicate is
        skipped entirely - which is the branch a scoped query must not take."""
        owner = await _tenant(db, name="Everything")
        await self._store(db, owner, name="Team key")
        await self._store(db, owner, name="Private key", visibility=Visibility.PRIVATE)

        visible = {row.name for row in await OrganizationSecretService(db).list_secrets(owner.ctx)}

        assert visible == {"Team key", "Private key"}

    async def test_filtering_by_purpose_narrows_to_what_a_slot_can_use(self, db) -> None:
        """What a picker asks for: the Tavily keys for a web-search binding,
        not every API key in the vault."""
        owner = await _tenant(db, name="Purposeful")
        await self._store(db, owner, name="OpenAI prod", purpose="openai")
        await self._store(db, owner, name="Tavily", purpose="tavily")
        await self._store(db, owner, name="Brave", purpose="brave")

        search_keys = await OrganizationSecretService(db).list_secrets(
            owner.ctx, purposes=["tavily", "brave"]
        )

        assert {row.name for row in search_keys} == {"Tavily", "Brave"}
        assert {row.purpose for row in search_keys} == {"tavily", "brave"}

    async def test_a_private_key_from_another_member_is_not_reachable_by_id(self, db) -> None:
        """The listing hides it; asking for it directly must too, and as
        "missing" rather than "forbidden" so ids stay unprobeable."""
        owner = await _tenant(db, name="Direct")
        member_user = await _new_user(db)
        db.add(
            OrganizationMember(
                id=uuid.uuid4(),
                organization_id=owner.organization.id,
                user_id=member_user.id,
                role=OrgRoleName.MEMBER.value,
            )
        )
        await db.flush()
        member_ctx = AuthContext(
            user_id=member_user.id,
            organization_id=owner.organization.id,
            role=OrgRoleName.MEMBER.value,
        )
        theirs = await self._store(db, owner, name="Owner private", visibility=Visibility.PRIVATE)

        with pytest.raises(NotFoundError):
            await OrganizationSecretService(db)._get(member_ctx, theirs.id)


class TestWhichSkillsAMemberSees:
    """The skills visibility predicate, against real rows.

    The same boundary the vault holds for keys: a mock session accepts any
    expression, so only a database can prove the SQL really says "mine, the
    organization's, or shared with me" - and getting it wrong shows one member
    another member's private know-how by name and description.
    """

    @staticmethod
    async def _skill_row(
        db,
        *,
        organization_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        name: str,
        visibility: Visibility = Visibility.PRIVATE,
    ) -> Skill:
        skill = Skill(
            id=uuid.uuid4(),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            name=name,
            description=f"What {name} is for",
            visibility=visibility.value,
        )
        db.add(skill)
        await db.flush()
        return skill

    async def test_a_viewer_does_not_list_another_members_private_skill(self, db) -> None:
        """The leak this predicate closes: before it, GET /skills answered a
        viewer with every skill in the organization, private ones included."""
        tenant = await _tenant(db, name="Shelved")
        viewer = await _join(db, tenant, OrgRoleName.VIEWER)
        org_id = tenant.organization.id

        await self._skill_row(
            db, organization_id=org_id, owner_user_id=tenant.user.id, name="owner-private"
        )
        await self._skill_row(
            db,
            organization_id=org_id,
            owner_user_id=tenant.user.id,
            name="org-wide",
            visibility=Visibility.ORG,
        )
        await self._skill_row(
            db, organization_id=org_id, owner_user_id=viewer.user_id, name="viewers-own"
        )
        shared = await self._skill_row(
            db, organization_id=org_id, owner_user_id=tenant.user.id, name="shared-with-viewer"
        )
        await SharingService(db).share(
            tenant.ctx,
            shared,
            resource_type=SKILL,
            subject_user_id=viewer.user_id,
            level=GrantLevel.READ,
        )

        items, total = await SkillService(db).list_skills(viewer)

        assert {skill.name for skill in items} == {"org-wide", "viewers-own", "shared-with-viewer"}
        # The count carries the same predicate as the page, or the pager offers
        # pages of rows the viewer will never receive.
        assert total == 3

    async def test_an_owner_still_sees_every_skill_including_private_ones(self, db) -> None:
        """An owner's role reaches the whole organization, so the predicate is
        skipped entirely - which is the branch a scoped query must not take."""
        tenant = await _tenant(db, name="Overseen")
        member = await _join(db, tenant, OrgRoleName.MEMBER)

        await self._skill_row(
            db,
            organization_id=tenant.organization.id,
            owner_user_id=member.user_id,
            name="members-private",
        )

        items, total = await SkillService(db).list_skills(tenant.ctx)

        assert {skill.name for skill in items} == {"members-private"}
        assert total == 1


class TestWhoStillHearsAboutRuns:
    """The notification opt-outs, against real rows.

    `/settings/notifications` writes three booleans; the recipient query
    filters on one of them in SQL. A unit test can only assert which column
    was asked for - whether the WHERE clause actually drops the member who
    switched it off is a question for the database.
    """

    @pytest.mark.anyio
    async def test_a_member_who_opted_out_is_dropped_from_the_recipient_query(self, db) -> None:
        tenant = await _tenant(db, name="Optout")
        admin_ctx = await _join(db, tenant, OrgRoleName.ADMIN)
        admin = await db.get(User, admin_ctx.user_id)
        assert admin is not None
        admin.notify_usage_reports = False
        await db.flush()

        recipients = await member_repo.list_emails_by_role(
            db,
            organization_id=tenant.organization.id,
            roles=[OrgRoleName.OWNER.value, OrgRoleName.ADMIN.value],
            preference="notify_usage_reports",
        )

        assert recipients == [tenant.user.email]

    @pytest.mark.anyio
    async def test_an_opt_out_silences_one_kind_of_email_not_the_others(self, db) -> None:
        """The columns are independent: declining the usage report must not
        also silence the budget alert that stops a runaway agent."""
        tenant = await _tenant(db, name="OneKind")
        tenant.user.notify_usage_reports = False
        await db.flush()

        reports = await member_repo.list_emails_by_role(
            db,
            organization_id=tenant.organization.id,
            roles=[OrgRoleName.OWNER.value],
            preference="notify_usage_reports",
        )
        budget = await member_repo.list_emails_by_role(
            db,
            organization_id=tenant.organization.id,
            roles=[OrgRoleName.OWNER.value],
            preference="notify_budget_alerts",
        )

        assert reports == []
        assert budget == [tenant.user.email]

    @pytest.mark.anyio
    async def test_a_query_without_a_preference_still_lists_everyone(self, db) -> None:
        """Callers that are not sending optional mail see the full roster."""
        tenant = await _tenant(db, name="NoPref")
        tenant.user.notify_usage_reports = False
        await db.flush()

        recipients = await member_repo.list_emails_by_role(
            db,
            organization_id=tenant.organization.id,
            roles=[OrgRoleName.OWNER.value],
        )

        assert recipients == [tenant.user.email]


class TestSharedWithMeIsWhatWasDeliberatelyShared:
    """The listings' shared_with_me filter: shared or org-visible, never mine.

    Two properties matter and both are easy to lose. The caller's own rows
    must not appear however visible they are, and a role that already reaches
    the whole organization must still get the grants-and-visibility answer -
    not "everything minus mine".
    """

    async def test_a_member_sees_the_granted_and_the_org_visible_but_not_their_own(
        self, db, estate: TwoTenants
    ) -> None:
        member = await _join(db, estate.home, OrgRoleName.MEMBER)
        await SharingService(db).share(
            estate.home.ctx,
            estate.home_agent,
            resource_type=AGENT,
            subject_user_id=member.user_id,
            level=GrantLevel.READ,
        )
        org_visible = await _agent_row(
            db,
            organization_id=estate.home.organization.id,
            owner_user_id=estate.home.user.id,
            slug="orgwide",
        )
        org_visible.visibility = Visibility.ORG.value
        mine = await _agent_row(
            db,
            organization_id=estate.home.organization.id,
            owner_user_id=member.user_id,
            slug="my-own",
        )
        mine.visibility = Visibility.ORG.value
        await db.flush()

        rows, total = await AgentRegistryService(db).list_agents(member, shared_with_me=True)

        assert {row.id for row in rows} == {estate.home_agent.id, org_visible.id}
        assert total == 2

    async def test_a_wide_role_gets_grants_and_visibility_not_the_whole_org(
        self, db, estate: TwoTenants
    ) -> None:
        """An owner reaches every agent; "shared with me" still means shared."""
        member = await _join(db, estate.home, OrgRoleName.MEMBER)
        private_granted_to_owner = await _agent_row(
            db,
            organization_id=estate.home.organization.id,
            owner_user_id=member.user_id,
            slug="theirs",
        )
        await SharingService(db).share(
            member,
            private_granted_to_owner,
            resource_type=AGENT,
            subject_user_id=estate.home.user.id,
            level=GrantLevel.READ,
        )

        rows, total = await AgentRegistryService(db).list_agents(
            estate.home.ctx, shared_with_me=True
        )

        # estate.home_agent is the owner's own private agent - not shared with
        # them, however wide their role.
        assert {row.id for row in rows} == {private_granted_to_owner.id}
        assert total == 1

    async def test_skills_answer_the_same_question(self, db, estate: TwoTenants) -> None:
        member = await _join(db, estate.home, OrgRoleName.MEMBER)
        await SharingService(db).share(
            estate.home.ctx,
            estate.home_skill,
            resource_type=SKILL,
            subject_user_id=member.user_id,
            level=GrantLevel.READ,
        )

        items, total = await SkillService(db).list_skills(member, shared_with_me=True)

        assert [skill.id for skill in items] == [estate.home_skill.id]
        assert total == 1

    async def test_collections_exclude_personal_and_app_rows(self, db) -> None:
        """A personal base is mine by construction and an app base is the
        deployment's - neither was shared *with* anybody."""
        tenant = await _tenant(db, name="KbShare")
        member = await _join(db, tenant, OrgRoleName.MEMBER)
        org_visible = await _kb_row(db, tenant=tenant, collection_name="kb_org_visible")
        await _kb_row(
            db,
            tenant=tenant,
            collection_name="kb_personal",
            scope=KBScope.PERSONAL,
            owner_user_id=member.user_id,
        )
        await _kb_row(db, tenant=tenant, collection_name="kb_app", scope=KBScope.APP)
        my_org_row = await _kb_row(
            db,
            tenant=tenant,
            collection_name="kb_my_org_row",
            owner_user_id=member.user_id,
        )

        bases = await KnowledgeBaseService(db).list_accessible(member, shared_with_me=True)

        assert {kb.id for kb in bases} == {org_visible.id}
        assert my_org_row.id not in {kb.id for kb in bases}


class TestTheListingCarriesThePublishedCap:
    """`budget_monthly_usd` on the agent listing - the headroom card's cap.

    Read off the published version's frozen spec by JSONB path, which only a
    real Postgres can prove: a mock cannot say whether `spec -> 'budget' ->>
    'monthly_usd'` survives the round trip through publish.
    """

    async def _publish(self, db, estate: TwoTenants, spec: dict) -> None:
        version = AgentVersion(
            id=uuid.uuid4(),
            agent_id=estate.home_agent.id,
            organization_id=estate.home.organization.id,
            version=1,
            spec=spec,
        )
        db.add(version)
        await db.flush()
        estate.home_agent.current_version_id = version.id
        estate.home_agent.status = AgentStatus.PUBLISHED.value
        await db.flush()

    async def test_the_cap_comes_off_the_frozen_spec_not_the_draft(
        self, db, estate: TwoTenants
    ) -> None:
        await self._publish(db, estate, {"name": "Support", "budget": {"monthly_usd": 60}})
        # The draft promises a different number; the runner does not enforce
        # promises, so the listing must not report one.
        estate.home_agent.draft_spec = {"name": "Support", "budget": {"monthly_usd": 999}}
        await db.flush()

        rows, _total = await AgentRegistryService(db).list_agents(estate.home.ctx)

        by_id = {row.id: row for row in rows}
        assert by_id[estate.home_agent.id].budget_monthly_usd == 60.0

    async def test_a_version_with_no_budget_block_answers_null(
        self, db, estate: TwoTenants
    ) -> None:
        await self._publish(db, estate, {"name": "Support"})

        rows, _total = await AgentRegistryService(db).list_agents(estate.home.ctx)

        by_id = {row.id: row for row in rows}
        assert by_id[estate.home_agent.id].budget_monthly_usd is None


class TestWhereAChatAccountHasBeenUsed:
    """The profile panel's second half, against a real database.

    Written after the first version 500'd on one. `SELECT DISTINCT` over the
    joined bot row asks Postgres to compare every column of it, and
    `channel_bots.access_policy` and `usage_reporting` are `json` - a type with
    no equality operator. Every unit test passed, because they mock the
    repository; the page answered `could not identify an equality operator for
    type json`. So this one runs the query.
    """

    @staticmethod
    async def _identity(db, *, user: User) -> ChannelIdentity:
        identity = ChannelIdentity(
            id=uuid.uuid4(),
            platform="mattermost",
            platform_user_id=uuid.uuid4().hex,
            platform_username="kacper.wlodarczyk",
            user_id=user.id,
        )
        db.add(identity)
        await db.flush()
        return identity

    @staticmethod
    async def _session(db, *, bot: ChannelBot, identity: ChannelIdentity, chat: str) -> None:
        db.add(
            ChannelSession(
                id=uuid.uuid4(),
                bot_id=bot.id,
                identity_id=identity.id,
                platform_chat_id=chat,
            )
        )
        await db.flush()

    async def test_the_query_runs_at_all(self, db, estate: TwoTenants) -> None:
        """The whole reason this test exists: json columns and DISTINCT."""
        identity = await self._identity(db, user=estate.home.user)
        bot = await _bot_row(db, organization_id=estate.home.organization.id, platform="mattermost")
        await self._session(db, bot=bot, identity=identity, chat="c-1")

        found = await channel_session_repo.bots_by_identity(db, identity_ids=[identity.id])

        assert [row.id for row in found[identity.id]] == [bot.id]

    async def test_one_bot_in_eight_channels_is_one_place(self, db, estate: TwoTenants) -> None:
        """A chat account has a session per chat, and the panel lists places."""
        identity = await self._identity(db, user=estate.home.user)
        bot = await _bot_row(db, organization_id=estate.home.organization.id, platform="mattermost")
        for chat in range(8):
            await self._session(db, bot=bot, identity=identity, chat=f"c-{chat}")

        found = await channel_session_repo.bots_by_identity(db, identity_ids=[identity.id])

        assert len(found[identity.id]) == 1

    async def test_an_account_used_nowhere_is_absent_rather_than_empty(
        self, db, estate: TwoTenants
    ) -> None:
        identity = await self._identity(db, user=estate.home.user)

        found = await channel_session_repo.bots_by_identity(db, identity_ids=[identity.id])

        assert found == {}

    async def test_a_bot_from_another_tenant_is_never_reported_to_this_person(
        self, db, estate: TwoTenants
    ) -> None:
        """A chat account is not scoped to a tenant, so the narrowing happens in
        the service - and this is the case it has to get right: the same person
        owns rows in both organizations."""
        identity = await self._identity(db, user=estate.home.user)
        home_bot = await _bot_row(
            db, organization_id=estate.home.organization.id, platform="mattermost"
        )
        other_bot = await _bot_row(
            db, organization_id=estate.other.organization.id, platform="mattermost"
        )
        await self._session(db, bot=home_bot, identity=identity, chat="c-1")
        await self._session(db, bot=other_bot, identity=identity, chat="c-2")
        # A member of Home only. `estate` puts the same user in both, so the
        # membership that would show the other tenant's bot is removed.
        await db.execute(
            delete(OrganizationMember).where(
                OrganizationMember.organization_id == estate.other.organization.id,
                OrganizationMember.user_id == estate.home.user.id,
            )
        )
        await db.flush()

        places = await ChannelLinkService(db).places(estate.home.user.id, [identity])

        assert [place.bot_id for place in places[identity.id]] == [home_bot.id]

    async def test_a_place_names_the_server_and_what_answers_there(
        self, db, estate: TwoTenants
    ) -> None:
        identity = await self._identity(db, user=estate.home.user)
        bot = await _bot_row(db, organization_id=estate.home.organization.id, platform="mattermost")
        bot.api_base_url = "https://mattermost.acme.com/"
        await _exposure_row(db, agent=estate.home_agent, bot=bot)
        await self._session(db, bot=bot, identity=identity, chat="c-1")

        places = await ChannelLinkService(db).places(estate.home.user.id, [identity])

        (place,) = places[identity.id]
        assert place.host == "mattermost.acme.com"
        assert [agent.slug for agent in place.agents] == [estate.home_agent.slug]


class TestOneAgentPerBot:
    """A bot answers as one agent, and the database is what makes that true.

    A bot user is one identity in the chat - the same avatar and the same name
    whichever agent replied - so serving several behind one bot meant somebody
    in a channel typing a slug to pick between agents they could not see. The
    constraint is `uq_exposure_bot`; the service refuses first so the caller
    gets a sentence rather than an IntegrityError, and this is the half that
    holds when something bypasses the service.
    """

    async def test_a_second_agent_on_one_bot_is_refused_by_the_database(
        self, db, estate: TwoTenants
    ) -> None:
        bot = await _bot_row(db, organization_id=estate.home.organization.id)
        await _exposure_row(db, agent=estate.home_agent, bot=bot)
        second = await _agent_row(
            db,
            organization_id=estate.home.organization.id,
            owner_user_id=estate.home.user.id,
            slug="billing",
        )

        with pytest.raises(IntegrityError):
            await _exposure_row(db, agent=second, bot=bot)
        await db.rollback()

    async def test_one_agent_may_answer_on_as_many_bots_as_it_likes(
        self, db, estate: TwoTenants
    ) -> None:
        """The constraint is on the bot, not on the pair: an agent in Slack,
        Telegram and two Mattermost servers is four rows and no conflict."""
        for platform in ("slack", "telegram", "mattermost", "mattermost"):
            bot = await _bot_row(db, organization_id=estate.home.organization.id, platform=platform)
            await _exposure_row(db, agent=estate.home_agent, bot=bot)

        bound = await agent_exposure_repo.list_for_agent(
            db,
            agent_id=estate.home_agent.id,
            organization_id=estate.home.organization.id,
        )

        assert len(bound) == 4

    async def test_a_paused_binding_still_holds_the_bot(self, db, estate: TwoTenants) -> None:
        """Which is why the picker filters on any binding rather than on who is
        answering: a paused row occupies the constraint just the same."""
        bot = await _bot_row(db, organization_id=estate.home.organization.id)
        await _exposure_row(db, agent=estate.home_agent, bot=bot, is_active=False)

        taken = await agent_exposure_repo.bound_agent_by_bot(db, channel_bot_ids=[bot.id])

        assert taken == {bot.id: estate.home_agent.id}


class TestPublishingIsNotDeploying:
    """Publishing mints a version; putting it somewhere is a separate decision.

    It used to be one action: publish repointed the default environment, so an
    author fixing a prompt changed what the live bot answered with, in the same
    click, with nothing on screen saying so.
    """

    async def test_a_publish_leaves_a_pinned_environment_where_it_is(self, db) -> None:
        tenant = await _tenant(db, name="Careful")
        model = await _default_model(db, tenant)
        registry = AgentRegistryService(db)
        agent = await registry.create(
            tenant.ctx, AgentSpec(name="Support", model_profile_id=model.id)
        )
        first = await registry.publish(tenant.ctx, agent.id)

        second = await registry.publish(tenant.ctx, agent.id)

        environments = await AgentEnvironmentService(db).list_for_agent(tenant.ctx, agent.id)
        production = next(row for row in environments if row.is_default)
        assert production.version_id == first.id
        assert production.version_id != second.id
        # And what a surface naming no environment gets is that environment's
        # version, not the newest publish.
        assert agent.current_version_id == first.id
        assert production.behind_by == 1

    async def test_an_environment_that_follows_latest_moves_with_every_publish(self, db) -> None:
        tenant = await _tenant(db, name="Iterating")
        model = await _default_model(db, tenant)
        registry = AgentRegistryService(db)
        environments = AgentEnvironmentService(db)
        agent = await registry.create(
            tenant.ctx, AgentSpec(name="Support", model_profile_id=model.id)
        )
        await registry.publish(tenant.ctx, agent.id)
        await environments.create(
            tenant.ctx, agent.id, EnvironmentCreate(name="dev", tracks_latest=True)
        )

        second = await registry.publish(tenant.ctx, agent.id)

        listed = await environments.list_for_agent(tenant.ctx, agent.id)
        dev = next(row for row in listed if row.name == "dev")
        assert dev.version_id == second.id
        assert dev.behind_by == 0

    async def test_the_first_publish_has_somewhere_to_land(self, db) -> None:
        """An agent with no environment has nowhere to run at all, so the first
        publish creates the default rather than leaving it unreachable."""
        tenant = await _tenant(db, name="Fresh")
        model = await _default_model(db, tenant)
        registry = AgentRegistryService(db)
        agent = await registry.create(
            tenant.ctx, AgentSpec(name="Support", model_profile_id=model.id)
        )

        version = await registry.publish(tenant.ctx, agent.id)

        listed = await AgentEnvironmentService(db).list_for_agent(tenant.ctx, agent.id)
        assert [(row.name, row.version_id, row.is_default) for row in listed] == [
            ("production", version.id, True)
        ]
        assert agent.current_version_id == version.id

    async def test_switching_an_environment_to_follow_adopts_the_newest_now(self, db) -> None:
        """A mode that claims to follow and does not until something else
        happens is the half-true state this setting exists to remove."""
        tenant = await _tenant(db, name="Switcher")
        model = await _default_model(db, tenant)
        registry = AgentRegistryService(db)
        environments = AgentEnvironmentService(db)
        agent = await registry.create(
            tenant.ctx, AgentSpec(name="Support", model_profile_id=model.id)
        )
        await registry.publish(tenant.ctx, agent.id)
        newest = await registry.publish(tenant.ctx, agent.id)
        listed = await environments.list_for_agent(tenant.ctx, agent.id)
        production = next(row for row in listed if row.is_default)

        await environments.update(
            tenant.ctx, agent.id, production.id, EnvironmentUpdate(tracks_latest=True)
        )

        after = await environments.list_for_agent(tenant.ctx, agent.id)
        assert next(row for row in after if row.is_default).version_id == newest.id
        assert agent.current_version_id == newest.id
