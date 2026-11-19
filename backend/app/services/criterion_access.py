"""Current dataset and skill access for criterion evidence, batched across readers' rows."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.repositories import eval_run_repo, skill_repo
from app.services.access import DATASET, SKILL, accessible_ids


async def readable_criterion_owners(
    db: AsyncSession, ctx: AuthContext, names: set[str]
) -> set[str]:
    """Stored criterion attributions name only skills the reader can still open."""
    if not names:
        return set()
    skills = await skill_repo.get_by_names(db, names, organization_id=ctx.organization_id)
    visible = await accessible_ids(
        db, ctx, list(skills.values()), Perm.SKILLS_VIEW, resource_type=SKILL
    )
    return {name for name, skill in skills.items() if skill.id in visible}


async def criterion_source_access(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    dataset_ids: set[UUID],
    names: set[str],
) -> tuple[set[UUID], set[str]]:
    """Readable datasets and named owners; no grade access without runs:view."""
    if not ctx.has(Perm.RUNS_VIEW) or not dataset_ids:
        return set(), set()
    datasets = await eval_run_repo.datasets(
        db, sorted(dataset_ids), organization_id=ctx.organization_id
    )
    visible = await accessible_ids(
        db, ctx, list(datasets.values()), Perm.DATASETS_VIEW, resource_type=DATASET
    )
    if not visible:
        return set(), set()
    return visible, await readable_criterion_owners(db, ctx, names)


async def readable_criterion_skill_ids(
    db: AsyncSession, ctx: AuthContext, ids: set[UUID]
) -> set[UUID]:
    """Exact original skill identities; a reused name never revives old evidence."""
    if not ids:
        return set()
    skills = await skill_repo.get_many(db, sorted(ids), organization_id=ctx.organization_id)
    return await accessible_ids(
        db, ctx, list(skills.values()), Perm.SKILLS_VIEW, resource_type=SKILL
    )
