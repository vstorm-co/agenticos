"""Re-wrap every stored secret under the current master key.

The staged rotation `docs/secrets.md` describes, implemented: an operator adds
the new master key to `VAULT_MASTER_KEYS` beside the old one, runs this
command, and drops the old key once it reports every row moved. Until #8 that
procedure had no implementation - `rewrap` existed with zero production
callers, so following the documented steps destroyed every credential.

The sweep walks every table holding vault envelopes. Each row is re-wrapped as
a unit: all of a row's ciphertexts share one version column, so either every
envelope moves and the column follows, or the row is left exactly as it was
and reported. A row that fails does not stop the sweep - stopping would leave
an unknown remainder under the old key with nothing naming it, where a report
names each failure and exits non-zero so the operator knows to keep the old
key configured and retry.

Rotating also upgrades the envelope format in place (`ENVELOPE_VERSION` 1 to
2, bare SHA-256 to HKDF), so running it with a single configured key is
meaningful too: it moves a deployment off the old derivation without minting
a new master key.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

import click
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commands import command, error, info, success
from app.core.exceptions import AppException
from app.core.vault import VaultScope, current_key_version, needs_rotation, rewrap, unseal
from app.db.models.agent_embed import AgentEmbed
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.channel_bot import ChannelBot
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization_secret import OrganizationSecret
from app.db.session import get_db_context
from app.services.mcp_connection import connection_scope


def _org_scope(row: OrganizationSecret | ChannelBot | AgentEmbed | AgentTrigger) -> VaultScope:
    return VaultScope.organization(row.organization_id)


@dataclass(frozen=True)
class SealedTable:
    """One table holding vault envelopes.

    Attributes:
        label: The table name, for the report.
        model: The mapped class the sweep selects.
        columns: Every ciphertext column. A row's envelopes share one version,
            so they are re-wrapped together or not at all.
        version_attr: The column recording which master key sealed the row.
        scope: The owner the row's envelopes are bound to - an organization
            for everything except a personal MCP connection, which belongs to
            its member.
    """

    label: str
    model: type[OrganizationSecret | ChannelBot | McpConnection | AgentEmbed | AgentTrigger]
    columns: tuple[str, ...]
    version_attr: str
    scope: Callable[..., VaultScope]


SEALED_TABLES: tuple[SealedTable, ...] = (
    SealedTable(
        label="organization_secrets",
        model=OrganizationSecret,
        columns=("sealed_secret",),
        version_attr="key_version",
        scope=_org_scope,
    ),
    SealedTable(
        label="channel_bots",
        model=ChannelBot,
        columns=(
            "token_encrypted",
            "webhook_secret_encrypted",
            "slack_signing_secret_encrypted",
            "slack_app_token_encrypted",
        ),
        version_attr="secret_key_version",
        scope=_org_scope,
    ),
    SealedTable(
        label="mcp_connections",
        model=McpConnection,
        columns=("auth_token", "oauth_payload", "oauth_pending_payload"),
        version_attr="secret_key_version",
        scope=connection_scope,
    ),
    SealedTable(
        label="agent_embeds",
        model=AgentEmbed,
        columns=("jwt_secret_encrypted",),
        version_attr="secret_key_version",
        scope=_org_scope,
    ),
    SealedTable(
        label="agent_triggers",
        model=AgentTrigger,
        columns=("event_secret_encrypted",),
        version_attr="secret_key_version",
        scope=_org_scope,
    ),
)


@dataclass
class Report:
    """What the sweep did, and to how many rows."""

    rotated: int = 0
    retagged: int = 0
    current: int = 0
    no_secret: int = 0
    failures: list[str] = field(default_factory=list)


async def _rotate_table(
    db: AsyncSession, spec: SealedTable, *, target: int, dry_run: bool, report: Report
) -> None:
    # Locked, because the deployment may be live: an OAuth refresh that rewrites
    # a connection's payload between this read and the commit would be silently
    # overwritten by the sweep's stale copy - restoring an already-spent refresh
    # token. A dry run writes nothing, so it reads without blocking anybody.
    stmt = select(spec.model) if dry_run else select(spec.model).with_for_update()
    rows = (await db.execute(stmt)).scalars().all()
    for row in rows:
        version = getattr(row, spec.version_attr)
        present = {
            name: value for name in spec.columns if (value := getattr(row, name)) is not None
        }
        if not present:
            # A row with no envelope still names a version, and a later seal
            # into it lands at that version (`_seal_for`) - left stale, it would
            # point at a key the operator has since dropped. Nothing to rewrap,
            # so the claim just moves. A null version (a polled trigger) names
            # nothing and stays null.
            if version is not None and version != target:
                if not dry_run:
                    setattr(row, spec.version_attr, target)
                report.retagged += 1
            else:
                report.no_secret += 1
            continue
        scope = spec.scope(row)
        needs_move = any(needs_rotation(value, key_version=version) for value in present.values())
        if dry_run:
            # The preflight's promise is that every stored envelope *opens*, so
            # it unseals payload and all: `rewrap` only authenticates the
            # wrapped data key, and a row already at the current version would
            # otherwise be waved through unread - either way a credential
            # `unseal` rejects at runtime would pass the preflight.
            try:
                for value in present.values():
                    unseal(value, scope=scope, key_version=version)
            except AppException as exc:
                report.failures.append(f"{spec.label} {row.id}: {exc.message}")
                continue
            if needs_move:
                report.rotated += 1
            else:
                report.current += 1
            continue
        if not needs_move:
            report.current += 1
            continue
        try:
            rotated = {
                name: rewrap(value, scope=scope, from_version=version, to_version=target)
                for name, value in present.items()
            }
        except AppException as exc:
            report.failures.append(f"{spec.label} {row.id}: {exc.message}")
            continue
        for name, value in rotated.items():
            setattr(row, name, value)
        setattr(row, spec.version_attr, target)
        report.rotated += 1


async def _run(*, dry_run: bool) -> Report:
    target = current_key_version()
    report = Report()
    async with get_db_context() as db:
        for spec in SEALED_TABLES:
            await _rotate_table(db, spec, target=target, dry_run=dry_run, report=report)
    return report


@command("vault-rotate", help="Re-wrap every stored secret under the current master key")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Unseal every stored envelope without writing, so failures surface before anything moves",
)
def vault_rotate(dry_run: bool) -> None:
    """Move every sealed row to the current master-key version.

    Exits non-zero when any row could not be re-wrapped, so a provisioning
    script cannot drop the old key on a partial rotation. A dry run fully
    unseals every stored envelope - payload included, and rows already at the
    current version too - and writes nothing, which is how an operator learns
    *before* rotating whether every stored credential actually opens under the
    keys configured today.

    Example:
        agenticos cmd vault-rotate --dry-run
        agenticos cmd vault-rotate
    """
    target = current_key_version()
    mode = "would be re-wrapped (dry run)" if dry_run else "re-wrapped"
    info(f"Rotating every stored secret to master-key version {target}...")
    report = asyncio.run(_run(dry_run=dry_run))
    success(f"{report.rotated} rows {mode}")
    info(
        f"{report.retagged} credential-free rows moved to the current version, "
        f"{report.current} already current, {report.no_secret} hold no secret"
    )
    if report.failures:
        for failure in report.failures:
            error(failure)
        error(
            f"{len(report.failures)} rows could not be re-wrapped - keep the old key "
            "configured, fix what the messages name, and run again"
        )
        raise SystemExit(1)
