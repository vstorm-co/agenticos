"""Install the bundled skills into an organization.

The same copy the gallery's install button makes, from a terminal - for a fresh
deployment that should come up with something in it, and for a scripted setup
that has no browser to click in.

Idempotent by name: a skill the organization already has is left exactly as it
is, never overwritten. An organization edits its skills, and a seed command
that reset the refund policy on every deploy would be a command nobody dares
run twice.
"""

import asyncio
from uuid import UUID

import click
from sqlalchemy.ext.asyncio import AsyncSession

from app.commands import command, info, success, warning
from app.core.exceptions import AlreadyExistsError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.resource_grant import Visibility
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


async def _owner_of(db: AsyncSession, organization_id: UUID) -> UUID | None:
    """The first owner of an organization, or None if it somehow has none."""
    members = await member_repo.list_for_org(db, organization_id)
    return next(
        (member.user_id for member, *_ in members if member.role == OrgRoleName.OWNER),
        None,
    )


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
            owner = await _owner_of(db, organization.id)
            if owner is None:
                warning("    no owner - skipped")
                continue

            service = SkillService(db)
            ctx = AuthContext(
                user_id=owner,
                organization_id=organization.id,
                role=OrgRoleName.OWNER,
            )
            for skill in bundled:
                try:
                    installed = await service.install_from_library(ctx, skill.key)
                except AlreadyExistsError:
                    click.echo(f"    {skill.name} - already there, left alone")
                    continue
                # Visible to the organization rather than to the person the
                # seed ran as. A bundled skill is for everybody; private is the
                # right default for something somebody wrote, and the wrong one
                # for something the platform shipped.
                await service.update(ctx, installed.id, {"visibility": Visibility.ORG.value})
                click.echo(f"    {installed.name} - installed with {len(skill.resources)} file(s)")

    success("Done." if not dry_run else "Dry run - nothing was written.")
