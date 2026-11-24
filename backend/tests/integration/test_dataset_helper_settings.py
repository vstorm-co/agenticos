"""Dataset pipeline configuration stays scoped and frozen for queued work."""

import asyncio
from typing import Literal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import OrgRoleName
from app.repositories import case_generation_repo
from app.schemas.dataset import DatasetUpdate
from app.schemas.dataset_helpers import DatasetHelper, DatasetHelpers
from app.services.case_generation import worker
from app.services.case_generation.worker import CaseGenerationWorker
from app.services.dataset import DatasetService
from app.services.system_agent_runner import SystemAgentRunner
from tests.integration import case_generation_world as world
from tests.integration.test_case_generation_runs import _profile, _request, _service, _setup

pytestmark = pytest.mark.anyio


async def test_generation_uses_the_admitted_model_and_instructions_after_settings_change(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, org, agent, dataset, _ = await _setup(db)
    first = await _profile(db, org)
    second = await _profile(db, org)
    datasets = DatasetService(db)
    await datasets.update(
        owner,
        dataset.id,
        DatasetUpdate(
            helper_settings=DatasetHelpers(
                generator=DatasetHelper(
                    model_profile_id=first.id, instructions="Use policy examples."
                ),
            )
        ),
    )
    runnable = AsyncMock()
    monkeypatch.setattr(SystemAgentRunner, "require_runnable", runnable)
    started = await _service(db).start(owner, dataset.id, _request(agent, "agent"))
    assert runnable.call_args.kwargs["model_profile_id"] == first.id
    await datasets.update(
        owner,
        dataset.id,
        DatasetUpdate(
            helper_settings=DatasetHelpers(
                generator=DatasetHelper(
                    model_profile_id=second.id, instructions="Changed for future runs."
                ),
            )
        ),
    )
    execute = AsyncMock()
    monkeypatch.setattr(worker, "generate", execute)
    task = CaseGenerationWorker(started.id, org.id, vector_store=_service(db).sources.vector_store)
    await task._run(db)
    assert execute.await_count == 1
    assert execute.call_args.kwargs["helper_settings"] == DatasetHelper(
        model_profile_id=first.id, instructions="Use policy examples."
    )
    row = await case_generation_repo.get_generation(db, started.id, organization_id=org.id)
    assert row is not None and row.helper_settings["model_profile_id"] == str(first.id)


@pytest.mark.security
async def test_dataset_helpers_refuse_a_model_from_another_tenant(db: AsyncSession) -> None:
    owner, _, _, dataset, _ = await _setup(db)
    other_person = await world.user(db)
    other_org = await world.org(db, other_person)
    foreign = await _profile(db, other_org)
    with pytest.raises(BadRequestError):
        await DatasetService(db).update(
            owner,
            dataset.id,
            DatasetUpdate(
                helper_settings=DatasetHelpers(
                    improver=DatasetHelper(model_profile_id=foreign.id),
                )
            ),
        )


async def test_readers_cannot_change_pipeline_instructions(db: AsyncSession) -> None:
    _, org, _, dataset, _ = await _setup(db)
    viewer = await world.member(db, org, OrgRoleName.VIEWER)
    with pytest.raises((AuthorizationError, BadRequestError, NotFoundError)):
        await DatasetService(db).update(
            viewer,
            dataset.id,
            DatasetUpdate(
                helper_settings=DatasetHelpers(
                    generator=DatasetHelper(instructions="Replace the instructions."),
                )
            ),
        )


@pytest.mark.parametrize("kind", ["generator", "improver"])
async def test_pipeline_settings_refuse_an_embedding_only_model(
    db: AsyncSession, kind: str
) -> None:
    owner, org, _, dataset, _ = await _setup(db)
    model = await _profile(db, org)
    model.provider = "openai"
    model.model = "text-embedding-3-small"
    await db.flush()
    helper = DatasetHelper(model_profile_id=model.id)
    config = (
        DatasetHelpers(generator=helper) if kind == "generator" else DatasetHelpers(improver=helper)
    )
    with pytest.raises(BadRequestError) as refused:
        await DatasetService(db).update(owner, dataset.id, DatasetUpdate(helper_settings=config))
    assert refused.value.details["fields"][0]["field"] == f"helper_settings.{kind}.model_profile_id"


async def test_two_helper_forms_saving_stale_copies_do_not_replace_each_other(
    engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup:
        owner, _, _, dataset, _ = await _setup(setup)
        dataset_id = dataset.id
        await setup.commit()
    barrier = asyncio.Barrier(2)

    async def save(kind: Literal["generator", "improver"]) -> None:
        async with factory() as session:
            service = DatasetService(session)
            await service.get(owner, dataset_id)
            await barrier.wait()
            helper = DatasetHelper(instructions=f"Instructions for {kind}.")
            changes = (
                DatasetHelpers(generator=helper)
                if kind == "generator"
                else DatasetHelpers(improver=helper)
            )
            await service.update(owner, dataset_id, DatasetUpdate(helper_settings=changes))
            await session.commit()

    async with asyncio.TaskGroup() as group:
        group.create_task(save("generator"))
        group.create_task(save("improver"))
    async with factory() as session:
        read = await DatasetService(session).read(owner, dataset_id)
        assert read.helper_settings.generator.instructions == "Instructions for generator."
        assert read.helper_settings.improver.instructions == "Instructions for improver."


async def test_helper_instruction_patch_keeps_its_model_and_null_resets_settings(
    db: AsyncSession,
) -> None:
    owner, org, _, dataset, _ = await _setup(db)
    model = await _profile(db, org)
    service = DatasetService(db)
    await service.update(
        owner,
        dataset.id,
        DatasetUpdate(
            helper_settings=DatasetHelpers(
                generator=DatasetHelper(model_profile_id=model.id, instructions="Original.")
            )
        ),
    )
    read = await service.update(
        owner,
        dataset.id,
        DatasetUpdate(
            helper_settings=DatasetHelpers(generator=DatasetHelper(instructions="Updated."))
        ),
    )
    assert read.helper_settings.generator == DatasetHelper(
        model_profile_id=model.id, instructions="Updated."
    )
    reset = await service.update(owner, dataset.id, DatasetUpdate(helper_settings=None))
    assert reset.helper_settings == DatasetHelpers()


async def test_generation_estimate_reports_unknown_price_after_its_model_is_deleted(
    db: AsyncSession,
) -> None:
    owner, org, agent, dataset, _ = await _setup(db)
    model = await _profile(db, org)
    await DatasetService(db).update(
        owner,
        dataset.id,
        DatasetUpdate(
            helper_settings=DatasetHelpers(generator=DatasetHelper(model_profile_id=model.id))
        ),
    )
    await db.delete(model)
    await db.flush()
    estimate = await _service(db).estimate(owner, dataset.id, _request(agent, "agent"))
    assert estimate.estimated_cost_usd is None


async def test_resolving_an_inherited_generation_model_refuses_a_deleted_agent(
    db: AsyncSession,
) -> None:
    owner, _, agent, _, _ = await _setup(db)
    request = _request(agent, "agent").model_copy(update={"agent_id": uuid4()})
    with pytest.raises(NotFoundError, match="Agent not found"):
        await _service(db)._helper(owner, request)


async def test_authoring_prices_the_explicit_helper_model_and_instructions(
    db: AsyncSession,
) -> None:
    from app.agents.system_agents import IMPROVER
    from app.services.authoring import AuthoringService
    from app.services.system_agents import SystemAgentService

    owner, org, _, _, _ = await _setup(db)
    model = await _profile(db, org)
    helper = await SystemAgentService(db).ensure(organization_id=org.id, key=IMPROVER.key)
    price = await AuthoringService(db)._per_call(
        owner,
        helper,
        120,
        helper=DatasetHelper(model_profile_id=model.id, instructions="Use the chosen model."),
    )
    assert price > 0


async def test_bootstrap_enabling_grading_keeps_existing_criteria(db: AsyncSession) -> None:
    from app.schemas.scoring import DatasetScoringUpdate
    from app.services.agent_test_set import AgentTestSetService
    from app.services.scoring import ScoringService

    owner, _, _, dataset, _ = await _setup(db)
    await ScoringService(db).set_scoring(
        owner,
        dataset.id,
        DatasetScoringUpdate.model_validate(
            {"judge": {"criteria": [{"name": "Existing", "description": "Keep this criterion."}]}}
        ),
    )
    row = await DatasetService(db).get(owner, dataset.id)
    service = AgentTestSetService(db, vector_store=_service(db).sources.vector_store)
    await service._switch_on(owner, row, None)
    read = await DatasetService(db).read(owner, dataset.id)
    assert [criterion.name for criterion in read.scoring.judge.criteria] == ["Existing"]
    assert read.scoring.judge.enabled and read.scoring.reference.enabled
