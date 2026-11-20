"""Real persistence: atomic bundles, principal isolation and serialized retries."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError
from app.core.permissions import AuthContext
from app.db.models import (
    Agent,
    ContextFile,
    Dataset,
    Organization,
    OrganizationMember,
    SolutionInstallation,
    User,
)
from app.db.session import get_db_context
from app.schemas.solution import SolutionInstall, SolutionManifest
from app.services.solution import SolutionService, plan_solution

pytestmark = pytest.mark.anyio


async def owner(db: AsyncSession) -> AuthContext:
    user = User(email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(name="Solutions", slug=uuid4().hex, created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    await db.commit()
    return AuthContext(user_id=user.id, organization_id=org.id, role="owner")


def bundle(name: str = "support") -> SolutionInstall:
    manifest = SolutionManifest.model_validate(
        {
            "name": name,
            "contexts": [
                {
                    "key": "policy",
                    "data": {"name": name + "-policy", "content": "Do not invent an answer."},
                }
            ],
            "skills": [
                {
                    "key": "triage",
                    "data": {
                        "name": name + "-triage",
                        "description": "Triage requests",
                        "content": "Ask for the missing facts.",
                    },
                }
            ],
            "datasets": [
                {
                    "key": "questions",
                    "data": {"name": name + "-questions"},
                    "cases": [{"input": "Unknown policy?", "reference_answer": "Escalate."}],
                }
            ],
            "agents": [
                {
                    "key": "assistant",
                    "spec": {
                        "name": name + "-assistant",
                        "instructions": "Answer support requests.",
                        "capabilities": [{"id": "skills"}],
                    },
                    "context_keys": ["policy"],
                    "skill_keys": ["triage"],
                }
            ],
        }
    )
    return SolutionInstall(
        installation_key=name,
        manifest=manifest,
        expected_manifest_hash=plan_solution(manifest).manifest_hash,
    )


async def test_private_resources_are_bound_and_same_installation_replays(db: AsyncSession) -> None:
    ctx = await owner(db)
    request = bundle()
    first = await SolutionService(db).install(ctx, request)
    await db.commit()
    second = await SolutionService(db).install(ctx, request)
    assert second.replayed and first.resources == second.resources
    agent = await db.get(Agent, first.resources["assistant"].id)
    assert agent is not None and agent.current_version_id is None
    assert agent.draft_spec["context_ids"] == [str(first.resources["policy"].id)]
    assert agent.draft_spec["skill_ids"] == [str(first.resources["triage"].id)]
    assert agent.visibility == "private"
    assert await db.scalar(select(func.count()).select_from(SolutionInstallation)) == 1
    assert await db.scalar(select(func.count()).select_from(Dataset)) == 1


@pytest.mark.security
async def test_receipt_cannot_be_replayed_from_another_organization(db: AsyncSession) -> None:
    first_ctx, other_ctx = await owner(db), await owner(db)
    request = bundle()
    first = await SolutionService(db).install(first_ctx, request)
    await db.commit()
    other = await SolutionService(db).install(other_ctx, request)
    assert not other.replayed and other.resources != first.resources
    await db.commit()
    assert await db.scalar(select(func.count()).select_from(SolutionInstallation)) == 2


async def test_changed_manifest_on_same_key_is_refused_without_overwrite(db: AsyncSession) -> None:
    ctx = await owner(db)
    request = bundle()
    await SolutionService(db).install(ctx, request)
    await db.commit()
    changed = bundle("other").model_copy(update={"installation_key": request.installation_key})
    with pytest.raises(ConflictError, match="already names"):
        await SolutionService(db).install(ctx, changed)
    assert await db.scalar(select(func.count()).select_from(ContextFile)) == 1


async def test_late_failure_rolls_back_resources_and_receipt(db: AsyncSession) -> None:
    ctx = await owner(db)
    request = bundle()
    request.manifest.skills[0].data.name = "knowledge"
    # Validation normally refuses a capability name. Revalidation of stored
    # data here deliberately happens in the domain service after context creation.
    request.expected_manifest_hash = plan_solution(request.manifest).manifest_hash
    with pytest.raises(BadRequestError, match=r"capability|reserved|name"):
        async with db.begin_nested():
            await SolutionService(db).install(ctx, request)
    assert await db.scalar(select(func.count()).select_from(ContextFile)) == 0
    assert await db.scalar(select(func.count()).select_from(SolutionInstallation)) == 0


async def test_concurrent_same_key_creates_only_one_bundle(db: AsyncSession) -> None:
    ctx = await owner(db)
    request = bundle()

    async def install() -> bool:
        async with get_db_context() as session:
            result = await SolutionService(session).install(ctx, request)
            return result.replayed

    results = await asyncio.gather(install(), install())
    assert sorted(results) == [False, True]
    assert await db.scalar(select(func.count()).select_from(SolutionInstallation)) == 1
    assert await db.scalar(select(func.count()).select_from(Agent)) == 1


@pytest.mark.parametrize("name", ["support", "repository", "onboarding"])
async def test_shipped_bundles_install_valid_private_workflows_with_tables(
    db: AsyncSession, name: str
) -> None:
    from pathlib import Path

    from app.db.models.workflow import Workflow
    from app.services.workflow_registry import WorkflowRegistryService

    ctx = await owner(db)
    path = Path(__file__).resolve().parents[3] / "plugins/agenticos/solutions" / f"{name}.json"
    manifest = SolutionManifest.model_validate_json(path.read_text())
    request = SolutionInstall(
        installation_key=name,
        manifest=manifest,
        expected_manifest_hash=plan_solution(manifest).manifest_hash,
    )
    result = await SolutionService(db).install(ctx, request)
    assert "intake.table" in result.resources
    check = await WorkflowRegistryService(db).check_draft(ctx, result.resources["intake"].id)
    assert check.graph_valid
    workflow = await db.get(Workflow, result.resources["intake"].id)
    assert workflow is not None and workflow.current_version_id is None


async def test_optional_knowledge_uses_explicit_embedding_dependency_without_indexing(
    db: AsyncSession,
) -> None:
    from app.db.models.local_service import LocalService
    from app.schemas.solution import SolutionKnowledge

    ctx = await owner(db)
    endpoint = LocalService(
        name="Embedding fixture",
        organization_id=ctx.organization_id,
        kind="embedding",
        provider="ollama",
        base_url="http://embedding.example/v1",
        is_active=True,
    )
    db.add(endpoint)
    await db.flush()
    request = bundle()
    request.manifest.knowledge.append(
        SolutionKnowledge.model_validate(
            {
                "key": "handbook",
                "data": {
                    "name": "Handbook",
                    "embedding_provider": "ollama",
                    "embedding_model": "nomic-embed-text",
                    "embedding_endpoint_id": str(endpoint.id),
                },
            }
        )
    )
    request.manifest.agents[0].knowledge_keys = ["handbook"]
    request.expected_manifest_hash = plan_solution(request.manifest).manifest_hash
    result = await SolutionService(db).install(ctx, request)
    agent = await db.get(Agent, result.resources["assistant"].id)
    assert agent is not None and agent.draft_spec["collection_ids"] == [
        str(result.resources["handbook"].id)
    ]


async def test_workflow_without_table_creates_no_extra_table_receipt(db: AsyncSession) -> None:
    ctx = await owner(db)
    node = str(uuid4())
    manifest = SolutionManifest.model_validate(
        {
            "name": "minimal",
            "workflows": [
                {
                    "key": "flow",
                    "data": {
                        "name": "Minimal flow",
                        "graph": {
                            "entry_node_id": node,
                            "nodes": [
                                {
                                    "id": node,
                                    "definition_id": "trigger.manual",
                                    "definition_version": 1,
                                    "config": {},
                                    "layout": {"x": 0, "y": 0},
                                }
                            ],
                        },
                    },
                }
            ],
        }
    )
    request = SolutionInstall(
        installation_key="minimal",
        manifest=manifest,
        expected_manifest_hash=plan_solution(manifest).manifest_hash,
    )
    result = await SolutionService(db).install(ctx, request)
    assert set(result.resources) == {"flow"}


@pytest.mark.security
async def test_prepared_install_and_history_are_principal_scoped_and_replay_after_cache_loss(
    db: AsyncSession,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.clients.redis import RedisClient
    from app.core.exceptions import NotFoundError
    from app.schemas.solution import PreparedSolutionInstall

    ctx = await owner(db)
    other = await owner(db)
    peer = User(email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(peer)
    await db.flush()
    db.add(OrganizationMember(organization_id=ctx.organization_id, user_id=peer.id, role="owner"))
    await db.commit()
    peer_ctx = AuthContext(user_id=peer.id, organization_id=ctx.organization_id, role="owner")
    stored: dict[str, str] = {}

    async def set_value(key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        assert ttl == 86400 and nx
        stored[key] = value
        return True

    cache = MagicMock(spec=RedisClient)
    cache.set = AsyncMock(side_effect=set_value)
    cache.get = AsyncMock(side_effect=stored.get)
    service = SolutionService(db)
    source = bundle("prepared")
    reviewed = await service.prepare(ctx, source.manifest, cache)
    request = PreparedSolutionInstall(
        plan_id=reviewed.plan_id,
        installation_key=source.installation_key,
        expected_manifest_hash=reviewed.manifest_hash,
    )
    for stranger in (other, peer_ctx):
        with pytest.raises(NotFoundError):
            await service.install_prepared(stranger, request, cache)
    installed = await service.install_prepared(ctx, request, cache)
    await db.commit()
    historical = await service.read_installation(ctx, source.installation_key)
    assert historical.resources == installed.resources
    for stranger in (other, peer_ctx):
        with pytest.raises(NotFoundError):
            await service.read_installation(stranger, source.installation_key)
    stored.clear()
    with pytest.raises(NotFoundError):
        await service.install_prepared(ctx, request, cache)
    renewed = await service.prepare(ctx, source.manifest, cache)
    request.plan_id = renewed.plan_id
    replay = await service.install_prepared(ctx, request, cache)
    assert replay.replayed and replay.resources == installed.resources
