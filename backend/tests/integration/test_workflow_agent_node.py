"""`agent.run` in a real run: a pinned version, typed answers, grounded prompts (#1789).

The agent is created and published through the real registry, and the run goes
through the real `AgentRunnerService` - budgets, run history, transcripts - with
only the model replaced by a `FunctionModel` that answers in-process and records
what it was told. That is what lets these tests prove *which version* answered:
the instructions each version was published with reach the model or they do not.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.agents.spec import AgentSpec
from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.credential import ModelProfile
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRunStatus
from app.services.agent_registry import AgentRegistryService
from app.services.rag.models import SearchResult
from app.workflows.contracts.io import Binding, LiteralValue, NodeOutputRef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from app.workflows.nodes.knowledge_search import _handler as search_handler
from tests.integration.workflow_run_support import (
    SeededRun,
    drive,
    node_statuses,
    seed_member,
    seed_run,
)

pytestmark = pytest.mark.anyio


class _Model:
    """What the model is told, and what it answers."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.instructions: list[str] = []
        self.prompts: list[str] = []

    def function_model(self) -> FunctionModel:
        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            for message in messages:
                if isinstance(message, ModelRequest):
                    if message.instructions:
                        self.instructions.append(message.instructions)
                    for part in message.parts:
                        content = getattr(part, "content", None)
                        if not isinstance(content, str):
                            continue
                        if part.part_kind == "user-prompt":
                            self.prompts.append(content)
                        elif part.part_kind == "system-prompt":
                            self.instructions.append(content)
            return ModelResponse(parts=[TextPart(self.answer)])

        return FunctionModel(respond)


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch):
    def install(answer: str) -> _Model:
        recorder = _Model(answer)
        monkeypatch.setattr(
            "app.agents.model_resolver.build_model", lambda *_args: recorder.function_model()
        )
        return recorder

    return install


async def _tenant(engine: AsyncEngine) -> tuple[User, Organization]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        member = await seed_member(db)
        await db.commit()
    return member


async def _profile(engine: AsyncEngine, org: Organization) -> uuid.UUID:
    sealed = seal_secret(
        ApiKeySecret(api_key="sk-test-key-0000"), scope=VaultScope.organization(org.id)
    )
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        secret = OrganizationSecret(
            id=uuid.uuid4(),
            organization_id=org.id,
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
            organization_id=org.id,
            label="Default",
            provider="openai",
            model="gpt-4.1",
            secret_id=secret.id,
        )
        db.add(profile)
        await db.commit()
    return profile.id


async def _published(
    engine: AsyncEngine, seeded_ctx: Any, profile_id: uuid.UUID, instructions: str
) -> tuple[uuid.UUID, uuid.UUID]:
    """A new agent published once with `instructions`: its id and that version's."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        registry = AgentRegistryService(db)
        agent = await registry.create(
            seeded_ctx,
            AgentSpec(
                name=f"Analyst {uuid.uuid4().hex[:6]}",
                instructions=instructions,
                model_profile_id=profile_id,
            ),
        )
        version = await registry.publish(seeded_ctx, agent.id)
        await db.commit()
    return agent.id, version.id


async def _republish(
    engine: AsyncEngine,
    seeded_ctx: Any,
    agent_id: uuid.UUID,
    profile_id: uuid.UUID,
    instructions: str,
) -> uuid.UUID:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        registry = AgentRegistryService(db)
        agent = await registry.get(seeded_ctx, agent_id)
        spec = AgentSpec.model_validate(agent.draft_spec)
        await registry.save_draft(
            seeded_ctx, agent_id, spec.model_copy(update={"instructions": instructions})
        )
        version = await registry.publish(seeded_ctx, agent_id)
        await db.commit()
    return version.id


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _edge(source: NodeInstance, target: NodeInstance) -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port="out",
        target_node_id=target.id,
        target_port="in",
    )


def _graph(agent_id: uuid.UUID, version_id: uuid.UUID, **config: Any) -> WorkflowGraph:
    entry = _node("core.input")
    ask = _node(
        "agent.run",
        {"agent": {"agent_id": str(agent_id), "version_id": str(version_id)}, **config},
    )
    output = _node("core.output")
    return WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, ask, output),
        edges=(_edge(entry, ask), _edge(ask, output)),
        bindings=(
            Binding(
                target_node_id=ask.id,
                target_field="prompt",
                source=NodeOutputRef(node_id=entry.id, port="out", field_path=("payload", "q")),
            ),
            Binding(
                target_node_id=output.id,
                target_field="text",
                source=NodeOutputRef(node_id=ask.id, port="out", field_path=("text",)),
            ),
            Binding(
                target_node_id=output.id,
                target_field="structured",
                source=NodeOutputRef(node_id=ask.id, port="out", field_path=("structured",)),
            ),
        ),
    )


async def _setup(engine: AsyncEngine, graph_for: Any, instructions: str = "Be brief.") -> SeededRun:
    member = await _tenant(engine)
    profile_id = await _profile(engine, member[1])
    placeholder = await seed_run(
        engine,
        WorkflowGraph(entry_node_id=uuid.uuid4(), nodes=(_node("core.input"),)),
        member=member,
    )
    agent_id, version_id = await _published(engine, placeholder.ctx, profile_id, instructions)
    graph = graph_for(agent_id, version_id)
    seeded = await seed_run(engine, graph, run_input={"q": "Score this lead"}, member=member)
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)
    return seeded


async def test_the_pinned_agent_answers_and_its_answer_is_the_runs_output(
    engine: AsyncEngine, model
):
    recorder = model("Warm lead.")
    seeded = await _setup(engine, _graph)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output is not None and run.output["text"] == "Warm lead."
    assert recorder.prompts == ["Score this lead"]
    async with seeded.factory() as db:
        (agent_run,) = (await db.execute(select(AgentRun))).scalars()
    assert agent_run.surface == RunSurface.WORKFLOW.value
    assert agent_run.status == RunStatus.COMPLETED.value
    assert agent_run.user_id == seeded.principal.id


async def test_a_step_keeps_running_the_version_it_pins_after_a_newer_one_is_published(
    engine: AsyncEngine, model
):
    recorder = model("ok")
    member = await _tenant(engine)
    profile_id = await _profile(engine, member[1])
    ctx_run = await seed_run(
        engine,
        WorkflowGraph(entry_node_id=uuid.uuid4(), nodes=(_node("core.input"),)),
        member=member,
    )
    agent_id, first = await _published(engine, ctx_run.ctx, profile_id, "Version one says hello.")
    await _republish(engine, ctx_run.ctx, agent_id, profile_id, "Version two says goodbye.")
    seeded = await seed_run(engine, _graph(agent_id, first), run_input={"q": "hi"}, member=member)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert any("Version one says hello." in text for text in recorder.instructions)
    assert not any("Version two" in text for text in recorder.instructions)


async def test_a_structured_answer_is_parsed_and_checked_against_its_schema(
    engine: AsyncEngine, model
):
    model('```json\n{"score": 87, "tier": "warm"}\n```')
    schema = {
        "type": "object",
        "properties": {"score": {"type": "integer"}, "tier": {"type": "string"}},
        "required": ["score"],
    }
    seeded = await _setup(engine, lambda a, v: _graph(a, v, structured_output_schema=schema))

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output is not None
    assert run.output["structured"] == {"score": 87, "tier": "warm"}


@pytest.mark.parametrize(
    "answer",
    ['{"score": "high"}', "Pretty warm, I would say", "[87]"],
    ids=["wrong-type", "not-json", "not-an-object"],
)
async def test_an_answer_of_the_wrong_shape_fails_before_the_next_step(
    engine: AsyncEngine, model, answer: str
):
    model(answer)
    schema = {"type": "object", "properties": {"score": {"type": "integer"}}, "required": ["score"]}
    seeded = await _setup(engine, lambda a, v: _graph(a, v, structured_output_schema=schema))

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "STRUCTURED_OUTPUT_MISMATCH"
    # The answer itself is not repeated in the error a viewer of the workflow reads.
    assert "high" not in str(run.error) and "warm" not in str(run.error)
    # Nothing downstream ran: the output step never got a node run at all.
    assert run.output is None
    assert seeded.graph.nodes[2].id not in await node_statuses(seeded)


async def test_sources_ground_the_prompt_as_numbered_context(engine: AsyncEngine, model):
    recorder = model("Thirty days [1].")
    sources = [
        {
            "filename": "policy.pdf",
            "collection": "handbook",
            "page": 4,
            "score": 0.9,
            "content": "Refunds within thirty days.",
        }
    ]

    def graph_for(agent_id: uuid.UUID, version_id: uuid.UUID) -> WorkflowGraph:
        graph = _graph(agent_id, version_id)
        ask = graph.nodes[1]
        return graph.model_copy(
            update={
                "bindings": (
                    *graph.bindings,
                    Binding(
                        target_node_id=ask.id,
                        target_field="sources",
                        source=LiteralValue(value=sources),
                    ),
                )
            }
        )

    seeded = await _setup(engine, graph_for)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    (prompt,) = recorder.prompts
    assert prompt.startswith("Score this lead")
    assert "[1] policy.pdf, page 4\nRefunds within thirty days." in prompt


@pytest.mark.security
async def test_a_version_of_another_agent_cannot_be_pinned(engine: AsyncEngine, model):
    model("x")
    member = await _tenant(engine)
    profile_id = await _profile(engine, member[1])
    ctx_run = await seed_run(
        engine,
        WorkflowGraph(entry_node_id=uuid.uuid4(), nodes=(_node("core.input"),)),
        member=member,
    )
    agent_id, _own = await _published(engine, ctx_run.ctx, profile_id, "a")
    _other_agent, foreign_version = await _published(engine, ctx_run.ctx, profile_id, "b")
    graph = _graph(agent_id, foreign_version)
    seeded = await seed_run(engine, graph, member=member)

    with pytest.raises(GraphValidationError) as refused:
        async with async_sessionmaker(engine)() as db:
            await validate_graph(db, seeded.ctx, graph)

    ask = graph.nodes[1]
    assert f"nodes.{ask.id}.config.agent" in {p["field"] for p in refused.value.details["fields"]}


async def test_a_question_is_answered_through_retrieval_and_an_agent(
    engine: AsyncEngine, model, monkeypatch: pytest.MonkeyPatch
):
    """The acceptance journey: input -> knowledge.search -> agent.run -> output."""

    class _Retrieval:
        async def resolve_scope(self, name: str, organization_id: uuid.UUID) -> str:
            return name

        async def retrieve(self, **_kwargs: Any) -> list[SearchResult]:
            return [
                SearchResult(
                    content="Refunds are accepted within thirty days.",
                    score=0.93,
                    metadata={"filename": "policy.pdf", "page_num": 4},
                )
            ]

    monkeypatch.setattr(search_handler, "get_retrieval_service", lambda: _Retrieval())
    recorder = model("Within thirty days [1].")
    member = await _tenant(engine)
    profile_id = await _profile(engine, member[1])
    ctx_run = await seed_run(
        engine,
        WorkflowGraph(entry_node_id=uuid.uuid4(), nodes=(_node("core.input"),)),
        member=member,
    )
    agent_id, version_id = await _published(engine, ctx_run.ctx, profile_id, "Answer from context.")
    name = f"kb_{uuid.uuid4().hex[:8]}"
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        kb = KnowledgeBase(
            id=uuid.uuid4(),
            name=name,
            scope=KBScope.ORG.value,
            collection_name=name,
            embedding_model="text-embedding-3-small",
            embedding_dim=1536,
            embedding_provider="openrouter",
            organization_id=member[1].id,
            owner_user_id=member[0].id,
            visibility="org",
        )
        db.add(kb)
        await db.commit()

    entry = _node("core.input")
    search = _node("knowledge.search", {"collection_ids": [str(kb.id)]})
    ask = _node("agent.run", {"agent": {"agent_id": str(agent_id), "version_id": str(version_id)}})
    output = _node("core.output")

    def ref(node: NodeInstance, *path: str) -> NodeOutputRef:
        return NodeOutputRef(node_id=node.id, port="out", field_path=path)

    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, search, ask, output),
        edges=(_edge(entry, search), _edge(search, ask), _edge(ask, output)),
        bindings=(
            Binding(
                target_node_id=search.id, target_field="query", source=ref(entry, "payload", "q")
            ),
            Binding(
                target_node_id=ask.id, target_field="prompt", source=ref(entry, "payload", "q")
            ),
            Binding(target_node_id=ask.id, target_field="sources", source=ref(search, "sources")),
            Binding(target_node_id=output.id, target_field="text", source=ref(ask, "text")),
            Binding(target_node_id=output.id, target_field="sources", source=ref(ask, "sources")),
        ),
    )
    seeded = await seed_run(
        engine, graph, run_input={"q": "How long do refunds take?"}, member=member
    )
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output is not None
    assert run.output["text"] == "Within thirty days [1]."
    assert [source["filename"] for source in run.output["sources"]] == ["policy.pdf"]
    (prompt,) = recorder.prompts
    assert "Refunds are accepted within thirty days." in prompt
