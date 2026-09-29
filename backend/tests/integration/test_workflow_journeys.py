"""The Workflows + Virtual Tables milestone's user journeys, end to end (#1793).

Each journey publishes its workflow through the real registry, so the graph is
validated the way the editor's Publish is, and drives the run through the real
dispatcher against Postgres. Only the model and the vector search are stand-ins:
the model answers in-process per agent, and the search answers with fixed
passages. The last tests break a journey on purpose - a worker that dies after a
step's effect, one that dies inside a model call, and a member who loses access
halfway - to show what is and is not repeated.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.spec import AgentSpec
from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation, Message
from app.db.models.credential import ModelProfile
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.user import User
from app.db.models.virtual_table import VirtualTableRecord, VirtualTableRecordHistory
from app.db.models.virtual_table_trigger import VirtualTableTrigger
from app.db.models.workflow_file import WorkflowFile
from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    NodeRun,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowRunTrigger,
)
from app.main import app
from app.schemas.virtual_table import ColumnInput, ColumnTypeName, TableCreate, TableRead
from app.schemas.workflow import WorkflowCreate, WorkflowDraftUpdate, WorkflowPublish
from app.services.agent_registry import AgentRegistryService
from app.services.file_storage import LocalFileStorage
from app.services.rag.models import SearchResult
from app.services.virtual_tables.facade import VirtualTableService
from app.services.virtual_tables.triggers import TableTriggerConsumer
from app.services.workflow_execution import WorkflowExecutionService, dispatcher
from app.services.workflow_execution.reconciler import WorkflowReconcilerService
from app.services.workflow_registry import WorkflowRegistryService
from app.workflows.contracts.io import (
    Binding,
    FileRef,
    LiteralValue,
    NodeOutputRef,
    TableIORef,
)
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.nodes.knowledge_search import _handler as search_handler
from tests.integration.workflow_run_support import SeededRun, drive, seed_member, tick

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_prefect_submission():
    with patch("app.worker.tasks.workflow_tasks.run_deployment", new=AsyncMock()) as submitted:
        yield submitted


# The model and the search


class _Agents:
    """One model for every agent: each answers by the marker in its instructions."""

    def __init__(self, answers: dict[str, str | dict[str, Any]]) -> None:
        self.answers = answers
        self.prompts: dict[str, list[str]] = {marker: [] for marker in answers}
        self.calls = 0

    def model(self) -> FunctionModel:
        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            self.calls += 1
            told = [info.instructions or ""]
            asked: list[str] = []
            for message in messages:
                if not isinstance(message, ModelRequest):
                    continue
                told.append(message.instructions or "")
                for part in message.parts:
                    content = getattr(part, "content", None)
                    if part.part_kind == "system-prompt" and isinstance(content, str):
                        told.append(content)
                    elif part.part_kind == "user-prompt" and isinstance(content, str):
                        asked.append(content)
            marker = next(key for key in self.answers if any(key in text for text in told))
            self.prompts[marker] += asked
            answer = self.answers[marker]
            if isinstance(answer, dict):
                # Asked for an object: it is handed back as the output tool's arguments.
                return ModelResponse(
                    parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=answer)]
                )
            return ModelResponse(parts=[TextPart(answer)])

        return FunctionModel(respond)


@pytest.fixture
def agents(monkeypatch: pytest.MonkeyPatch):
    def install(answers: dict[str, str | dict[str, Any]]) -> _Agents:
        recorder = _Agents(answers)
        monkeypatch.setattr(
            "app.agents.model_resolver.build_model", lambda *_args: recorder.model()
        )
        return recorder

    return install


class _Retrieval:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.queries: list[str] = []

    async def resolve_scope(self, name: str, organization_id: uuid.UUID) -> str:
        return f"scope:{name}:{organization_id}"

    async def retrieve(self, **kwargs: Any) -> list[SearchResult]:
        self.queries.append(str(kwargs.get("query")))
        return self.results

    async def retrieve_multi(self, **kwargs: Any) -> list[SearchResult]:
        return await self.retrieve(**kwargs)


# A tenant, its agents, its workflows


@dataclass
class _World:
    factory: async_sessionmaker[AsyncSession]
    owner: User
    org: Organization
    profile_id: uuid.UUID

    @property
    def ctx(self) -> AuthContext:
        return AuthContext(user_id=self.owner.id, organization_id=self.org.id, role="owner")

    async def agent(self, instructions: str, **spec: Any) -> dict[str, str]:
        """A published agent's pin, as `agent.run`'s config names it."""
        async with self.factory() as db:
            registry = AgentRegistryService(db)
            agent = await registry.create(
                self.ctx,
                AgentSpec(
                    name=f"Agent {uuid.uuid4().hex[:6]}",
                    instructions=instructions,
                    model_profile_id=self.profile_id,
                    **spec,
                ),
            )
            version = await registry.publish(self.ctx, agent.id)
            await db.commit()
        return {"agent_id": str(agent.id), "version_id": str(version.id)}

    async def workflow(self, graph: WorkflowGraph, name: str = "Journey") -> uuid.UUID:
        """A workflow published through the registry - validated as Publish is."""
        async with self.factory() as db:
            registry = WorkflowRegistryService(db)
            made = await registry.create(self.ctx, WorkflowCreate(name=name))
            draft = await registry.update_draft(
                self.ctx,
                made.id,
                WorkflowDraftUpdate(
                    graph=graph.model_dump(mode="json"), expected_revision=made.draft_revision
                ),
            )
            await registry.publish(
                self.ctx, made.id, WorkflowPublish(expected_revision=draft.draft_revision)
            )
            await db.commit()
        return made.id

    async def table(self, name: str, *columns: tuple[str, ColumnTypeName]) -> TableRead:
        async with self.factory() as db:
            made = await VirtualTableService(db).create_table(
                self.ctx,
                TableCreate(
                    name=name,
                    columns=[ColumnInput(label=label, type=kind) for label, kind in columns],
                ),
            )
            await db.commit()
        return made

    async def run(self, run_id: uuid.UUID) -> WorkflowRun:
        async with self.factory() as db:
            return (
                await db.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
            ).scalar_one()

    async def seeded(self, run_id: uuid.UUID, graph: WorkflowGraph) -> SeededRun:
        return SeededRun(
            run=await self.run(run_id),
            graph=graph,
            principal=self.owner,
            org=self.org,
            factory=self.factory,
        )

    async def start(self, workflow_id: uuid.UUID, **options: Any) -> uuid.UUID:
        async with self.factory() as db:
            started = await WorkflowExecutionService(db).start(self.ctx, workflow_id, **options)
            await db.commit()
        return started.id


async def _profile(factory: async_sessionmaker[AsyncSession], org: Organization) -> uuid.UUID:
    sealed = seal_secret(
        ApiKeySecret(api_key="sk-test-key-0000"), scope=VaultScope.organization(org.id)
    )
    async with factory() as db:
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


@pytest.fixture
async def world(engine: AsyncEngine) -> _World:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        owner, org = await seed_member(db)
        await db.commit()
    return _World(factory=factory, owner=owner, org=org, profile_id=await _profile(factory, org))


# Graph building


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _edge(source: NodeInstance, target: NodeInstance, port: str = "out") -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port=port,
        target_node_id=target.id,
        target_port="in",
    )


def _chain(*nodes: NodeInstance) -> list[Edge]:
    return [_edge(a, b) for a, b in pairwise(nodes)]


def _bind(
    target: NodeInstance, field: str, source: NodeInstance, *path: str, port: str = "out"
) -> Binding:
    return Binding(
        target_node_id=target.id,
        target_field=field,
        source=NodeOutputRef(node_id=source.id, port=port, field_path=path),
    )


def _literal(target: NodeInstance, field: str, value: Any) -> Binding:
    return Binding(target_node_id=target.id, target_field=field, source=LiteralValue(value=value))


def _pin(table: TableRead) -> dict[str, Any]:
    return {
        "table": TableIORef(table_id=table.id, schema_version=table.schema_version).model_dump(
            mode="json"
        )
    }


# Journey 1: /chat -> retrieval -> agent -> answer


async def test_a_chat_question_is_answered_from_the_knowledge_base_into_the_thread(
    world: _World, agents, monkeypatch: pytest.MonkeyPatch
):
    recorder = agents({"You answer from the handbook.": "Thirty days, per the policy [1]."})
    retrieval = _Retrieval(
        [
            SearchResult(
                content="Refunds are accepted within thirty days.",
                score=0.93,
                metadata={"filename": "policy.pdf", "page_num": 4, "document_id": "doc-1"},
            )
        ]
    )
    monkeypatch.setattr(search_handler, "get_retrieval_service", lambda: retrieval)
    collection = KnowledgeBase(
        id=uuid.uuid4(),
        name="handbook",
        scope=KBScope.ORG.value,
        collection_name=f"kb_{uuid.uuid4().hex[:10]}",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_provider="openrouter",
        organization_id=world.org.id,
        owner_user_id=world.owner.id,
        visibility="org",
    )
    conversation = Conversation(
        id=uuid.uuid4(), organization_id=world.org.id, user_id=world.owner.id
    )
    async with world.factory() as db:
        db.add_all([collection, conversation])
        await db.commit()
    answerer = await world.agent("You answer from the handbook.")
    entry = _node("trigger.chat")
    search = _node("knowledge.search", {"collection_ids": [str(collection.id)], "top_k": 3})
    ask = _node("agent.run", {"agent": answerer})
    output = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, search, ask, output),
        edges=tuple(_chain(entry, search, ask, output)),
        bindings=(
            _bind(search, "query", entry, "prompt"),
            _bind(ask, "prompt", entry, "prompt"),
            _bind(ask, "sources", search, "sources"),
            _bind(output, "text", ask, "text"),
        ),
    )
    workflow_id = await world.workflow(graph, "Handbook answers")

    run_id = await world.start(
        workflow_id,
        triggered_by=WorkflowRunTrigger.CHAT,
        run_input={
            "prompt": "How long do refunds take?",
            "conversation_id": str(conversation.id),
            "user_id": str(world.owner.id),
        },
        reply_conversation_id=conversation.id,
    )
    run = await drive(await world.seeded(run_id, graph))

    assert run.status == WorkflowRunStatus.SUCCEEDED.value, run.error
    assert retrieval.queries == ["How long do refunds take?"]
    (asked,) = recorder.prompts["You answer from the handbook."]
    assert "Refunds are accepted within thirty days." in asked
    async with world.factory() as db:
        (answer,) = (
            await db.execute(select(Message).where(Message.conversation_id == conversation.id))
        ).scalars()
    assert (answer.role, answer.content) == ("assistant", "Thirty days, per the policy [1].")
    assert [part["type"] for part in answer.parts] == ["workflow_run", "text"]
    assert answer.parts[0]["status"] == WorkflowRunStatus.SUCCEEDED.value


# Journey 2: two agents in sequence


async def test_two_agents_answer_in_turn_each_on_what_the_one_before_said(world: _World, agents):
    recorder = agents(
        {
            "You extract the facts.": {"company": "Acme", "seats": 40},
            "You write the reply.": "Acme wants 40 seats; I will send a quote.",
        }
    )
    schema = {
        "type": "object",
        "properties": {"company": {"type": "string"}, "seats": {"type": "integer"}},
        "required": ["company", "seats"],
    }
    extractor = await world.agent("You extract the facts.")
    writer = await world.agent("You write the reply.")
    entry = _node("core.input")
    extract = _node("agent.run", {"agent": extractor, "structured_output_schema": schema})
    write = _node("agent.run", {"agent": writer})
    output = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, extract, write, output),
        edges=tuple(_chain(entry, extract, write, output)),
        bindings=(
            _bind(extract, "prompt", entry, "payload", "email"),
            _bind(write, "prompt", extract, "text"),
            _bind(output, "text", write, "text"),
            _bind(output, "structured", extract, "structured"),
        ),
    )
    workflow_id = await world.workflow(graph, "Two agents")

    run_id = await world.start(workflow_id, run_input={"email": "Hi, Acme here, 40 seats?"})
    run = await drive(await world.seeded(run_id, graph))

    assert run.status == WorkflowRunStatus.SUCCEEDED.value, run.error
    assert run.output is not None
    assert run.output["text"] == "Acme wants 40 seats; I will send a quote."
    assert run.output["structured"] == {"company": "Acme", "seats": 40}
    assert recorder.prompts["You extract the facts."] == ["Hi, Acme here, 40 seats?"]
    # The writer reads the extractor's answer as text: the object, as a JSON block.
    assert recorder.prompts["You write the reply."] == [
        '```json\n{\n  "company": "Acme",\n  "seats": 40\n}\n```'
    ]
    async with world.factory() as db:
        answered = (
            (await db.execute(select(AgentRun).order_by(AgentRun.created_at))).scalars().all()
        )
    assert len(answered) == 2 and all(row.user_id == world.owner.id for row in answered)


# Journey 3: an API-created lead -> table trigger -> analysis -> update -> notification


@dataclass
class _LeadPipeline:
    leads: TableRead
    graph: WorkflowGraph
    update: NodeInstance
    analyse: NodeInstance
    trigger_id: uuid.UUID


async def _lead_pipeline(world: _World) -> _LeadPipeline:
    leads = await world.table("Leads", ("Email", "text"), ("Score", "integer"), ("Tier", "text"))
    analyst = await world.agent("You score leads.")
    schema = {
        "type": "object",
        "properties": {"Score": {"type": "integer"}, "Tier": {"type": "string"}},
        "required": ["Score", "Tier"],
    }
    entry = _node("trigger.table_record", _pin(leads))
    analyse = _node("agent.run", {"agent": analyst, "structured_output_schema": schema})
    record_update = _node("table.record.update", _pin(leads))
    notify = _node(
        "notification.send",
        {"recipients": [str(world.owner.id)], "subject": "Lead scored", "channels": ["in_app"]},
    )
    output = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, analyse, record_update, notify, output),
        edges=tuple(_chain(entry, analyse, record_update, notify, output)),
        bindings=(
            _bind(analyse, "prompt", entry, "fields", "Email"),
            _bind(record_update, "record_id", entry, "record_id"),
            _bind(record_update, "values", analyse, "structured"),
            _bind(notify, "message", entry, "fields", "Email"),
            _bind(output, "structured", record_update, "fields"),
        ),
    )
    # Publishing is what subscribes it to the table's new records.
    workflow_id = await world.workflow(graph, "Score new leads")
    async with world.factory() as db:
        trigger_id = (
            await db.execute(
                select(VirtualTableTrigger.id).where(VirtualTableTrigger.workflow_id == workflow_id)
            )
        ).scalar_one()
    return _LeadPipeline(
        leads=leads, graph=graph, update=record_update, analyse=analyse, trigger_id=trigger_id
    )


@asynccontextmanager
async def _api(world: _World, redis: MagicMock) -> AsyncIterator[AsyncClient]:
    async def session() -> AsyncGenerator[AsyncSession, None]:
        async with world.factory() as opened:
            try:
                yield opened
                await opened.commit()
            except BaseException:
                await opened.rollback()
                raise

    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_auth_context] = lambda: world.ctx
    app.dependency_overrides[deps.get_redis] = lambda: redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def _post_lead(world: _World, pipeline: _LeadPipeline, redis: MagicMock) -> uuid.UUID:
    email = next(column.id for column in pipeline.leads.columns if column.label == "Email")
    async with _api(world, redis) as client:
        created = await client.post(
            f"{settings.API_V1_STR}/tables/{pipeline.leads.id}/records",
            json={"values": {str(email): "ada@example.com"}},
        )
    assert created.status_code == 201, created.text
    return uuid.UUID(created.json()["id"])


async def _fire(world: _World) -> uuid.UUID:
    async with world.factory() as db:
        ((run_id, _entry),) = await TableTriggerConsumer(db).consume()
        await db.commit()
    return run_id


async def _lead(world: _World, record_id: uuid.UUID) -> VirtualTableRecord:
    async with world.factory() as db:
        return (
            await db.execute(select(VirtualTableRecord).where(VirtualTableRecord.id == record_id))
        ).scalar_one()


async def _updates(world: _World, record_id: uuid.UUID) -> int:
    async with world.factory() as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(VirtualTableRecordHistory)
                .where(
                    VirtualTableRecordHistory.record_id == record_id,
                    VirtualTableRecordHistory.operation == "update",
                )
            )
            or 0
        )


async def _told(world: _World) -> list[uuid.UUID]:
    """Who the workflow's own notification step told - not the run's outcome notices."""
    async with world.factory() as db:
        rows = await db.execute(
            select(Notification.recipient_user_id).where(
                Notification.event_type == NotificationEventType.WORKFLOW_NOTIFICATION.value
            )
        )
        return list(rows.scalars())


def _cell(record: VirtualTableRecord, table: TableRead, label: str) -> Any:
    column = next(item.id for item in table.columns if item.label == label)
    return record.values.get(str(column))


async def test_a_lead_added_over_the_api_is_scored_written_back_and_announced(
    world: _World, agents, mock_redis: MagicMock
):
    recorder = agents({"You score leads.": {"Score": 91, "Tier": "hot"}})
    pipeline = await _lead_pipeline(world)

    record_id = await _post_lead(world, pipeline, mock_redis)
    run_id = await _fire(world)
    run = await drive(await world.seeded(run_id, pipeline.graph))

    assert run.status == WorkflowRunStatus.SUCCEEDED.value, run.error
    assert run.triggered_by == WorkflowRunTrigger.TABLE_CREATED.value
    assert recorder.prompts["You score leads."] == ["ada@example.com"]
    lead = await _lead(world, record_id)
    assert (lead.revision, _cell(lead, pipeline.leads, "Score")) == (2, 91)
    assert _cell(lead, pipeline.leads, "Tier") == "hot"
    assert await _told(world) == [world.owner.id]
    # Writing the score back is an update, and an update starts no trigger.
    async with world.factory() as db:
        assert await TableTriggerConsumer(db).consume() == []


# Journey 4: multi-file foreach -> conversion -> agent -> Python -> upsert -> report


def _csv(batch: str, amounts: list[int]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["batch", "amount"])
    writer.writerows([batch, amount] for amount in amounts)
    return out.getvalue().encode()


async def _store_file(
    world: _World, run_id: uuid.UUID, storage: LocalFileStorage, data: bytes
) -> FileRef:
    """A CSV stored as one of the run's own files."""
    file_id = uuid.uuid4()
    path = f"workflow-files/{world.org.id}/{run_id}/{file_id}"
    await storage.save_at(path, data)
    ref = FileRef(file_id=file_id, content_type="text/csv", byte_size=len(data))
    async with world.factory() as db:
        db.add(
            WorkflowFile(
                id=file_id,
                organization_id=world.org.id,
                workflow_run_id=run_id,
                storage_path=path,
                content_type="text/csv",
                byte_size=len(data),
                filename=f"{file_id}.csv",
            )
        )
        await db.commit()
    return ref


async def test_each_uploaded_file_is_converted_summarised_totalled_and_filed_into_a_report(
    world: _World, agents, tmp_path
):
    agents({"You summarise a batch.": "Batch looks healthy."})
    storage = LocalFileStorage(str(tmp_path))
    batches = await world.table("Batches", ("Name", "text"), ("Total", "integer"))
    writer = await world.agent("You summarise a batch.")
    entry, loop, item = _node("core.input"), _node("control.foreach"), _node("loop.item")
    convert = _node("convert.csv_to_json")
    read = _node("file.read", {"parse_as": "json"})
    shape = _node(
        "data.map", {"mappings": [{"target_field": "rows", "source_path": "source.json_value"}]}
    )
    total = _node(
        "code.python.simple",
        {
            "code": (
                "rows = args['rows']\n"
                "name = rows[0]['batch']\n"
                "amount = 0\n"
                "for row in rows:\n"
                "    amount = amount + int(row['amount'])\n"
                "{'name': name, 'values': {'Name': name, 'Total': amount},"
                " 'prompt': name + ': ' + str(len(rows)) + ' orders, ' + str(amount) + ' in total'}"
            )
        },
    )
    summarise = _node("agent.run", {"agent": writer})
    upsert = _node("table.record.upsert", _pin(batches))
    collect = _node("loop.yield")
    report = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, loop, item, convert, read, shape, total, summarise, upsert, collect, report),
        edges=(
            _edge(entry, loop),
            _edge(loop, item, "body"),
            *_chain(item, convert, read, shape, total, summarise, upsert, collect),
            _edge(loop, report, "done"),
        ),
        bindings=(
            _bind(loop, "items", entry, "payload", "files"),
            _bind(convert, "file", item, "item"),
            _bind(read, "file", convert, "file"),
            _bind(shape, "source", read),
            _bind(total, "args", shape, "values"),
            _bind(summarise, "prompt", total, "result", "prompt"),
            _bind(upsert, "external_id", total, "result", "name"),
            _bind(upsert, "values", total, "result", "values"),
            _bind(collect, "value", summarise, "text"),
            _bind(report, "structured", loop, port="done"),
        ),
    )
    workflow_id = await world.workflow(graph, "Batch report")

    with (
        patch("app.workflows.files.get_file_storage", return_value=storage),
        patch("app.services.file_storage.get_file_storage", return_value=storage),
    ):
        # Nothing uploads into a run from outside yet, so the CSVs are stored as
        # the run's own files - the way `files.save` stores what a step made -
        # and named in its input before its first step is dispatched.
        run_id = await world.start(workflow_id, run_input={"files": []})
        files = [
            await _store_file(world, run_id, storage, _csv("north", [10, 20, 30])),
            await _store_file(world, run_id, storage, _csv("south", [5, 5])),
        ]
        async with world.factory() as db:
            await db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run_id)
                .values(input={"files": [ref.model_dump(mode="json") for ref in files]})
            )
            await db.commit()
        run = await drive(await world.seeded(run_id, graph))

    assert run.status == WorkflowRunStatus.SUCCEEDED.value, run.error
    assert run.output is not None
    assert run.output["structured"]["results"] == ["Batch looks healthy."] * 2
    assert run.output["structured"]["errors"] == []
    async with world.factory() as db:
        rows = (await db.execute(select(VirtualTableRecord))).scalars().all()
    totals = {row.external_id: _cell(row, batches, "Total") for row in rows}
    assert totals == {"north": 60, "south": 10}


# Breaking a journey on purpose


async def _next_pending(seeded: SeededRun) -> tuple[uuid.UUID, uuid.UUID] | None:
    """The next due node run and the graph node it runs, or None when none is due."""
    async with seeded.factory() as db:
        row = (
            await db.execute(
                select(DispatchOutbox.node_run_id, NodeRun.node_instance_id)
                .join(NodeRun, NodeRun.id == DispatchOutbox.node_run_id)
                .where(
                    DispatchOutbox.workflow_run_id == seeded.run.id,
                    DispatchOutbox.status == DispatchOutboxStatus.PENDING.value,
                    DispatchOutbox.available_at <= func.now(),
                )
                .order_by(DispatchOutbox.created_at)
                .limit(1)
            )
        ).first()
    return None if row is None else (row[0], row[1])


async def _drive_until(seeded: SeededRun, node: NodeInstance) -> uuid.UUID:
    """Tick every node before `node`, and return `node`'s node run, due now."""
    for _ in range(50):
        pending = await _next_pending(seeded)
        assert pending is not None, "the run ended before reaching the node"
        node_run_id, instance = pending
        if instance == node.id:
            return node_run_id
        await tick(seeded, node_run_id)
    raise AssertionError("the node never came due")


async def _die_after_the_effect(seeded: SeededRun, node_run_id: uuid.UUID) -> None:
    """A worker that ran the step's handler - its effect is done - and died
    before saving the result, with a lease that has already run out."""
    async with seeded.factory() as db:
        claim = await dispatcher.claim(db, node_run_id=node_run_id, lease_seconds=0)
        await db.commit()
    assert claim is not None and claim.claimed_by is not None
    async with seeded.factory() as db:
        begun = await dispatcher.begin_attempt(
            db, workflow_run_id=seeded.run.id, node_run_id=node_run_id, token=claim.claimed_by
        )
        await db.commit()
    assert begun is not None
    await dispatcher.call_handler(begun)


async def _reconcile(seeded: SeededRun) -> None:
    """What the reconcile heartbeat does once the lease is gone, then make its retry due."""
    async with seeded.factory() as db:
        assert await WorkflowReconcilerService(db).resolve_orphaned_attempts() == 1
        await db.commit()
    async with seeded.factory() as db:
        await db.execute(
            update(DispatchOutbox)
            .where(
                DispatchOutbox.workflow_run_id == seeded.run.id,
                DispatchOutbox.status == DispatchOutboxStatus.PENDING.value,
            )
            .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()


async def test_a_worker_dying_after_the_write_back_replays_it_instead_of_writing_twice(
    world: _World, agents, mock_redis: MagicMock
):
    agents({"You score leads.": {"Score": 91, "Tier": "hot"}})
    pipeline = await _lead_pipeline(world)
    record_id = await _post_lead(world, pipeline, mock_redis)
    seeded = await world.seeded(await _fire(world), pipeline.graph)

    node_run_id = await _drive_until(seeded, pipeline.update)
    await _die_after_the_effect(seeded, node_run_id)
    assert (await _lead(world, record_id)).revision == 2
    await _reconcile(seeded)
    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value, run.error
    # One update, not two: the retried step found its first write's receipt.
    assert (await _lead(world, record_id)).revision == 2
    assert await _updates(world, record_id) == 1
    assert await _told(world) == [world.owner.id]


async def test_a_worker_dying_inside_a_model_call_asks_a_person_rather_than_paying_twice(
    world: _World, agents, mock_redis: MagicMock
):
    """`agent.run` promises nothing about a retry, so an attempt nobody saw end
    is not run again on its own: the run waits for someone to decide."""
    recorder = agents({"You score leads.": {"Score": 91, "Tier": "hot"}})
    pipeline = await _lead_pipeline(world)
    record_id = await _post_lead(world, pipeline, mock_redis)
    seeded = await world.seeded(await _fire(world), pipeline.graph)

    node_run_id = await _drive_until(seeded, pipeline.analyse)
    await _die_after_the_effect(seeded, node_run_id)
    async with seeded.factory() as db:
        assert await WorkflowReconcilerService(db).resolve_orphaned_attempts() == 1
        await db.commit()
    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.NEEDS_ATTENTION.value
    assert recorder.calls == 1
    assert (await _lead(world, record_id)).revision == 1


@pytest.mark.security
async def test_a_member_who_loses_access_halfway_stops_the_journey_before_the_write(
    world: _World, agents, mock_redis: MagicMock
):
    agents({"You score leads.": {"Score": 91, "Tier": "hot"}})
    pipeline = await _lead_pipeline(world)
    record_id = await _post_lead(world, pipeline, mock_redis)
    seeded = await world.seeded(await _fire(world), pipeline.graph)

    await _drive_until(seeded, pipeline.update)
    async with world.factory() as db:
        await db.execute(
            update(OrganizationMember)
            .where(OrganizationMember.user_id == world.owner.id)
            .values(role="viewer")
        )
        await db.commit()
    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "PRINCIPAL_REVOKED"
    assert (await _lead(world, record_id)).revision == 1
    assert await _told(world) == []
    assert json.dumps(run.error or {}).find("ada@example.com") == -1
