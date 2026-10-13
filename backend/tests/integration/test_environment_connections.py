"""Guarantees about environment connection overrides and intercepted calls that only
a database can make.

An override's test side is `SET NULL` on delete, and the runner reads null as
"off": a deleted sandbox must leave the row in place rather than cascade it away,
or staging would silently fall back to production. The kind and the test column
agree by `CHECK`, both tables are scoped by tenant, and an intercepted call's
order survives a run being finished twice.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment, AgentEnvironmentConnection
from app.db.models.agent_run import AgentRun
from app.db.models.intercepted_tool_call import InterceptedToolCall
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.user import User
from app.repositories import agent_environment_repo, intercepted_tool_call_repo

pytestmark = pytest.mark.anyio


async def _org(db) -> Organization:
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
    return org


async def _environment(db, org: Organization) -> AgentEnvironment:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
        name="Support",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        id=uuid.uuid4(), organization_id=org.id, agent_id=agent.id, version=1, spec={}
    )
    db.add(version)
    await db.flush()
    environment = AgentEnvironment(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        name="staging",
        version_id=version.id,
    )
    db.add(environment)
    await db.flush()
    return environment


async def _connection(db, org: Organization) -> McpConnection:
    connection = McpConnection(
        id=uuid.uuid4(),
        scope="org",
        organization_id=org.id,
        name=f"crm-{uuid.uuid4().hex[:8]}",
        url="https://mcp.example.com/mcp",
        secret_key_version=1,
    )
    db.add(connection)
    await db.flush()
    return connection


async def _secret(db, org: Organization) -> OrganizationSecret:
    secret = OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=f"key-{uuid.uuid4().hex[:6]}",
        kind="api_key",
        sealed_secret="{}",
        hint="1234",
    )
    db.add(secret)
    await db.flush()
    return secret


class TestOverrides:
    async def test_replacing_writes_the_whole_set_and_lists_it_back(self, db) -> None:
        org = await _org(db)
        environment = await _environment(db, org)
        sandbox = await _connection(db, org)
        test_key = await _secret(db, org)
        production_connection, production_key = uuid.uuid4(), uuid.uuid4()

        await agent_environment_repo.replace_connections(
            db,
            environment_id=environment.id,
            organization_id=org.id,
            connections=[
                AgentEnvironmentConnection(
                    kind="mcp",
                    production_id=production_connection,
                    test_connection_id=sandbox.id,
                ),
                AgentEnvironmentConnection(
                    kind="secret", production_id=production_key, test_secret_id=test_key.id
                ),
            ],
        )
        await agent_environment_repo.replace_connections(
            db,
            environment_id=environment.id,
            organization_id=org.id,
            connections=[
                AgentEnvironmentConnection(
                    kind="secret", production_id=production_key, test_secret_id=test_key.id
                )
            ],
        )

        rows = await agent_environment_repo.list_connections(
            db, environment_ids=[environment.id], organization_id=org.id
        )
        assert [(row.kind, row.production_id, row.test_id) for row in rows] == [
            ("secret", production_key, test_key.id)
        ]

    async def test_another_organizations_overrides_are_not_listed(self, db) -> None:
        org, other = await _org(db), await _org(db)
        environment = await _environment(db, org)
        await agent_environment_repo.replace_connections(
            db,
            environment_id=environment.id,
            organization_id=org.id,
            connections=[
                AgentEnvironmentConnection(
                    kind="mcp",
                    production_id=uuid.uuid4(),
                    test_connection_id=(await _connection(db, org)).id,
                )
            ],
        )

        assert (
            await agent_environment_repo.list_connections(
                db, environment_ids=[environment.id], organization_id=other.id
            )
            == []
        )

    async def test_no_environments_asks_nothing(self, db) -> None:
        org = await _org(db)

        assert (
            await agent_environment_repo.list_connections(
                db, environment_ids=[], organization_id=org.id
            )
            == []
        )

    async def test_deleting_the_test_side_leaves_the_override_switched_off(self, db) -> None:
        """Cascading the row away would let staging fall back to production."""
        org = await _org(db)
        environment = await _environment(db, org)
        sandbox = await _connection(db, org)
        production_id = uuid.uuid4()
        db.add(
            AgentEnvironmentConnection(
                organization_id=org.id,
                environment_id=environment.id,
                kind="mcp",
                production_id=production_id,
                test_connection_id=sandbox.id,
            )
        )
        await db.flush()

        environment_id, org_id = environment.id, org.id
        await db.execute(delete(McpConnection).where(McpConnection.id == sandbox.id))
        db.expire_all()

        (row,) = await agent_environment_repo.list_connections(
            db, environment_ids=[environment_id], organization_id=org_id
        )
        assert (row.production_id, row.test_id) == (production_id, None)

    async def test_a_secret_override_cannot_carry_a_connection(self, db) -> None:
        org = await _org(db)
        environment = await _environment(db, org)
        db.add(
            AgentEnvironmentConnection(
                organization_id=org.id,
                environment_id=environment.id,
                kind="secret",
                production_id=uuid.uuid4(),
                test_connection_id=(await _connection(db, org)).id,
            )
        )

        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_one_binding_has_one_override_per_environment(self, db) -> None:
        org = await _org(db)
        environment = await _environment(db, org)
        production_id = uuid.uuid4()
        for _ in range(2):
            db.add(
                AgentEnvironmentConnection(
                    organization_id=org.id,
                    environment_id=environment.id,
                    kind="secret",
                    production_id=production_id,
                    test_secret_id=(await _secret(db, org)).id,
                )
            )

        with pytest.raises(IntegrityError):
            await db.flush()


async def _run(db, org: Organization) -> AgentRun:
    environment = await _environment(db, org)
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=environment.agent_id,
        surface="api",
        status="completed",
    )
    db.add(run)
    await db.flush()
    return run


def _call(tool_name: str, outcome: str = "blocked") -> InterceptedToolCall:
    return InterceptedToolCall(
        tool_name=tool_name, tool_id=f"mcp:{tool_name}", args={"to": "a@b.c"}, outcome=outcome
    )


class TestInterceptedCalls:
    async def test_a_second_batch_continues_the_runs_order(self, db) -> None:
        """A parked run is finished twice; its calls stay one sequence."""
        org = await _org(db)
        run = await _run(db, org)

        await intercepted_tool_call_repo.add_many(
            db, run_id=run.id, organization_id=org.id, calls=[_call("crm_create"), _call("send")]
        )
        await intercepted_tool_call_repo.add_many(
            db, run_id=run.id, organization_id=org.id, calls=[_call("crm_update", "divergent")]
        )
        await intercepted_tool_call_repo.add_many(
            db, run_id=run.id, organization_id=org.id, calls=[]
        )

        rows = await intercepted_tool_call_repo.list_for_run(
            db, run_id=run.id, organization_id=org.id
        )
        assert [(row.sequence, row.tool_name, row.outcome) for row in rows] == [
            (0, "crm_create", "blocked"),
            (1, "send", "blocked"),
            (2, "crm_update", "divergent"),
        ]
        assert rows[0].args == {"to": "a@b.c"}

    async def test_another_organization_reads_nothing(self, db) -> None:
        org, other = await _org(db), await _org(db)
        run = await _run(db, org)
        await intercepted_tool_call_repo.add_many(
            db, run_id=run.id, organization_id=org.id, calls=[_call("send")]
        )

        assert (
            await intercepted_tool_call_repo.list_for_run(
                db, run_id=run.id, organization_id=other.id
            )
            == []
        )

    async def test_an_unknown_outcome_is_refused(self, db) -> None:
        org = await _org(db)
        run = await _run(db, org)
        db.add(
            InterceptedToolCall(
                organization_id=org.id,
                run_id=run.id,
                sequence=0,
                tool_name="send",
                tool_id="mcp:send",
                outcome="executed",
            )
        )

        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_the_calls_go_with_the_run(self, db) -> None:
        org = await _org(db)
        run = await _run(db, org)
        await intercepted_tool_call_repo.add_many(
            db, run_id=run.id, organization_id=org.id, calls=[_call("send")]
        )

        await db.execute(delete(AgentRun).where(AgentRun.id == run.id))

        remaining = await db.execute(
            select(InterceptedToolCall).where(InterceptedToolCall.run_id == run.id)
        )
        assert remaining.scalars().all() == []
