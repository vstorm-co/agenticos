"""The 0154 revision, exercised on datasets with history in them.

`tests/test_migrations.py` runs the whole chain forwards and back on an empty
database, where no version holds anything to rebuild. This writes datasets
through the service - adds, an import, an edit, removals, a dataset emptied and
one never filled - then downgrades to the membership table and upgrades again,
and asserts every version reads the same revisions, in the same order and with
the same counts, at each step. It then corrupts the membership in the ways no
version of the code writes and asserts the upgrade stops, naming where.

It owns a database of its own - created here, dropped when the module is done -
for the reason `test_migrations.py` does.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import dataset_repo
from app.schemas.dataset import DatasetCaseCreate, DatasetCaseUpdate, DatasetCreate
from app.services.dataset import DatasetService

pytestmark = pytest.mark.anyio

MIGRATION_DATABASE = f"agenticos_dataset_spans_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_REVISION = "0154_dataset_version_spans"
_CSV = b"input,reference_answer,tags\nImported?,Yes,import\nAlso imported?,No,import\n"

# A version as a reader sees it: its revisions in order, and what scoring counts.
Snapshot = dict[str, Any]


def _url(database: str, *, sync: bool = True) -> str:
    base = settings.DATABASE_URL_SYNC if sync else settings.DATABASE_URL
    return f"{base.rsplit('/', 1)[0]}/{database}"


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        cwd=".",
        env={**os.environ, "POSTGRES_DB": MIGRATION_DATABASE},
        timeout=120,
    )


def _migrate(*args: str) -> None:
    result = _alembic(*args)
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stderr}"


def _outside_a_transaction(url: str, statement: str) -> None:
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(statement)
    finally:
        engine.dispose()


def _server_reachable(url: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect():
            return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module", autouse=True)
def migration_database() -> Iterator[None]:
    maintenance = _url(_MAINTENANCE_DATABASE)
    if not _server_reachable(maintenance):
        if os.getenv("CI"):
            raise RuntimeError(
                f"No database reachable at {maintenance} but CI is set - refusing to skip."
            )
        pytest.skip("No database reachable - start one with `make docker-db`")

    drop = f'DROP DATABASE IF EXISTS "{MIGRATION_DATABASE}" WITH (FORCE)'
    _outside_a_transaction(maintenance, drop)
    _outside_a_transaction(maintenance, f'CREATE DATABASE "{MIGRATION_DATABASE}"')
    try:
        yield
    finally:
        _outside_a_transaction(maintenance, drop)


@asynccontextmanager
async def _session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(_url(MIGRATION_DATABASE, sync=False))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


async def _owner(db: AsyncSession) -> AuthContext:
    person = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", is_active=True)
    db.add(person)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=person.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=org.id, user_id=person.id, role=OrgRoleName.OWNER.value
        )
    )
    await db.flush()
    return AuthContext(user_id=person.id, organization_id=org.id, role=OrgRoleName.OWNER.value)


def _case(question: str, **fields: Any) -> DatasetCaseCreate:
    return DatasetCaseCreate(input=question, **{"reference_answer": "An answer.", **fields})


async def _seed() -> uuid.UUID:
    """An organization whose datasets hold every shape of history; its id."""
    async with _session() as db:
        ctx = await _owner(db)
        service = DatasetService(db)
        busy = await service.create(ctx, DatasetCreate(name="busy"))
        await service.add_case(ctx, busy.id, _case("One?", tags=["refunds"]))
        await service.add_case(
            ctx,
            busy.id,
            _case("Two?", checks=[{"type": "contains", "value": "30 days"}]),
        )
        await service.add_case(ctx, busy.id, _case("Three?", counter_example="Never."))
        await service.import_cases(ctx, busy.id, content=_CSV, filename="more.csv", fmt="csv")
        held = (await service.list_cases(ctx, busy.id)).items
        await service.update_case(ctx, busy.id, held[1].case_id, DatasetCaseUpdate(input="Two!"))
        await service.remove_case(ctx, busy.id, held[0].case_id)
        await service.add_case(ctx, busy.id, _case("Four?", tags=["refunds"]))

        emptied = await service.create(ctx, DatasetCreate(name="emptied"))
        await service.add_case(ctx, emptied.id, _case("Gone?"))
        gone = (await service.list_cases(ctx, emptied.id)).items[0]
        await service.remove_case(ctx, emptied.id, gone.case_id)
        await service.create(ctx, DatasetCreate(name="never filled"))
        await db.commit()
        return ctx.organization_id


def _summary(rows: list[Any]) -> Snapshot:
    """What a version holds, in order, and the counts the dataset page shows for it."""
    tags: Counter[str] = Counter(tag for row in rows for tag in row.tags)
    return {
        "revisions": [(row.id, row.position) for row in rows],
        "with_reference": sum(1 for row in rows if row.reference_answer),
        "with_counter_example": sum(1 for row in rows if row.counter_example),
        "with_checks": sum(1 for row in rows if row.checks),
        "by_source": Counter(row.source for row in rows),
        "tags": tags,
    }


async def _read_through_the_repository(organization_id: uuid.UUID) -> dict[uuid.UUID, Snapshot]:
    async with _session() as db:
        versions = (
            await db.execute(
                text(
                    "SELECT id, dataset_id, number, case_count FROM dataset_versions "
                    "WHERE organization_id = :org"
                ),
                {"org": organization_id},
            )
        ).all()
        read: dict[uuid.UUID, Snapshot] = {}
        for version in versions:
            cases = await dataset_repo.list_cases(
                db, version.id, organization_id=organization_id, limit=None
            )
            assert len(cases) == version.case_count
            read[version.id] = _summary(cases)
        latest = await dataset_repo.case_stats(
            db, sorted({v.dataset_id for v in versions}), organization_id=organization_id
        )
        newest = {v.dataset_id: v.id for v in sorted(versions, key=lambda v: v.number)}
        for dataset_id, stats in latest.items():
            shown = read[newest[dataset_id]]
            assert stats.with_reference == shown["with_reference"]
            assert stats.with_counter_example == shown["with_counter_example"]
            assert stats.with_checks == shown["with_checks"]
            assert {k: v for k, v in stats.by_source.items() if v} == dict(shown["by_source"])
        return read


def _read_the_membership_table(organization_id: uuid.UUID) -> dict[uuid.UUID, Snapshot]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT v.id AS version_id, c.id, vc.position, c.reference_answer, "
                    "c.counter_example, c.checks, c.source, c.tags "
                    "FROM dataset_versions v "
                    "JOIN dataset_version_cases vc ON vc.version_id = v.id "
                    "JOIN dataset_cases c ON c.id = vc.case_revision_id "
                    "WHERE v.organization_id = :org ORDER BY v.id, vc.position"
                ),
                {"org": organization_id},
            ).all()
            versions = conn.execute(
                text("SELECT id FROM dataset_versions WHERE organization_id = :org"),
                {"org": organization_id},
            ).scalars()
            held: dict[uuid.UUID, list[Any]] = {version: [] for version in versions}
    finally:
        engine.dispose()
    for row in rows:
        held[row.version_id].append(row)
    return {version: _summary(cases) for version, cases in held.items()}


def _sql(statement: str, **params: Any) -> None:
    engine = create_engine(_url(MIGRATION_DATABASE), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(statement), params)
    finally:
        engine.dispose()


async def test_every_version_reads_the_same_through_a_downgrade_and_an_upgrade() -> None:
    _migrate("upgrade", _REVISION)
    organization_id = await _seed()
    before = await _read_through_the_repository(organization_id)
    assert len(before) == 9
    assert [len(snapshot["revisions"]) for snapshot in before.values()].count(0) == 1

    _migrate("downgrade", "-1")
    assert _read_the_membership_table(organization_id) == before

    _migrate("upgrade", _REVISION)
    assert await _read_through_the_repository(organization_id) == before


async def _corruptible() -> tuple[uuid.UUID, uuid.UUID, list[uuid.UUID]]:
    """A dataset of two revisions over three versions, downgraded: its id, a revision, versions."""
    _migrate("upgrade", _REVISION)
    async with _session() as db:
        ctx = await _owner(db)
        service = DatasetService(db)
        dataset = await service.create(ctx, DatasetCreate(name="to corrupt"))
        for question in ("One?", "Two?", "Three?"):
            await service.add_case(ctx, dataset.id, _case(question))
        first = (await service.list_cases(ctx, dataset.id)).items[0]
        await db.commit()
    _migrate("downgrade", "-1")
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            versions = list(
                conn.execute(
                    text("SELECT id FROM dataset_versions WHERE dataset_id = :d ORDER BY number"),
                    {"d": dataset.id},
                ).scalars()
            )
    finally:
        engine.dispose()
    return dataset.id, first.id, versions


@pytest.mark.parametrize(
    ("corruption", "says"),
    [
        (
            "DELETE FROM dataset_version_cases WHERE case_revision_id = :revision",
            "is held by no version",
        ),
        (
            "DELETE FROM dataset_version_cases "
            "WHERE case_revision_id = :revision AND version_id = :middle",
            "with gaps",
        ),
        (
            "UPDATE dataset_version_cases SET position = 7 "
            "WHERE case_revision_id = :revision AND version_id = :last",
            "sits at positions 0 to 7",
        ),
    ],
)
async def test_an_upgrade_stops_on_membership_the_code_never_writes(
    corruption: str, says: str
) -> None:
    dataset_id, revision_id, versions = await _corruptible()
    _sql(corruption, revision=revision_id, middle=versions[1], last=versions[2])

    refused = _alembic("upgrade", _REVISION)

    assert refused.returncode != 0
    assert says in refused.stderr
    assert f"Case revision {revision_id} of dataset {dataset_id}" in refused.stderr
    _sql("DELETE FROM datasets WHERE id = :d", d=dataset_id)
    _migrate("upgrade", _REVISION)


async def test_an_upgrade_stops_on_a_revision_held_by_another_dataset() -> None:
    dataset_id, revision_id, _ = await _corruptible()
    other_id, _, other_versions = await _corruptible()
    _sql(
        "INSERT INTO dataset_version_cases (version_id, case_revision_id, position) "
        "VALUES (:version, :revision, 9)",
        version=other_versions[0],
        revision=revision_id,
    )

    refused = _alembic("upgrade", _REVISION)

    assert refused.returncode != 0
    assert "is held by another dataset's version" in refused.stderr
    assert str(dataset_id) in refused.stderr
    _sql("DELETE FROM datasets WHERE id IN (:a, :b)", a=dataset_id, b=other_id)
    _migrate("upgrade", _REVISION)
