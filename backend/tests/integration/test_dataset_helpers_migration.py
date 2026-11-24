"""Upgrade legacy dataset grading and queued generations without losing their prompts."""

import runpy
from pathlib import Path
from typing import Literal

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import case_generation_repo
from app.services.system_agents import SystemAgentService
from tests.integration.test_case_generation_runs import _request, _service, _setup

pytestmark = pytest.mark.anyio
_REVISIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _apply(connection: Connection, name: str, direction: Literal["upgrade", "downgrade"]) -> None:
    namespace: dict[str, object] = runpy.run_path(str(_REVISIONS / name))
    operation = namespace[direction]
    if not callable(operation):
        raise TypeError("A migration must expose upgrade and downgrade functions")
    with Operations.context(MigrationContext.configure(connection)):
        operation()


async def test_legacy_grading_and_queued_generator_keep_the_published_model_and_prompt(
    db: AsyncSession,
) -> None:
    owner, org, agent, dataset, _ = await _setup(db)
    judge = await SystemAgentService(db).ensure(organization_id=org.id, key="eval_judge")
    generator = await SystemAgentService(db).ensure(organization_id=org.id, key="case_generator")
    started = await _service(db).start(owner, dataset.id, _request(agent, "agent"))
    generation = await case_generation_repo.get_generation(db, started.id, organization_id=org.id)
    assert generation is not None
    generation.generator_agent_id = generator.id
    await db.execute(
        text(
            "UPDATE datasets SET scoring = jsonb_build_object('judge', jsonb_build_object('agent_id', CAST(:judge AS text))) WHERE id = :dataset"
        ),
        {"judge": str(judge.id), "dataset": dataset.id},
    )
    await db.flush()
    for name in ["0253_freeze_dataset_helper_settings.py", "0252_dataset_helper_configuration.py"]:
        await db.run_sync(
            lambda session, name=name: _apply(session.connection(), name, "downgrade")
        )
    for name in ["0252_dataset_helper_configuration.py", "0253_freeze_dataset_helper_settings.py"]:
        await db.run_sync(lambda session, name=name: _apply(session.connection(), name, "upgrade"))
    judge_settings = await db.scalar(
        text("SELECT scoring->'judge' FROM datasets WHERE id=:id"), {"id": dataset.id}
    )
    judge_spec = await db.scalar(
        text("SELECT spec FROM agent_versions WHERE id=:id"), {"id": judge.current_version_id}
    )
    generator_settings = await db.scalar(
        text("SELECT helper_settings FROM case_generations WHERE id=:id"), {"id": generation.id}
    )
    generator_spec = await db.scalar(
        text("SELECT spec FROM agent_versions WHERE id=:id"), {"id": generator.current_version_id}
    )
    assert judge_settings["model_profile_id"] == judge_spec["model_profile_id"]
    assert judge_settings["instructions"] == judge_spec["instructions"]
    assert generator_settings["model_profile_id"] == generator_spec["model_profile_id"]
    assert generator_settings["instructions"] == generator_spec["instructions"]
    columns = set(
        (
            await db.scalars(
                text(
                    "SELECT table_name FROM information_schema.columns WHERE column_name = 'helper_settings'"
                )
            )
        ).all()
    )
    assert {"datasets", "case_generations", "improvement_runs", "authoring_requests"} <= columns
