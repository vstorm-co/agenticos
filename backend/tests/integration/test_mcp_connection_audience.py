"""A department's MCP server stays the department's (#2072).

Everyone who manages MCP servers sees and binds an organization connection, unless
it is narrowed to groups or people: then they, and whoever created it, alone do.
The run itself is not refused - an agent bound to it answers whoever may run the
agent - so the Builder says so instead.
"""

import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, OrgMcpServerRef
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.group import Group, GroupMember
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import ResourceGrant, Visibility
from app.db.models.user import User
from app.schemas.mcp_connection import OrgMcpConnectionCreate, OrgMcpConnectionUpdate
from app.schemas.resource_grant import AudienceChoice
from app.services import mcp_connection as mcp_connection_module
from app.services.agent_registry import AgentRegistryService
from app.services.group import GroupService
from app.services.knowledge_reach import KnowledgeReachService
from app.services.mcp_connection import McpConnectionService
from app.services.workflow_execution import context
from app.workflows.contracts.results import Failed
from app.workflows.nodes.mcp_call import _handler as workflow_mcp

pytestmark = pytest.mark.anyio


async def _person(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _member(db: AsyncSession, organization: Organization, role: str) -> AuthContext:
    person = await _person(db)
    db.add(OrganizationMember(organization_id=organization.id, user_id=person.id, role=role))
    await db.flush()
    return AuthContext(user_id=person.id, organization_id=organization.id, role=role)


async def _department(db: AsyncSession, organization: Organization, *people: AuthContext) -> Group:
    group = Group(organization_id=organization.id, name=f"Dept {uuid.uuid4().hex[:6]}")
    db.add(group)
    await db.flush()
    for person in people:
        assert person.user_id is not None
        db.add(GroupMember(group_id=group.id, user_id=person.user_id))
    await db.flush()
    return group


async def _setup(db: AsyncSession) -> tuple[Organization, AuthContext]:
    owner = await _person(db)
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"))
    await db.flush()
    return organization, AuthContext(
        user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER
    )


@pytest.fixture(autouse=True)
def _any_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # The address check resolves the host; these servers are never called.
    async def checked(url: str) -> str:
        return url

    monkeypatch.setattr(mcp_connection_module, "_checked_url", checked)


async def _server(
    db: AsyncSession, ctx: AuthContext, name: str, **audience: list[uuid.UUID]
) -> McpConnection:
    return await McpConnectionService(db).create_for_org(
        ctx, OrgMcpConnectionCreate(name=name, url=f"https://{name}.example/mcp", **audience)
    )


async def _listed(db: AsyncSession, ctx: AuthContext) -> list[str]:
    rows, total = await McpConnectionService(db).list_for_org(ctx)
    assert total == len(rows)
    return [row.name for row in rows]


async def test_a_server_is_the_whole_organization_s_unless_limited(db: AsyncSession) -> None:
    organization, owner = await _setup(db)
    builder = await _member(db, organization, "builder")

    server = await _server(db, owner, "wiki")

    assert server.visibility == Visibility.ORG.value
    assert await _listed(db, builder) == ["wiki"]


async def test_finance_s_server_is_seen_by_finance_its_creator_and_the_owner(
    db: AsyncSession,
) -> None:
    organization, owner = await _setup(db)
    creator = await _member(db, organization, "builder")
    accountant = await _member(db, organization, "builder")
    seller = await _member(db, organization, "builder")
    finance = await _department(db, organization, accountant)
    await _department(db, organization, seller)

    server = await _server(db, creator, "ledger", group_ids=[finance.id])

    assert server.visibility == Visibility.PRIVATE.value
    assert await _listed(db, accountant) == ["ledger"]
    assert await _listed(db, creator) == ["ledger"]
    assert await _listed(db, owner) == ["ledger"]
    assert await _listed(db, seller) == []
    # Not there for the rest, by id either - the same answer as a missing one.
    with pytest.raises(NotFoundError):
        await McpConnectionService(db).update_for_org(
            seller, connection_id=server.id, data=OrgMcpConnectionUpdate(label="mine now")
        )


async def test_a_server_can_be_limited_to_a_person(db: AsyncSession) -> None:
    organization, owner = await _setup(db)
    analyst = await _member(db, organization, "builder")
    other = await _member(db, organization, "builder")
    assert analyst.user_id is not None

    await _server(db, owner, "warehouse", user_ids=[analyst.user_id])

    assert await _listed(db, analyst) == ["warehouse"]
    assert await _listed(db, other) == []


async def test_a_group_or_person_from_elsewhere_is_refused_by_name(db: AsyncSession) -> None:
    _, owner = await _setup(db)
    elsewhere, outsider = await _setup(db)
    foreign = await _department(db, elsewhere)
    assert outsider.user_id is not None

    with pytest.raises(BadRequestError) as by_group:
        await _server(db, owner, "leak", group_ids=[foreign.id])
    with pytest.raises(BadRequestError) as by_person:
        await _server(db, owner, "leak-two", user_ids=[outsider.user_id])

    assert by_group.value.details["fields"][0]["field"] == "group_ids"
    assert by_person.value.details["fields"][0]["field"] == "user_ids"


async def test_naming_yourself_adds_nothing(db: AsyncSession) -> None:
    organization, owner = await _setup(db)
    assert owner.user_id is not None

    server = await _server(db, owner, "notes", user_ids=[owner.user_id])

    grants = await db.scalars(select(ResourceGrant).where(ResourceGrant.resource_id == server.id))
    assert list(grants) == []


async def test_a_server_signed_in_to_for_the_organization_can_be_limited_too(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization, owner = await _setup(db)
    seller = await _member(db, organization, "builder")
    finance = await _department(db, organization)
    service = McpConnectionService(db)

    async def staged(*, create: Callable[..., Awaitable[McpConnection]], **flow: object) -> str:
        await create(
            name=flow["name"],
            url=flow["url"],
            secret_key_version=1,
            is_enabled=True,
            auth_type="oauth",
            oauth_state=uuid.uuid4().hex,
            oauth_pending_payload=None,
        )
        return "https://consent.example/authorize"

    monkeypatch.setattr(service, "_oauth_start", AsyncMock(side_effect=staged))

    await service.oauth_start_for_org(
        owner,
        name="books",
        url="https://books.example/mcp",
        audience=AudienceChoice(group_ids=[finance.id]),
    )
    await service.oauth_start_for_org(owner, name="open", url="https://open.example/mcp")

    assert sorted(await _listed(db, owner)) == ["books", "open"]
    assert await _listed(db, seller) == ["open"]


async def test_publishing_with_a_department_s_server_needs_its_department(
    db: AsyncSession,
) -> None:
    organization, owner = await _setup(db)
    accountant = await _member(db, organization, "builder")
    seller = await _member(db, organization, "builder")
    finance = await _department(db, organization, accountant)
    server = await _server(db, owner, "ledger", group_ids=[finance.id])
    registry = AgentRegistryService(db)
    refs = [OrgMcpServerRef(connection_id=server.id)]

    assert await registry._mcp_problems(accountant, refs) == []
    assert await registry._mcp_problems(seller, refs) == [f"MCP server not found: {server.id}"]


async def test_the_builder_says_an_organization_agent_reads_finance_s_server(
    db: AsyncSession,
) -> None:
    organization, owner = await _setup(db)
    reader = await _member(db, organization, "builder")
    finance = await _department(db, organization)
    ledger = await _server(db, owner, "ledger", group_ids=[finance.id])
    wiki = await _server(db, owner, "wiki")
    agent = await AgentRegistryService(db).create(
        owner,
        AgentSpec(
            name="Everyone's",
            mcp_servers=[
                OrgMcpServerRef(connection_id=ledger.id),
                OrgMcpServerRef(connection_id=wiki.id),
            ],
        ),
        visibility=Visibility.ORG,
    )

    reach = await KnowledgeReachService(db).for_agent(owner, agent.id)
    by_name = {source.name: source for source in reach.sources}
    assert by_name["ledger"].kind == "mcp"
    assert by_name["ledger"].groups == [finance.name]
    assert by_name["ledger"].reaches_fewer_than_agent
    assert not by_name["wiki"].reaches_fewer_than_agent

    # Somebody outside Finance is not told Finance's server exists.
    hidden = await KnowledgeReachService(db).for_agent(reader, agent.id)
    assert [source.name for source in hidden.sources] == ["wiki"]


async def test_a_department_page_names_its_server_and_deleting_it_drops_the_grant(
    db: AsyncSession,
) -> None:
    organization, owner = await _setup(db)
    finance = await _department(db, organization)
    server = await McpConnectionService(db).create_for_org(
        owner,
        OrgMcpConnectionCreate(
            name="ledger",
            url="https://ledger.example/mcp",
            label="Finance ledger",
            group_ids=[finance.id],
        ),
    )

    listed = await GroupService(db).resources(owner, finance.id)
    assert [(item.kind, item.name) for item in listed] == [("mcp_connection", "Finance ledger")]

    await McpConnectionService(db).delete_for_org(owner, connection_id=server.id)

    assert await GroupService(db).resources(owner, finance.id) == []


async def _refused_workflow_call(
    db: AsyncSession, ctx: AuthContext, connection: McpConnection, monkeypatch: pytest.MonkeyPatch
) -> Failed:
    @asynccontextmanager
    async def session() -> AsyncGenerator[AsyncSession]:
        yield db

    headers = AsyncMock(side_effect=AssertionError("Refused MCP calls must not unseal credentials"))
    monkeypatch.setattr(workflow_mcp, "get_worker_db_context", session)
    monkeypatch.setattr(workflow_mcp, "resolve_auth_headers", headers)
    dispatch = context.DispatchContext(
        organization_id=ctx.organization_id,
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=ctx,
        resumed_agent_run_id=None,
        workflow_id=uuid.uuid4(),
    )
    with context.dispatching_as(dispatch):
        result = await workflow_mcp.handle(
            workflow_mcp.McpCallConfig(connection_id=connection.id, tool="find", approval="none"),
            None,
        )
    assert isinstance(result, Failed)
    headers.assert_not_awaited()
    return result


@pytest.mark.security
@pytest.mark.parametrize("audience", ["person", "group"])
async def test_workflow_mcp_cannot_borrow_another_teams_private_connection(
    db, monkeypatch, audience
):
    org, _owner = await _setup(db)
    creator = await _member(db, org, "builder")
    intended = await _member(db, org, "builder")
    intruder = await _member(db, org, "builder")
    group = await _department(db, org, intended)
    server = await _server(
        db,
        creator,
        "private-workflow",
        **(
            {"user_ids": [intended.subject_id]}
            if audience == "person"
            else {"group_ids": [group.id]}
        ),
    )
    config = workflow_mcp.McpCallConfig(connection_id=server.id, tool="find", approval="none")
    assert await workflow_mcp.check_resources(db, intended, config) == []
    assert [field for field, _ in await workflow_mcp.check_resources(db, intruder, config)] == [
        "connection_id"
    ]
    refused = await _refused_workflow_call(db, intruder, server, monkeypatch)
    assert refused.error.code == "MCP_SERVER_UNAVAILABLE"


@pytest.mark.security
async def test_workflow_mcp_rechecks_group_access_after_publish(db, monkeypatch):
    org, _owner = await _setup(db)
    creator = await _member(db, org, "builder")
    user = await _member(db, org, "builder")
    group = await _department(db, org, user)
    server = await _server(db, creator, "withdrawn-workflow", group_ids=[group.id])
    config = workflow_mcp.McpCallConfig(connection_id=server.id, tool="find")
    assert await workflow_mcp.check_resources(db, user, config) == []
    await db.execute(
        delete(GroupMember).where(
            GroupMember.group_id == group.id, GroupMember.user_id == user.subject_id
        )
    )
    await db.flush()
    assert (
        await _refused_workflow_call(db, user, server, monkeypatch)
    ).error.code == "MCP_SERVER_UNAVAILABLE"


@pytest.mark.security
async def test_workflow_mcp_rechecks_the_effective_connection_allowlist_after_publish(
    db, monkeypatch
):
    org, owner = await _setup(db)
    user = await _member(db, org, "builder")
    server = await _server(db, owner, "limited-workflow")
    server.allowed_tools = ["find"]
    await db.flush()
    config = workflow_mcp.McpCallConfig(connection_id=server.id, tool="find")
    assert await workflow_mcp.check_resources(db, user, config) == []
    server.allowed_tools = []
    await db.flush()
    assert [field for field, _ in await workflow_mcp.check_resources(db, user, config)] == ["tool"]
    assert (
        await _refused_workflow_call(db, user, server, monkeypatch)
    ).error.code == "MCP_TOOL_NOT_ALLOWED"
