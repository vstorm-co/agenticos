"""Execute migration 0357 against PostgreSQL and preserve accepted receipts."""

import importlib.util
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from alembic import op
from app.db.base import Base
from app.db.models.accepted_queued_message import AcceptedQueuedMessage
from app.db.models.agent import Agent
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.conversation_task import ConversationTask
from tests.integration.test_conversation_tasks import seed

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_TABLES = (
    "accepted_queued_messages",
    "agent_runs",
    "chat_files",
    "conversation_tasks",
    "messages",
)
_PATH = Path(__file__).parents[2] / "alembic" / "versions" / "0357_accepted_queued_messages.py"
_SPEC = importlib.util.spec_from_file_location("accepted_queue_migration", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MIGRATION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MIGRATION)


def _migrate(connection: Connection, direction: Literal["upgrade", "downgrade"]) -> None:
    context = MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
    with context.begin_transaction(), Operations.context(context):
        getattr(_MIGRATION, direction)()


async def _step(connection: AsyncConnection, direction: Literal["upgrade", "downgrade"]) -> None:
    await connection.commit()
    await connection.run_sync(lambda sync: _migrate(sync, direction))


def _schema(connection: Connection) -> dict[str, dict[str, object]]:
    inspector = inspect(connection)
    return {
        table: {
            "columns": sorted(
                (item["name"], str(item["type"]), item["nullable"], item["default"])
                for item in inspector.get_columns(table)
            ),
            "primary_key": inspector.get_pk_constraint(table),
            "unique_constraints": sorted(
                inspector.get_unique_constraints(table), key=lambda item: str(item["name"])
            ),
            "foreign_keys": sorted(
                inspector.get_foreign_keys(table), key=lambda item: str(item["name"])
            ),
            "checks": sorted(
                inspector.get_check_constraints(table), key=lambda item: str(item["name"])
            ),
            "indexes": sorted(inspector.get_indexes(table), key=lambda item: str(item["name"])),
        }
        for table in _TABLES
    }


def _schema_diff(connection: Connection) -> list:
    def include_object(_object, name, object_type, _reflected, _compare_to):
        return object_type != "table" or name in _TABLES

    context = MigrationContext.configure(
        connection,
        opts={
            "target_metadata": Base.metadata,
            "include_object": include_object,
            "compare_type": True,
            "compare_server_default": True,
        },
    )
    return compare_metadata(context, Base.metadata)


def _prepare_interrupted_index_build(connection: Connection) -> None:
    """Leave the exact nullable columns and standalone concurrent indexes of phase one."""
    context = MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
    with context.begin_transaction(), Operations.context(context):
        for table, column in _MIGRATION._QUEUE_COLUMNS:
            _MIGRATION._ensure_column(table, column, add=True)
        with _MIGRATION._autocommit_ddl():
            for table, column, name in _MIGRATION._QUEUE_UNIQUE:
                _MIGRATION._ensure_index(table, column, name)


def _create_conflicting_named_index(connection: Connection) -> None:
    context = MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
    with context.begin_transaction(), Operations.context(context):
        op.create_index("uq_message_accepted_queue", "messages", ["conversation_id"], unique=True)


def _drop_interrupted_objects(connection: Connection) -> None:
    for _table, _column, name in _MIGRATION._QUEUE_UNIQUE:
        connection.exec_driver_sql(f"DROP INDEX IF EXISTS {name}")
    for table, column in _MIGRATION._QUEUE_COLUMNS:
        connection.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")


async def _restore_model_schema(connection: AsyncConnection) -> None:
    present = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
    if _TABLES[0] in present:
        return
    await connection.run_sync(_drop_interrupted_objects)
    await _step(connection, "upgrade")


def _receipt_for_seed(
    example,
    agent: Agent,
    conversation: Conversation,
    *,
    state: str = "pending",
):
    return AcceptedQueuedMessage(
        id=uuid4(),
        organization_id=example.ctx.organization_id,
        conversation_id=conversation.id,
        requester_id=example.ctx.subject_id,
        client_queue_id=uuid4(),
        agent_id=agent.id,
        payload={"content": "Queued integrity check"},
        payload_hash="a" * 64,
        state=state,
    )


async def test_accepted_queue_revision_upgrade_empty_downgrade_and_schema_parity(
    engine: AsyncEngine,
) -> None:
    async with engine.connect() as connection:
        expected = await connection.run_sync(_schema)
        try:
            await _step(connection, "downgrade")
            remaining = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
            assert _TABLES[0] not in remaining

            await _step(connection, "upgrade")
            assert await connection.run_sync(_schema) == expected
            assert await connection.run_sync(_schema_diff) == []
            await _step(connection, "upgrade")
            assert await connection.run_sync(_schema) == expected
            assert await connection.run_sync(_schema_diff) == []
            await _step(connection, "downgrade")
        finally:
            present = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
            if _TABLES[0] not in present:
                await _step(connection, "upgrade")


async def test_upgrade_reuses_exact_standalone_indexes_after_interruption(
    engine: AsyncEngine,
) -> None:
    async with engine.connect() as connection:
        expected = await connection.run_sync(_schema)
        try:
            await _step(connection, "downgrade")
            await connection.run_sync(_prepare_interrupted_index_build)

            await _step(connection, "upgrade")
            assert await connection.run_sync(_schema) == expected
            assert await connection.run_sync(_schema_diff) == []
            # A second invocation checks the committed-schema retry path too.
            await _step(connection, "upgrade")
            assert await connection.run_sync(_schema) == expected
        finally:
            await _restore_model_schema(connection)


async def test_upgrade_refuses_and_preserves_a_conflicting_named_index(
    engine: AsyncEngine,
) -> None:
    async with engine.connect() as connection:
        try:
            await _step(connection, "downgrade")
            await connection.run_sync(_create_conflicting_named_index)
            before = await connection.run_sync(
                lambda sync: next(
                    item
                    for item in inspect(sync).get_indexes("messages")
                    if item["name"] == "uq_message_accepted_queue"
                )
            )

            with pytest.raises(RuntimeError, match="uq_message_accepted_queue"):
                await _step(connection, "upgrade")

            after = await connection.run_sync(
                lambda sync: next(
                    item
                    for item in inspect(sync).get_indexes("messages")
                    if item["name"] == "uq_message_accepted_queue"
                )
            )
            assert after == before
            message_columns = await connection.run_sync(
                lambda sync: {item["name"] for item in inspect(sync).get_columns("messages")}
            )
            assert "accepted_queue_id" not in message_columns
        finally:
            await _restore_model_schema(connection)


async def test_downgrade_refuses_retained_receipt_without_changing_schema(
    db: AsyncSession,
) -> None:
    example = await seed(db)
    agent = await db.get(Agent, example.agent.id)
    conversation = await db.get(Conversation, example.topic.id)
    assert agent is not None and conversation is not None
    receipt = _receipt_for_seed(example, agent, conversation)
    db.add(receipt)
    await db.flush()

    connection = await db.connection()
    before = await connection.run_sync(_schema)
    with pytest.raises(RuntimeError, match="Cannot discard retained accepted queue"):
        await connection.run_sync(lambda sync: _migrate(sync, "downgrade"))
    assert await connection.run_sync(_schema) == before
    assert (
        await db.scalar(
            select(AcceptedQueuedMessage.id).where(AcceptedQueuedMessage.id == receipt.id)
        )
        == receipt.id
    )


async def test_accepted_queue_rejects_unknown_state(db: AsyncSession) -> None:
    example = await seed(db)
    agent = await db.get(Agent, example.agent.id)
    conversation = await db.get(Conversation, example.topic.id)
    assert agent is not None and conversation is not None
    receipt = _receipt_for_seed(example, agent, conversation, state="unknown")
    db.add(receipt)

    with pytest.raises(IntegrityError):
        await db.flush()


async def test_accepted_queue_requires_a_real_steering_run(db: AsyncSession) -> None:
    example = await seed(db)
    agent = await db.get(Agent, example.agent.id)
    conversation = await db.get(Conversation, example.topic.id)
    assert agent is not None and conversation is not None
    receipt = _receipt_for_seed(example, agent, conversation, state="steering")
    receipt.steering_run_id = uuid4()
    db.add(receipt)

    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.parametrize("provenance", ["missing", "both"])
async def test_conversation_task_requires_one_provenance_source(
    db: AsyncSession, provenance: str
) -> None:
    example = await seed(db)
    conversation = await db.get(Conversation, example.topic.id)
    assert conversation is not None
    version_id = example.source.agent_version_id
    assert version_id is not None
    queue_receipt = _receipt_for_seed(example, example.agent, conversation)
    db.add(queue_receipt)
    await db.flush()

    has_task_provenance = provenance == "both"
    task = ConversationTask(
        id=uuid4(),
        organization_id=example.ctx.organization_id,
        user_id=example.ctx.subject_id,
        source_conversation_id=conversation.id,
        conversation_id=conversation.id,
        source_run_id=example.source.id if has_task_provenance else None,
        source_agent_id=example.agent.id,
        source_version_id=version_id,
        agent_id=example.agent.id,
        version_id=version_id,
        tool_call_id="delegate-1" if has_task_provenance else None,
        queue_receipt_id=queue_receipt.id if has_task_provenance else None,
        title="Integrity check",
        prompt="This invalid provenance must be rejected.",
    )
    db.add(task)

    with pytest.raises(IntegrityError):
        await db.flush()


async def test_chat_file_cannot_be_attached_and_queue_reserved_together(
    db: AsyncSession,
) -> None:
    example = await seed(db)
    conversation = await db.get(Conversation, example.topic.id)
    assert conversation is not None
    message_id = await db.scalar(
        select(Message.id).where(Message.conversation_id == conversation.id)
    )
    assert message_id is not None
    queue_receipt = _receipt_for_seed(example, example.agent, conversation)
    db.add(queue_receipt)
    await db.flush()

    file = ChatFile(
        id=uuid4(),
        user_id=example.ctx.subject_id,
        message_id=message_id,
        queue_receipt_id=queue_receipt.id,
        filename="double-owned.txt",
        mime_type="text/plain",
        size=12,
        storage_path=f"uploads/{uuid4().hex}.txt",
        file_type="text",
    )
    db.add(file)

    with pytest.raises(IntegrityError):
        await db.flush()
