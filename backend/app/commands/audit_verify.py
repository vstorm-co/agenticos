"""Recompute the app-admin audit trail's hash chain and report any break.

The trail is what `docs/governance.md` points to when it says a privileged action
is accountable, and #1622 gave each entry a place in a per-organization hash
chain. This command is how an operator actually reads that evidence: it walks each
chain, recomputes every entry's hash, and reports the first entry whose stored hash
no longer matches its contents or no longer links to the entry before it.

It exits non-zero when any chain fails, so it can run in a scheduled job or a
provisioning check and fail loudly rather than in a report nobody reads. The two
deletions the hash walk cannot see on its own - the newest entries dropped, and a
whole chain deleted - are caught by comparing each chain against its checkpoint
(`app_admin_audit_checkpoints`, #1648): a head behind the recorded high-water mark,
or a checkpoint with no chain at all.

What it proves is detection, not prevention: an operator with the database can
rewrite a row and recompute every hash after it, and a Postgres superuser can drop
the checkpoint's guard trigger and delete both the entries and the checkpoint - so
a clean run means no tampering by anyone who did not also defeat those, not that the
database is immutable. Closing the superuser gap needs a checkpoint kept outside
this database, which #1648 tracks as the next step.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import click

from app.commands import command, error, info, success
from app.db.session import get_db_context
from app.services.audit import AuditService, ChainVerification


async def _run(organization_id: UUID | None) -> list[ChainVerification]:
    async with get_db_context() as db:
        service = AuditService(db)
        if organization_id is not None:
            return [await service.verify_chain(organization_id)]
        return await service.verify_all_chains()


@command(
    "audit-verify", help="Recompute the app-admin audit trail's hash chain and report any break"
)
@click.option(
    "--org",
    "organization_id",
    type=click.UUID,
    default=None,
    help="Verify only this organization's chain; omit to verify every chain",
)
def audit_verify(organization_id: UUID | None) -> None:
    """Walk each audit chain, recompute its hashes, and report the first break.

    With no `--org`, every chain is verified, including the deployment-wide one
    that holds actions with no tenant - deployment settings, impersonation, and
    app-admin user management. Exits
    non-zero if any chain fails, naming the entry it broke on.

    Example:
        agenticos cmd audit-verify
        agenticos cmd audit-verify --org 5f2b...
    """
    info("Verifying the app-admin audit trail...")
    results = asyncio.run(_run(organization_id))
    broken = [result for result in results if result.first_break is not None]
    for result in results:
        label = "deployment" if result.organization_id is None else str(result.organization_id)
        if result.first_break is None:
            success(f"{label}: {result.entries_checked} entries verified")
        else:
            first_break = result.first_break
            error(
                f"{label}: broke at seq {first_break.seq} (entry {first_break.entry_id}) - "
                f"{first_break.reason}; {result.entries_checked} entries checked before it"
            )
    if broken:
        error(f"{len(broken)} chain(s) failed verification - the trail has been altered")
        raise SystemExit(1)
    success("The audit trail is intact.")
