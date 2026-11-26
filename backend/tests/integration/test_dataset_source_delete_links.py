"""Conversation deletion releases copied dataset provenance in either FK trigger order."""

import importlib.util
from dataclasses import replace
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from app.core.permissions import OrgRoleName
from app.db.base import Base
from app.db.models.conversation import Conversation
from app.db.models.dataset import DatasetCase
from app.schemas.dataset import DatasetCaseFromMessage, DatasetCreate
from app.services.dataset import DatasetService
from tests.integration.test_datasets import _owner, _rated_down_turn

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_CONVERSATION_FK = "dataset_cases_source_conversation_id_fkey"
_MESSAGE_FK = "dataset_cases_source_message_id_fkey"
_MIGRATION_PATH = (
    Path(__file__).parents[2] / "alembic" / "versions" / "0358_defer_dataset_source_links.py"
)
_SPEC = importlib.util.spec_from_file_location("dataset_source_links_migration", _MIGRATION_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MIGRATION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MIGRATION)


async def _recreate_fk(db: AsyncSession, table: str, name: str) -> None:
    """Move one FK's RI triggers while preserving its full PostgreSQL definition."""
    definition = await db.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = CAST(:table AS regclass) AND conname = :name"
        ),
        {"table": table, "name": name},
    )
    assert definition is not None
    await db.execute(text(f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"'))
    # Table/constraint names are the constants above; definition is read from pg_constraint.
    await db.execute(text(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" {definition}'))


async def _force_conversation_delete_order(
    db: AsyncSession, *, source_conversation_last: bool
) -> None:
    """Install either order of message CASCADE and case SET NULL triggers."""
    message_fk = ("messages", "messages_conversation_id_fkey")
    source_fk = ("dataset_cases", "dataset_cases_source_conversation_id_fkey")
    ordered = (message_fk, source_fk) if source_conversation_last else (source_fk, message_fk)
    expected = ("c", "c", "n", "n") if source_conversation_last else ("n", "n", "c", "c")
    # OID trigger names sort lexically. Rebuild until both new OIDs share a digit
    # width and the requested order is the one PostgreSQL will actually fire.
    for _ in range(3):
        for table, name in ordered:
            await _recreate_fk(db, table, name)
        actions = tuple(
            await db.scalars(
                text(
                    "SELECT c.confdeltype::text FROM pg_trigger t "
                    "JOIN pg_constraint c ON c.oid = t.tgconstraint "
                    "WHERE t.tgrelid = 'conversations'::regclass "
                    "AND c.conname IN ('messages_conversation_id_fkey', "
                    "'dataset_cases_source_conversation_id_fkey') ORDER BY t.tgname"
                )
            )
        )
        if actions == expected:
            return
    assert actions == expected


def _migrate(connection: Connection, direction: Literal["upgrade", "downgrade"]) -> None:
    context = MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
    with context.begin_transaction(), Operations.context(context):
        getattr(_MIGRATION, direction)()


async def _step(connection: AsyncConnection, direction: Literal["upgrade", "downgrade"]) -> None:
    await connection.commit()
    await connection.run_sync(lambda sync: _migrate(sync, direction))


def _source_constraint_state(connection: Connection) -> dict[str, tuple[bool, bool, str]]:
    rows = connection.execute(
        text(
            "SELECT conname, condeferrable, condeferred, confdeltype::text AS confdeltype "
            "FROM pg_constraint WHERE conrelid = 'dataset_cases'::regclass "
            "AND conname IN ('dataset_cases_source_conversation_id_fkey', "
            "'dataset_cases_source_message_id_fkey')"
        )
    )
    return {row.conname: (row.condeferrable, row.condeferred, row.confdeltype) for row in rows}


def _dataset_case_schema_diff(connection: Connection) -> list:
    def include_object(obj, name, object_type, _reflected, _compare_to):
        if object_type == "table":
            return name == "dataset_cases"
        return getattr(getattr(obj, "table", None), "name", None) == "dataset_cases"

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


async def _case_snapshot(
    connection: AsyncConnection, case_id: UUID
) -> tuple[str, UUID | None, UUID | None, UUID | None]:
    row = await connection.execute(
        text(
            "SELECT input, source_run_id, source_conversation_id, source_message_id "
            "FROM dataset_cases WHERE case_id = :case_id AND removed_in IS NULL"
        ),
        {"case_id": case_id},
    )
    return tuple(row.one())


@pytest.mark.parametrize(
    "source_conversation_last", [False, True], ids=["set-null-first", "set-null-last"]
)
async def test_deleting_a_conversation_clears_dataset_sources_in_either_fk_order(
    db: AsyncSession, source_conversation_last: bool
) -> None:
    await _force_conversation_delete_order(db, source_conversation_last=source_conversation_last)
    owner = await _owner(db)
    viewer = replace(owner, role=OrgRoleName.VIEWER)
    service = DatasetService(db)
    dataset = await service.create(owner, DatasetCreate(name="source deletion"))
    run, answer = await _rated_down_turn(db, owner)
    copied = await service.add_from_message(
        owner, dataset.id, DatasetCaseFromMessage(message_id=answer.id)
    )
    await db.execute(delete(Conversation).where(Conversation.id == answer.conversation_id))
    await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert (
        await db.scalar(select(Conversation.id).where(Conversation.id == answer.conversation_id))
        is None
    )

    stored = await db.scalar(
        select(DatasetCase)
        .where(DatasetCase.case_id == copied.case_id, DatasetCase.removed_in.is_(None))
        .execution_options(populate_existing=True)
    )
    assert stored is not None
    assert stored.source_conversation_id is None
    assert stored.source_message_id is None
    assert stored.source_run_id == run.id
    assert stored.input == copied.input
    [read] = await service.case_reads(viewer, [stored])
    assert read.masked and read.input != stored.input


@pytest.mark.parametrize(
    ("field", "constraint"),
    (("source_conversation_id", _CONVERSATION_FK), ("source_message_id", _MESSAGE_FK)),
)
async def test_invalid_surviving_dataset_source_is_rejected_at_commit(
    db: AsyncSession, field: str, constraint: str
) -> None:
    owner = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(owner, DatasetCreate(name="invalid source"))
    _, answer = await _rated_down_turn(db, owner)
    copied = await service.add_from_message(
        owner, dataset.id, DatasetCaseFromMessage(message_id=answer.id)
    )
    stored = await db.scalar(
        select(DatasetCase).where(
            DatasetCase.case_id == copied.case_id, DatasetCase.removed_in.is_(None)
        )
    )
    assert stored is not None
    setattr(stored, field, uuid4())
    await db.flush()

    with pytest.raises(IntegrityError, match=constraint):
        await db.commit()


async def test_dataset_source_constraint_migration_preserves_rows_and_matches_models(
    scratch_engine: AsyncEngine,
) -> None:
    async with async_sessionmaker(scratch_engine, expire_on_commit=False)() as db:
        owner = await _owner(db)
        run, answer = await _rated_down_turn(db, owner)
        dataset = await DatasetService(db).create(owner, DatasetCreate(name="migration preserve"))
        copied = await DatasetService(db).add_from_message(
            owner, dataset.id, DatasetCaseFromMessage(message_id=answer.id)
        )
        case_id = copied.case_id
        await db.commit()

    async with scratch_engine.connect() as connection:
        snapshot = await _case_snapshot(connection, case_id)
        assert snapshot[1] == run.id
        assert await connection.run_sync(_source_constraint_state) == {
            _CONVERSATION_FK: (True, True, "n"),
            _MESSAGE_FK: (True, True, "n"),
        }
        await _step(connection, "downgrade")
        assert await connection.run_sync(_source_constraint_state) == {
            _CONVERSATION_FK: (False, False, "n"),
            _MESSAGE_FK: (False, False, "n"),
        }
        assert await _case_snapshot(connection, case_id) == snapshot

        await _step(connection, "upgrade")
        await _step(connection, "upgrade")
        assert await connection.run_sync(_source_constraint_state) == {
            _CONVERSATION_FK: (True, True, "n"),
            _MESSAGE_FK: (True, True, "n"),
        }
        assert await connection.run_sync(_dataset_case_schema_diff) == []
        assert await _case_snapshot(connection, case_id) == snapshot
