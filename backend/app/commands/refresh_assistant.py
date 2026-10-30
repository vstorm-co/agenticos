"""Inspect and refresh installed Architects after a deployment update."""

import asyncio
from uuid import UUID

import click

from app.commands import command
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.session import get_db_context
from app.repositories import member_repo, organization_repo
from app.services.assistant import AssistantService


@command("refresh-assistant", help="Refresh installed Architect instructions and guide")
@click.option(
    "--org", "org_id", type=click.UUID, help="Organization ID; defaults to all organizations"
)
@click.option(
    "--dry-run", is_flag=True, help="Report current, outdated and edited copies without writing"
)
@click.option(
    "--replace-edited",
    is_flag=True,
    help="Replace customized instructions and guide; organization edits are lost",
)
def refresh_assistant(org_id: UUID | None, dry_run: bool, replace_edited: bool) -> None:
    asyncio.run(_run(org_id, dry_run=dry_run, replace_edited=replace_edited))


async def _run(org_id: UUID | None, *, dry_run: bool, replace_edited: bool) -> None:
    async with get_db_context() as db:
        organizations = (
            [await organization_repo.get_by_id(db, org_id)]
            if org_id is not None
            else await organization_repo.list_all(db)
        )
        targets = [(org.id, org.name) for org in organizations if org is not None]
    if org_id is not None and not targets:
        raise NotFoundError(
            message="Organization not found", details={"organization_id": str(org_id)}
        )
    for target_id, name in targets:
        # Each organization commits independently; a failed refresh never commits
        # only half of that organization's instruction/guide update.
        async with get_db_context() as db:
            service = AssistantService(db)
            owner_id = await member_repo.first_owner_id(db, organization_id=target_id)
            if owner_id is None:
                raise NotFoundError(
                    message="Organization has no owner", details={"organization_id": str(target_id)}
                )
            ctx = AuthContext(user_id=owner_id, organization_id=target_id, role=OrgRoleName.OWNER)
            result = await service.refresh(ctx, dry_run=dry_run, replace_edited=replace_edited)
        click.echo(
            f"{name} ({target_id}): instructions={result.instructions or 'skipped'}, guide={result.guide or 'skipped'}"
        )
        if result.published_version is not None:
            click.echo(f"  published version {result.published_version}")
        if result.detail:
            click.echo(f"  {result.detail}")
    if dry_run:
        click.echo(
            "Dry run: nothing written. update means would refresh; edited/untracked copies require --replace-edited."
        )
