"""Judge again, from the runs they kept, the agents of finished skill checks.

A check's agent row is what the rule said when its stage runs finished. One judged
before families of criteria were kept shows its criteria one by one, and one judged
before `too_few_questions` existed says its run could not grade every answer when
it only had too few questions. Judging it again reads the same runs - no model is
asked - and a decided check keeps its decision, as after a person's review.

A skill session's attempt counted only its check's answers before the judge's
gradings were counted too; its cost is counted again from the same runs.
"""

import asyncio
from collections.abc import Sequence
from uuid import UUID

import click

from app.commands import command, info, success
from app.db.session import get_db_context
from app.repositories import skill_check_repo, skill_improvement_repo
from app.services.skill_check import SkillCheckService
from app.services.skill_improvement import SkillImprovementService


@command("skill-checks-rejudge", help="Judge finished skill checks again from their stored runs")
@click.option(
    "--check",
    "check_ids",
    type=click.UUID,
    multiple=True,
    help="A check to judge again; repeat for several. Defaults to every check judged by an "
    "older rule, and every session attempt counted without the judge",
)
def skill_checks_rejudge(check_ids: tuple[UUID, ...]) -> None:
    asyncio.run(_run(check_ids))


async def _run(check_ids: Sequence[UUID]) -> None:
    async with get_db_context() as db:
        found = await skill_check_repo.judged_before_families(db, check_ids=check_ids)
        attempts = await skill_improvement_repo.checked_iterations(db, check_ids=check_ids)
    judged = skipped = 0
    for organization_id, check_id, run_ids in found:
        async with get_db_context() as db:
            result = await SkillCheckService(db).recompute_after_review(organization_id, run_ids)
        if result.judged:
            judged += 1
            info(f"Judged check {check_id} again from {len(run_ids)} stage run(s).")
        if result.skipped:
            skipped += result.skipped
            info(
                f"Skipped {result.skipped} agent(s) of check {check_id}: original access is unavailable."
            )
    recounted = 0
    for organization_id, iteration_id in attempts:
        async with get_db_context() as db:
            if await SkillImprovementService(db).recount_check_cost(organization_id, iteration_id):
                recounted += 1
                info(f"Counted the judge in session attempt {iteration_id}.")
    if not found and not recounted:
        info("No finished check or session attempt was counted by an older rule.")
        return
    success(
        f"{judged} check(s) judged again, {recounted} attempt(s) recounted, {skipped} agent(s) skipped."
    )
