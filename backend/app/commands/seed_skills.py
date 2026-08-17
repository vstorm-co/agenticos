"""Install the bundled skills into an organization.

The same copy organization creation and the skills listing's top-up make, from
a terminal - for a fresh deployment that should come up with something in it,
and for a scripted setup that has no browser to click in.

Idempotent by name: a skill the organization already has is left exactly as it
is, never overwritten. An organization edits its skills, and a seed command
that reset the refund policy on every deploy would be a command nobody dares
run twice.
"""

import asyncio
from uuid import UUID

import click
from sqlalchemy.exc import IntegrityError

from app.commands import command, info, success, warning
from app.core.exceptions import AlreadyExistsError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.session import get_db_context
from app.repositories import member_repo, organization_repo
from app.services import skill_library
from app.services.skills import SkillService


@command("seed-skills", help="Install the bundled skills into an organization")
@click.option("--org", "org_id", help="Organization id. Defaults to every organization.")
@click.option("--dry-run", is_flag=True, help="Say what would be installed and stop")
def seed_skills(org_id: str | None, dry_run: bool) -> None:
    """Copy every skill in `app/core/catalog/skills` into an organization."""
    asyncio.run(_run(org_id, dry_run))


async def _run(org_id: str | None, dry_run: bool) -> None:
    bundled = skill_library.library()
    if not bundled:
        warning("No bundled skills found - is app/core/catalog/skills missing?")
        return

    info(f"{len(bundled)} bundled skill(s): {', '.join(skill.key for skill in bundled)}")

    async with get_db_context() as db:
        organizations = (
            [await organization_repo.get_by_id(db, UUID(org_id))]
            if org_id
            else await organization_repo.list_all(db)
        )
        targets = [organization for organization in organizations if organization is not None]
        if not targets:
            warning("No such organization.")
            return

        for organization in targets:
            info(f"→ {organization.name}")
            if dry_run:
                for skill in bundled:
                    click.echo(f"    would install {skill.name} ({len(skill.resources)} file(s))")
                continue

            # Seeded as the organization's owner, not as "the organization":
            # a skill records who owns it, that column is a foreign key to a
            # real person, and an owner is the one member guaranteed to exist
            # and to be allowed to edit what lands here.
            owner = await member_repo.first_owner_id(db, organization_id=organization.id)
            if owner is None:
                warning("    no owner - skipped")
                continue

            service = SkillService(db)
            ctx = AuthContext(
                user_id=owner,
                organization_id=organization.id,
                role=OrgRoleName.OWNER,
            )
            # Each install under its own savepoint, exactly as the listing's
            # top-up does it: a listing committing the same skill mid-command
            # surfaces as an IntegrityError at flush, and without the savepoint
            # a caught one leaves the session dead for every skill after it.
            for skill in bundled:
                try:
                    async with db.begin_nested():
                        installed = await service.install_from_library(ctx, skill.key)
                except (AlreadyExistsError, IntegrityError):
                    click.echo(f"    {skill.name} - already there, left alone")
                    continue
                click.echo(f"    {installed.name} - installed with {len(skill.resources)} file(s)")

    success("Done." if not dry_run else "Dry run - nothing was written.")
