"""Choosing a table name and creating the table take the org guards in one order.

`create_table` takes the table-storage guard and then the table-name guard. A
helper that picked a free name under the name guard and only then called
`create_table` took them the other way round, so a plain table create running
beside a private task board or a workflow template could deadlock (#273).

The test holds the storage guard as `create_table` does, waits until PostgreSQL
shows the helper blocked on it, then lets a real `create_table` go on to the name
guard. With the old order the helper already owns the name guard and PostgreSQL
aborts one side with a deadlock; with the global order the helper owns nothing the
create needs, so both finish. No timed sleep chooses the interleaving.
"""

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.background import discard_deferred
from app.core.permissions import AuthContext
from app.db.locks import LockScope, hold_subject
from app.db.models.virtual_table import VirtualTable
from app.schemas.task import BoardEnsure
from app.schemas.virtual_table import ColumnInput, TableCreate
from app.schemas.workflow import WorkflowCreate
from app.services.tasks import TaskService
from app.services.virtual_tables import VirtualTableService
from app.services.workflow_registry import WorkflowRegistryService
from tests.integration.virtual_table_support import ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio

Operation = Callable[[AsyncSession, AuthContext], Awaitable[object]]


async def _private_board(db: AsyncSession, ctx: AuthContext) -> object:
    return await TaskService(db).ensure_board(ctx, BoardEnsure(scope="private"))


async def _workflow_template(db: AsyncSession, ctx: AuthContext) -> object:
    return await WorkflowRegistryService(db).create(
        ctx, WorkflowCreate(name="Notes", template_id="markdownNotes")
    )


@pytest.mark.parametrize(
    "operation", [_private_board, _workflow_template], ids=["private-board", "workflow-template"]
)
async def test_creating_a_table_beside_a_name_picking_helper_does_not_deadlock(
    engine: AsyncEngine, operation: Operation
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as setup:
        owner = await make_user(setup)
        org = await make_org(setup, owner=owner)
        await setup.commit()
    ctx = ctx_for(owner, org)
    org_id: UUID = org.id

    helper_pids: asyncio.Queue[int] = asyncio.Queue()

    async def helper() -> None:
        async with sessions() as session:
            try:
                pid = await session.scalar(text("SELECT pg_backend_pid()"))
                assert isinstance(pid, int)
                await helper_pids.put(pid)
                await operation(session, ctx)
                await session.commit()
            finally:
                discard_deferred(session)

    async with asyncio.timeout(60), sessions() as creator:
        # What `create_table` does first; it is held to the end of this transaction.
        await hold_subject(creator, LockScope.VIRTUAL_TABLE_STORAGE_PER_ORG, org_id)

        helper_task = asyncio.create_task(helper())
        pid = await helper_pids.get()
        async with sessions() as observer:
            while True:
                waiting = await observer.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = :pid "
                        "AND locktype = 'advisory' AND classid = :scope AND NOT granted)"
                    ),
                    {"pid": pid, "scope": LockScope.VIRTUAL_TABLE_STORAGE_PER_ORG.value},
                )
                if waiting:
                    break
                assert not helper_task.done(), "The helper never waited for the storage guard"
                await asyncio.sleep(0.01)

        # The real create: storage guard again (already ours), then the name guard.
        creating = asyncio.create_task(
            VirtualTableService(creator).create_table(
                ctx,
                TableCreate(
                    name="Unrelated",
                    visibility="private",
                    columns=[ColumnInput(label="A", type="text")],
                ),
            )
        )
        try:
            await creating
            await creator.commit()
        finally:
            discard_deferred(creator)
        await helper_task

    async with sessions() as observed:
        names = set(
            await observed.scalars(
                select(VirtualTable.name).where(VirtualTable.organization_id == org_id)
            )
        )
    assert "Unrelated" in names
    assert len(names) == 2
