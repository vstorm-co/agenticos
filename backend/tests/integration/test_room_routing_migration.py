"""Native PostgreSQL rehearsal of the additive room handoff revision.

The upgrade test commits to the disposable integration database, because 0341
builds its scope key concurrently. Existing
submission bytes survive the upgrade, and used review evidence blocks rollback.
"""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.db.base import Base
from app.schemas.room_routing import RoomLeadPolicyWrite
from app.schemas.room_submission import RoomMessageCreate
from app.services.room_routing import RoomRoutingService
from app.services.room_submission import RoomSubmissionService
from tests.integration.test_room_routing import acceptance, planning
from tests.integration.test_room_routing import room as room

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_PATH = Path(__file__).parents[2] / "alembic" / "versions" / "0341_room_task_handoffs.py"
_SPEC = importlib.util.spec_from_file_location("room_handoff_migration", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MIGRATION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MIGRATION)
_TABLES = ("room_submissions", "room_lead_policies", "room_routing_proposals", "room_task_links")


def migrate(connection, direction):
    ctx = MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
    with ctx.begin_transaction(), Operations.context(ctx):
        getattr(_MIGRATION, direction)()


async def step(connection, direction):
    # 0341 builds its scope key CONCURRENTLY and validates its CHECK after commit,
    # neither of which can run inside the fixture's open transaction. Commit first,
    # so Alembic owns the transaction its autocommit_block commits.
    await connection.commit()
    await connection.run_sync(lambda sync: migrate(sync, direction))


def schema(connection):
    inspector = inspect(connection)
    result = {}
    for table in _TABLES:
        columns = [
            (column["name"], str(column["type"]), column["nullable"], column["default"])
            for column in inspector.get_columns(table)
        ]
        result[table] = {
            "columns": sorted(columns),
            "primary_key": inspector.get_pk_constraint(table),
            "unique": sorted(
                inspector.get_unique_constraints(table), key=lambda value: value["name"]
            ),
            "foreign_keys": sorted(
                inspector.get_foreign_keys(table), key=lambda value: value["name"]
            ),
            "checks": sorted(
                inspector.get_check_constraints(table), key=lambda value: value["name"]
            ),
            "indexes": sorted(inspector.get_indexes(table), key=lambda value: value["name"]),
        }
    return result


async def test_upgrade_preserves_legacy_submission_bytes_and_matches_the_model_schema(db, room):
    posted = await RoomSubmissionService(db).post(
        room.ctx,
        room.conversation.id,
        RoomMessageCreate(client_message_id="before-handoffs", content="An ordinary human post"),
        room.user,
    )
    query = text(
        "SELECT to_jsonb(s) - 'intent' - 'lead_policy_revision' FROM room_submissions s WHERE message_id = :message"
    )
    before = await db.scalar(query, {"message": posted.message.id})
    connection = await db.connection()
    expected_schema = await connection.run_sync(schema)
    try:
        await step(connection, "downgrade")
        assert await db.scalar(query, {"message": posted.message.id}) == before
        await step(connection, "upgrade")
        assert await db.scalar(query, {"message": posted.message.id}) == before
        assert tuple(
            (
                await db.execute(
                    text(
                        "SELECT intent, lead_policy_revision FROM room_submissions WHERE message_id = :message"
                    ),
                    {"message": posted.message.id},
                )
            ).one()
        ) == ("message", None)
        assert await connection.run_sync(schema) == expected_schema
        # A plain legacy post does not prevent a clean rollback of an unused feature.
        await step(connection, "downgrade")
        assert await db.scalar(query, {"message": posted.message.id}) == before
    finally:
        # The upgrade commits, so the shared test database must get its tables back.
        if not await connection.run_sync(
            lambda sync: inspect(sync).has_table("room_lead_policies")
        ):
            await step(connection, "upgrade")


@pytest.mark.parametrize("evidence", ["policy", "request", "proposal", "accepted_orphan"])
async def test_downgrade_refuses_to_erase_policy_requests_or_review_provenance(db, room, evidence):
    service = RoomRoutingService(db)
    if evidence in {"policy", "request"}:
        await service.update_policy(
            room.ctx,
            room.conversation.id,
            RoomLeadPolicyWrite(expected_revision=0, enabled=True, lead_agent_id=room.agent.id),
        )
        if evidence == "request":
            await RoomSubmissionService(db).post(
                room.ctx,
                room.conversation.id,
                RoomMessageCreate(
                    client_message_id="kept-request",
                    content="Plan this",
                    intent="ask_lead",
                    expected_policy_revision=1,
                ),
                room.user,
            )
            await db.execute(text("DELETE FROM room_lead_policies"))
    else:
        service, _, proposal = await planning(db, room)
        if evidence == "accepted_orphan":
            await service.accept(room.ctx, room.conversation.id, proposal.id, acceptance(proposal))
            await db.delete(room.conversation)
            await db.flush()
        else:
            await db.execute(text("DELETE FROM room_lead_policies"))
    connection = await db.connection()
    before = await connection.run_sync(schema)
    with pytest.raises(RuntimeError, match="handoff evidence"):
        await connection.run_sync(lambda sync: migrate(sync, "downgrade"))
    assert await connection.run_sync(schema) == before
