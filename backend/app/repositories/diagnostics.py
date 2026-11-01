"""Atomic identity creation and aggregate-only diagnostics queries."""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.agent_run import AgentRun
from app.db.models.background_job import BackgroundJob
from app.db.models.background_worker import BackgroundWorker
from app.db.models.diagnostics import DiagnosticsIdentity
from app.db.models.project import Project
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.models.skill import Skill
from app.schemas.diagnostics import Component, ErrorCode, Feature


async def get(db: AsyncSession, *, lock: bool = False) -> DiagnosticsIdentity | None:
    stmt = select(DiagnosticsIdentity).where(DiagnosticsIdentity.id == 1)
    if lock:
        stmt = stmt.with_for_update(skip_locked=True)
    return (await db.execute(stmt)).scalar_one_or_none()


async def initialize(
    db: AsyncSession, *, sealed_seed: str, key_version: int
) -> DiagnosticsIdentity:
    await db.execute(
        insert(DiagnosticsIdentity)
        .values(id=1, sealed_seed=sealed_seed, secret_key_version=key_version)
        .on_conflict_do_nothing(index_elements=[DiagnosticsIdentity.id])
    )
    await db.flush()
    return (await db.execute(select(DiagnosticsIdentity))).scalar_one()


async def save(db: AsyncSession, *, row: DiagnosticsIdentity) -> None:
    await db.flush()
    await db.refresh(row)


async def feature_counts(db: AsyncSession, *, since: datetime) -> dict[Feature, int]:
    # SQL counts only: neither tool arguments nor run transcripts are read.
    result: dict[Feature, int] = {}
    run_filters: dict[Feature, ColumnElement[bool]] = {
        "chat": AgentRun.surface.in_(["web", "embed", "api"]),
        "channels": AgentRun.surface.in_(["slack", "teams", "mattermost", "telegram", "discord"]),
        "routines": AgentRun.surface == "schedule",
        "voice": AgentRun.modality == "voice",
    }
    for name, predicate in run_filters.items():
        result[name] = int(
            await db.scalar(
                select(func.count())
                .select_from(AgentRun)
                .where(AgentRun.created_at >= since, predicate)
            )
            or 0
        )
    for name, model in (("projects", Project), ("skills", Skill), ("rag", RAGDocument)):
        result[name] = int(
            await db.scalar(
                select(func.count()).select_from(model).where(model.created_at >= since)
            )
            or 0
        )
    return result


async def failures(
    db: AsyncSession, *, since: datetime, until: datetime
) -> list[tuple[Component, ErrorCode, int]]:
    result: list[tuple[Component, ErrorCode, int]] = []
    for component, code, model, at, predicate in (
        ("agents", "run_failed", AgentRun, AgentRun.ended_at, AgentRun.status == "failed"),
        (
            "worker",
            "job_failed",
            BackgroundJob,
            BackgroundJob.finished_at,
            (BackgroundJob.status == "dead") & (BackgroundJob.kind != "send-diagnostics"),
        ),
        (
            "rag",
            "ingestion_failed",
            RAGDocument,
            RAGDocument.updated_at,
            RAGDocument.status == DocumentStatus.ERROR,
        ),
    ):
        count = int(
            await db.scalar(
                select(func.count()).select_from(model).where(at >= since, at < until, predicate)
            )
            or 0
        )
        if count:
            result.append((component, code, count))
    return result


async def worker_alive(db: AsyncSession, *, now: datetime) -> bool:
    return bool(
        await db.scalar(
            select(func.count())
            .select_from(BackgroundWorker)
            .where(BackgroundWorker.heartbeat_at >= now - timedelta(minutes=2))
        )
    )
