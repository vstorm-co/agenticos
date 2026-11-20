"""Judge again, from the runs they kept, the agents of finished skill checks.

A check's agent row is what the rule said when its stage runs finished. One judged
before families of criteria were kept shows its criteria one by one, and one judged
before `too_few_questions` existed says its run could not grade every answer when
it only had too few questions. Judging it again reads the same runs - no model is
asked - and a decided check keeps its decision, as after a person's review.
"""

import asyncio
from collections.abc import Sequence
from uuid import UUID

import click

from app.commands import command, info, success
from app.db.session import get_db_context
from app.repositories import skill_check_repo
from app.services.skill_check import SkillCheckService


@command("skill-checks-rejudge", help="Judge finished skill checks again from their stored runs")
@click.option(
    "--check",
    "check_ids",
    type=click.UUID,
    multiple=True,
    help="A check to judge again; repeat for several. Defaults to every check judged by an "
    "older rule",
)
def skill_checks_rejudge(check_ids: tuple[UUID, ...]) -> None:
    asyncio.run(_run(check_ids))


async def _run(check_ids: Sequence[UUID]) -> None:
    async with get_db_context() as db:
        found = await skill_check_repo.judged_before_families(db, check_ids=check_ids)
    if not found:
        info("No finished check has an agent judged by an older rule.")
        return
    for organization_id, check_id, run_ids in found:
        async with get_db_context() as db:
            await SkillCheckService(db).recompute_after_review(organization_id, run_ids)
        info(f"Judged check {check_id} again from {len(run_ids)} stage run(s).")
    success(f"{len(found)} check(s) judged again.")
