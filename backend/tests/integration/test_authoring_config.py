"""What the improver reads about an agent's configuration, and what the registry lets it add.

The configuration section names every changeable path with its value - a
specialist's description, an MCP binding and the tools its server offers - and
what the person asking may add. Names on a card are only those the reader may
see. A widened MCP binding says which newly reached tools write; a change of
model is priced on recent runs, and says so when it cannot be.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.agents.spec import AgentSpec
from app.db.models.agent_run import AgentRun
from app.db.models.authoring import HunkKind, HunkOrigin, SpecProposalHunk
from app.db.models.context import ContextFile
from app.db.models.credential import ModelProfile
from app.db.models.mcp_connection import McpConnection
from app.schemas.authoring import FieldChange
from app.services.agent_registry import AgentRegistryService
from app.services.authoring_config import ConfigurationService
from app.services.authoring_evidence import EvidencePack
from tests.integration.test_authoring import _owner, _published

pytestmark = pytest.mark.anyio


async def _connection(db, ctx) -> McpConnection:
    connection = McpConnection(
        id=uuid.uuid4(),
        scope="org",
        organization_id=ctx.organization_id,
        name=f"crm-{uuid.uuid4().hex[:6]}",
        url="https://mcp.example.com/sse",
        secret_key_version=1,
        last_tools=[
            {"name": "find", "description": "Finds", "read_only": True},
            {"name": "update", "description": "Updates", "read_only": False},
        ],
    )
    db.add(connection)
    await db.flush()
    return connection


async def _context(db, ctx, name: str = "policy") -> ContextFile:
    file = ContextFile(
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility="org",
        name=f"{name}-{uuid.uuid4().hex[:4]}",
        content="Returns take 30 days.",
        mode="inject",
    )
    db.add(file)
    await db.flush()
    return file


def _spec(connection: McpConnection, **values: Any) -> AgentSpec:
    return AgentSpec.model_validate(
        {
            "name": "Clerk",
            "instructions": "Help.",
            "capabilities": [
                {
                    "id": "subagents",
                    "config": {
                        "inline": [
                            {"name": "triage", "description": "Sorts", "instructions": "Sort."}
                        ]
                    },
                }
            ],
            "mcp_servers": [
                {
                    "account": "organization",
                    "connection_id": str(connection.id),
                    "allowed_tools": ["find"],
                },
                {"account": "personal", "catalog_key": "notion"},
            ],
            **values,
        }
    )


def _hunk(path: str, op: str, base: Any, new: Any) -> SpecProposalHunk:
    return SpecProposalHunk(
        kind=HunkKind.SPEC_FIELD.value, path=path, op=op, base_value=base, new_value=new
    )


def _field(path: str, op: str, value: Any) -> FieldChange:
    return FieldChange(path=path, op=op, value=value, rationale="r", expected_effect="e")


async def test_the_configuration_names_every_path_and_what_the_server_offers(db):
    ctx = await _owner(db)
    connection = await _connection(db, ctx)
    file = await _context(db, ctx)

    text = await ConfigurationService(db).describe(ctx, _spec(connection, context_ids=[file.id]))

    assert 'capabilities/subagents/inline/triage/description: "Sorts"' in text
    assert f'mcp_servers/{connection.id}/allowed_tools: ["find"]' in text
    assert "find (reads), update (writes)" in text
    assert "mcp_servers/personal:notion/allowed_tools: null" in text
    assert f"{file.id} ({file.name} (inject))" in text


async def test_a_widened_binding_says_which_newly_reached_tools_write(db):
    ctx = await _owner(db)
    connection = await _connection(db, ctx)
    spec = _spec(connection)
    service = ConfigurationService(db)
    path = f"mcp_servers/{connection.id}/allowed_tools"

    widened, narrowed = await service.stage(
        ctx,
        agent_id=uuid.uuid4(),
        spec=spec,
        changes=[_field(path, "set", None), _field(path, "set", [])],
        pack=EvidencePack(),
        origin=HunkOrigin.IMPROVE,
    )
    personal = await service.stage(
        ctx,
        agent_id=uuid.uuid4(),
        spec=spec,
        changes=[_field("mcp_servers/personal:notion/allowed_tools", "set", ["search"])],
        pack=EvidencePack(),
        origin=HunkOrigin.IMPROVE,
    )

    assert widened["effect"] == {"writes": ["update"]}
    assert narrowed["effect"] is None
    # A personal account's server is somebody's own, and lists nothing to read here.
    assert [(hunk["new_value"], hunk["effect"]) for hunk in personal] == [(["search"], None)]


async def test_a_model_change_says_when_it_cannot_be_priced(db):
    ctx = await _owner(db)
    connection = await _connection(db, ctx)
    unpriced = ModelProfile(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        label="House model",
        provider="custom",
        model="house-1",
    )
    db.add(unpriced)
    await db.flush()
    service = ConfigurationService(db)
    agent = await _published(db, ctx, name="Clerk", spec=_spec(connection).model_dump(mode="json"))

    nothing_ran = await service.cost(ctx, agent.id, str(unpriced.id), str(uuid.uuid4()))
    db.add(
        AgentRun(
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            user_id=ctx.user_id,
            surface="web",
            status="completed",
            input_tokens=1000,
            output_tokens=100,
            started_at=datetime.now(UTC),
        )
    )
    await db.flush()
    one_ran = await service.cost(ctx, agent.id, str(unpriced.id), str(uuid.uuid4()))

    unknown = {"cost_per_run_before": None, "cost_per_run_after": None}
    assert nothing_ran == {"runs": 0, "rough": True, **unknown}
    assert one_ran == {"runs": 1, "rough": True, **unknown}


async def test_a_card_names_only_what_its_reader_may_see(db):
    ctx = await _owner(db)
    connection = await _connection(db, ctx)
    file = await _context(db, ctx)
    hunks = [
        _hunk("context_ids", "add", None, str(file.id)),
        _hunk(f"mcp_servers/{connection.id}/allowed_tools", "set", ["find"], None),
        _hunk("capabilities", "remove", {"id": "retired"}, None),
        _hunk("capabilities", "add", None, {"id": "charts"}),
        _hunk("model_profile_id", "set", "not-an-id", None),
        SpecProposalHunk(kind=HunkKind.INSTRUCTIONS.value),
    ]

    names = await ConfigurationService(db).names(ctx, hunks)

    assert names == {
        str(file.id): file.name,
        str(connection.id): connection.name,
        "charts": "Charts",
    }


async def test_the_registry_asks_only_about_what_a_change_adds(db):
    ctx = await _owner(db)
    connection = await _connection(db, ctx)
    registry = AgentRegistryService(db)
    spec = _spec(connection)
    gone = uuid.uuid4()

    assert await registry.reference_problems(ctx, spec, path="description", op="set") == []
    assert await registry.reference_problems(ctx, spec, path="budget", op="set") == []
    assert await registry.reference_problems(ctx, spec, path="context_ids", op="remove") == []
    assert await registry.reference_problems(
        ctx, spec.model_copy(update={"context_ids": [gone]}), path="context_ids", op="add"
    )
    assert await registry.reference_problems(
        ctx, spec.model_copy(update={"model_profile_id": gone}), path="model_profile_id", op="set"
    ) == ["The selected model profile no longer exists"]
    assert await registry.reference_problems(ctx, spec, path="model_profile_id", op="set") == []
    assert (
        await registry.reference_problems(
            ctx, spec, path=f"mcp_servers/{connection.id}/allowed_tools", op="set"
        )
        == []
    )
    assert (
        await registry.reference_problems(ctx, spec, path="capabilities/missing/config", op="set")
        == []
    )
