"""Create invitations for several addresses at once and print their links.

Usage:
    project cmd invite-members <org-id> a@example.com b@example.com
    project cmd invite-members <org-id> a@example.com --role admin
    project cmd invite-members <org-id> a@example.com --as owner@example.com

Why it exists: a deployment with no `SMTP_*` configured emails nobody, so every
invitation has to be passed on by hand - and the token is returned once and
stored nowhere a second read can reach. Doing that one address at a time through
the dialog is the shape this replaces.

It goes through `InvitationService.invite` rather than the repository, so the
role ceiling, the seat cap and the duplicate checks apply exactly as they do to
somebody clicking the button. That is also why it needs somebody to act as: a
role gate has to have a role to weigh the offered one against.
"""

import asyncio
from uuid import UUID

import click
from sqlalchemy.ext.asyncio import AsyncSession

from app.commands import command, error, info, success, warning
from app.core.config import settings
from app.core.exceptions import AppException
from app.db.session import get_db_context
from app.repositories import member_repo, organization_repo, user_repo
from app.services.invitation import InvitationService


@command("invite-members", help="Invite several addresses to an organization and print the links")
@click.argument("organization_id")
@click.argument("emails", nargs=-1, required=True)
@click.option(
    "--role", default="member", show_default=True, help="The role every invitee is offered"
)
@click.option(
    "--as",
    "acting_as",
    default=None,
    help="Email of the member to invite as. Defaults to the organization's first owner.",
)
def invite_members(
    organization_id: str, emails: tuple[str, ...], role: str, acting_as: str | None
) -> None:
    asyncio.run(_run(organization_id, emails, role, acting_as))


async def _run(
    organization_id: str, emails: tuple[str, ...], role: str, acting_as: str | None
) -> None:
    try:
        org_id = UUID(organization_id)
    except ValueError:
        error(f"Not a UUID: {organization_id}")
        return

    async with get_db_context() as db:
        org = await organization_repo.get_by_id(db, org_id)
        if not org:
            error(f"No organization with id {org_id}")
            return

        requester_id = await _requester(db, org_id, acting_as)
        if requester_id is None:
            return

        info(f"Inviting {len(emails)} address(es) to {org.name} as {role}\n")

        service = InvitationService(db)
        frontend = settings.FRONTEND_URL.rstrip("/")
        created: list[tuple[str, str, bool]] = []
        refused = 0

        for email in emails:
            try:
                invite, delivered = await service.invite(org_id, email, role, requester_id)
            except AppException as exc:
                # Reported and skipped, not raised: one address already holding a
                # pending invitation must not cost the other nineteen. Nothing was
                # written for this one - every refusal in `invite` precedes the row.
                error(f"  {email}: {exc.message}")
                refused += 1
                continue
            created.append(
                (invite.email or email, f"{frontend}/invitations/{invite.token}", delivered)
            )

        if not created:
            warning("\nNothing created.")
            return

        # Printed as `address<tab>link`, one per line and nothing else between
        # them: this output is meant to be copied, and a table drawn in box
        # characters is a table somebody has to edit before pasting it anywhere.
        info("")
        width = max(len(address) for address, _, _ in created)
        for address, link, _ in created:
            info(f"  {address.ljust(width)}  {link}")

        success(f"\n{len(created)} invitation(s) created.")
        if refused:
            warning(f"{refused} refused - see above.")
        if not any(delivered for _, _, delivered in created):
            warning(
                "No email left this deployment - pass the links on yourself. "
                "Set SMTP_* to have them sent."
            )
        elif not all(delivered for _, _, delivered in created):
            warning("Some of these were emailed and some were not; pass on the rest yourself.")


async def _requester(db: AsyncSession, organization_id: UUID, acting_as: str | None) -> UUID | None:
    """Whose authority the invitations are created under."""
    if acting_as is None:
        owner_id = await member_repo.first_owner_id(db, organization_id=organization_id)
        if owner_id is None:
            error("This organization has no owner to invite as - pass --as <email>.")
        return owner_id

    user = await user_repo.get_by_email(db, acting_as.lower())
    if not user:
        error(f"No user with email {acting_as}")
        return None
    member = await member_repo.get(db, organization_id=organization_id, user_id=user.id)
    if not member:
        error(f"{acting_as} is not a member of this organization")
        return None
    return user.id
