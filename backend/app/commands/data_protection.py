"""Print the data-protection evidence a deployment review asks for.

`docs/data-protection.md` describes where personal data lives, what leaves the
deployment and under which configuration. A review of one deployment needs the
same facts about *that* deployment, and until now they were a page of SQL an
operator pasted into `psql` by hand, plus a shell pipeline for the one question
SQL alone cannot answer. This command is the reproducible version: one run, one
report, attachable to the review as it stands.

It reads and prints nothing else. Every query below selects the configuration
that decides where data goes - a provider, an endpoint, a parser, a bot - and
never the data itself: no message text, no document contents, no secret value
and no hint of one. The retention section counts rows and never reads them.

What it cannot answer is the other half of `docs/data-protection.md`: whether
the providers this report lists are covered by a processing agreement, sit where
the deployment needs them to sit, and exclude the traffic from training. Those
are contracts, not rows, and the page names each as evidence to obtain.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import click
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from tabulate import tabulate

from app.commands import command, info, success, warning
from app.core.config import settings
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_embed import AgentEmbed
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.agent_run import AgentRun
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.channel_bot import ChannelBot
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation
from app.db.models.credential import ModelProfile
from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.local_service import LocalService
from app.db.models.mcp_connection import McpConnection
from app.db.models.memory import AgentMemoryFile
from app.db.models.organization import Organization
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.rag_document import RAGDocument
from app.db.models.sandbox_operation import SandboxOperation
from app.db.models.sync_source import SyncSource
from app.db.models.user import User
from app.db.session import get_db_context

# Every column holding a path under `MEDIA_DIR`. The unreferenced-file scan is
# only as good as this list: a column missing from it turns every file it names
# into an apparent orphan, which is the failure mode that would quietly make the
# count useless. `tests/test_data_protection_report.py` asserts the list covers
# every media-path column the models declare, so a new one fails a test rather
# than inflating a number nobody re-derives.
MEDIA_PATH_COLUMNS: tuple[InstrumentedAttribute[str | None] | InstrumentedAttribute[str], ...] = (
    ChatFile.storage_path,
    RAGDocument.storage_path,
    User.avatar_url,
    Organization.avatar_url,
    Agent.avatar_url,
    AgentEmbed.logo_path,
    DeploymentSettings.logo_path,
    DeploymentSettings.favicon_path,
)

# Directories under `MEDIA_DIR` that hold files no row points at, by design:
# generated images are addressed by their path in a message, and the parse
# scratch directory is cleared by the worker that wrote it.
UNREFERENCED_BY_DESIGN = ("generated_", "_rag_tmp")

# How many orphan paths to name before the report stops listing and only counts.
ORPHAN_SAMPLE = 20


@dataclass(frozen=True, slots=True)
class Section:
    """One table of the report: a heading, a note about what it proves, rows."""

    title: str
    note: str
    headers: Sequence[str]
    rows: Sequence[Sequence[Any]]


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _settings_section() -> Section:
    """The deployment settings that decide what leaves, and what is encrypted.

    A credential is reported as set or unset and never printed: the report is
    meant to be attached to a review, and a review attachment holding a Logfire
    write token is a credential leak with a paper trail.
    """
    rows: list[list[str]] = [
        ["ENVIRONMENT", settings.ENVIRONMENT],
        ["MEDIA_DIR", str(settings.MEDIA_DIR)],
        ["LOGFIRE_TOKEN", "set" if settings.LOGFIRE_TOKEN else "unset"],
        ["LOGFIRE_BASE_URL", settings.LOGFIRE_BASE_URL],
        ["POSTGRES_SSLMODE", settings.POSTGRES_SSLMODE or "unset"],
        ["REDIS_SSL", _yes_no(settings.REDIS_SSL)],
        ["SMTP_HOST", settings.SMTP_HOST],
        ["SMTP_TLS", _yes_no(settings.SMTP_TLS)],
        ["LOG_PROVIDER_WRITE_TO_DISK", _yes_no(settings.LOG_PROVIDER_WRITE_TO_DISK)],
        ["RATE_LIMIT_TRUST_FORWARDED_FOR", _yes_no(settings.RATE_LIMIT_TRUST_FORWARDED_FOR)],
        ["MEM0_ALLOWED_HOSTS", ", ".join(settings.MEM0_ALLOWED_HOSTS) or "none"],
        ["GOOGLE_CLIENT_ID", "set" if settings.GOOGLE_CLIENT_ID else "unset"],
    ]
    return Section(
        title="Deployment settings",
        note=(
            "What the process itself decides. LOG_PROVIDER_WRITE_TO_DISK must be no "
            "outside development - the logging email provider writes whole mail "
            "bodies to disk when it is on."
        ),
        headers=("Setting", "Value"),
        rows=rows,
    )


async def _model_destinations(db: AsyncSession) -> Section:
    """Every provider and endpoint an agent's model call can reach."""
    result = await db.execute(
        select(
            Organization.name,
            ModelProfile.label,
            ModelProfile.provider,
            ModelProfile.model,
            ModelProfile.base_url,
        )
        .join(Organization, Organization.id == ModelProfile.organization_id)
        .order_by(Organization.name, ModelProfile.label)
    )
    rows = [
        [
            org,
            label,
            provider,
            model,
            base_url or "provider default",
            # A custom `base_url` is refused without a host or with credentials
            # in it, but plain HTTP is accepted so an Ollama or a gateway on the
            # deployment's own network works. Off that network it sends the
            # prompt and the key in clear, so each one here is a question for
            # the review rather than a finding on its own.
            "plain HTTP" if (base_url or "").startswith("http://") else "",
        ]
        for org, label, provider, model, base_url in result.all()
    ]
    return Section(
        title="Model destinations",
        note="Where prompts, attachments, retrieved chunks and tool results go.",
        headers=("Organization", "Profile", "Provider", "Model", "Endpoint", "Note"),
        rows=rows,
    )


async def _credentials(db: AsyncSession) -> Section:
    """What the vault holds, by purpose - never a value, never a hint."""
    result = await db.execute(
        select(
            Organization.name,
            OrganizationSecret.purpose,
            OrganizationSecret.kind,
            OrganizationSecret.name,
        )
        .join(Organization, Organization.id == OrganizationSecret.organization_id)
        .order_by(Organization.name, OrganizationSecret.purpose, OrganizationSecret.name)
    )
    return Section(
        title="Credentials held",
        note=(
            "One row per sealed credential. Each names a third party this "
            "deployment reaches and therefore needs an agreement with."
        ),
        headers=("Organization", "Purpose", "Kind", "Name"),
        rows=[list(row) for row in result.all()],
    )


async def _collections(db: AsyncSession) -> Section:
    """Who embeds each collection, and which of them parse off-site."""
    result = await db.execute(
        select(
            KnowledgeBase.name,
            KnowledgeBase.embedding_provider,
            KnowledgeBase.embedding_model,
            KnowledgeBase.embedding_endpoint_id,
            KnowledgeBase.ingestion_config,
        ).order_by(KnowledgeBase.name)
    )
    rows = []
    for name, provider, model, endpoint_id, config in result.all():
        parser = str(config.get("pdf_parser", "pymupdf"))
        # LlamaParse sends the whole document to LlamaCloud, and only a
        # collection naming its own vault key can: there is no deployment key.
        off_site = parser == "llamaparse" and config.get("llamaparse_secret_id") is not None
        rows.append(
            [
                name,
                provider,
                model,
                "local service" if endpoint_id else "provider API",
                parser,
                _yes_no(off_site),
            ]
        )
    return Section(
        title="Collections",
        note=(
            "Every chunk of every document and every retrieval query reaches the "
            "embedding provider named here. An off-site parse sends the whole "
            "document."
        ),
        headers=(
            "Collection",
            "Embeddings",
            "Model",
            "Reached at",
            "PDF parser",
            "Parses off-site",
        ),
        rows=rows,
    )


async def _local_services(db: AsyncSession) -> Section:
    """The hosts a collection or a model profile may be pointed at instead."""
    result = await db.execute(
        select(
            Organization.name,
            LocalService.kind,
            LocalService.provider,
            LocalService.name,
            LocalService.base_url,
            LocalService.is_active,
        )
        .outerjoin(Organization, Organization.id == LocalService.organization_id)
        .order_by(LocalService.kind, LocalService.name)
    )
    rows = [
        [org or "deployment-wide", kind, provider, name, base_url, _yes_no(is_active)]
        for org, kind, provider, name, base_url, is_active in result.all()
    ]
    return Section(
        title="Services on your own network",
        note="Every address here should be one the deployment runs. Verify each.",
        headers=("Organization", "Kind", "Provider", "Name", "Endpoint", "Active"),
        rows=rows,
    )


async def _external_connections(db: AsyncSession) -> Section:
    """MCP servers, sync sources and channel bots - the rest of what leaves."""
    rows: list[list[str]] = []

    mcp = await db.execute(
        select(McpConnection.scope, McpConnection.name, McpConnection.url, McpConnection.auth_type)
        .where(McpConnection.is_enabled.is_(True))
        .order_by(McpConnection.scope, McpConnection.name)
    )
    rows += [
        ["MCP server", f"{scope}/{name}", url, auth_type]
        for scope, name, url, auth_type in mcp.all()
    ]

    sources = await db.execute(
        select(SyncSource.connector_type, SyncSource.name, SyncSource.collection_name)
        .where(SyncSource.is_active.is_(True))
        .order_by(SyncSource.connector_type, SyncSource.name)
    )
    rows += [
        ["Sync source", name, connector, collection or "-"]
        for connector, name, collection in sources.all()
    ]

    bots = await db.execute(
        select(ChannelBot.platform, ChannelBot.name).order_by(ChannelBot.platform, ChannelBot.name)
    )
    rows += [["Channel bot", name, platform, "-"] for platform, name in bots.all()]

    return Section(
        title="Other configured destinations",
        note=(
            "Tool arguments and results reach an MCP server; a sync source pulls "
            "documents in under its own credential; a channel bot posts the "
            "agent's replies to the messaging vendor."
        ),
        headers=("Kind", "Name", "Destination", "Detail"),
        rows=rows,
    )


async def _tracing(db: AsyncSession) -> Section:
    """Which runs are traced, where to, and how much content the span carries."""
    rows: list[list[str]] = [
        [
            "deployment-wide",
            "every run in the API process",
            settings.LOGFIRE_BASE_URL if settings.LOGFIRE_TOKEN else "-",
            "set" if settings.LOGFIRE_TOKEN else "unset",
        ]
    ]

    agents = await db.execute(
        select(Agent.slug, AgentVersion.version, AgentVersion.spec)
        .join(AgentVersion, AgentVersion.id == Agent.current_version_id)
        .order_by(Agent.slug)
    )
    for slug, version, spec in agents.all():
        observability = spec.get("observability") or {}
        rows.append(
            [
                f"agent {slug}",
                f"v{version}",
                "own project" if observability.get("token_secret_id") else "-",
                f"content: {observability.get('content', 'full')}",
            ]
        )

    environments = await db.execute(
        select(Agent.slug, AgentEnvironment.name)
        .join(Agent, Agent.id == AgentEnvironment.agent_id)
        .where(AgentEnvironment.logfire_token_secret_id.is_not(None))
        .order_by(Agent.slug, AgentEnvironment.name)
    )
    rows += [
        [f"agent {slug}", f"environment {name}", "own project", "-"]
        for slug, name in environments.all()
    ]

    return Section(
        title="Tracing",
        note=(
            "A span carries the prompt, the output and every tool argument "
            "unless the agent's observability content is none. With no token "
            "anywhere, nothing is exported and the trace id is still recorded "
            "locally."
        ),
        headers=("Scope", "Version", "Exported to", "Content"),
        rows=rows,
    )


async def _retention(db: AsyncSession, older_than_days: int) -> Section:
    """How much of each store a retention schedule would have to reach."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    stores = (
        ("conversations", Conversation),
        ("agent_runs", AgentRun),
        ("chat_files", ChatFile),
        ("rag_documents", RAGDocument),
        ("agent_memory_files", AgentMemoryFile),
        ("sandbox_operations", SandboxOperation),
        ("app_admin_audit_logs", AppAdminAuditLog),
    )
    rows = []
    for label, model in stores:
        total = await db.scalar(select(func.count()).select_from(model))
        older = await db.scalar(
            select(func.count()).select_from(model).where(model.created_at < cutoff)
        )
        rows.append([label, total or 0, older or 0])
    return Section(
        title=f"Retention exposure (older than {older_than_days} days)",
        note=(
            "Counts only. Nothing here is swept on a schedule yet except "
            "sandbox_operations, so every number in the last column is data a "
            "decided retention period would already have removed."
        ),
        headers=("Store", "Rows", f"Older than {older_than_days}d"),
        rows=rows,
    )


def _walk_media(media_dir: Path) -> list[str]:
    """Every file under `media_dir`, relative, minus the by-design unreferenced."""
    if not media_dir.is_dir():
        return []
    found = []
    for path in sorted(media_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(media_dir).as_posix()
        if relative.startswith(UNREFERENCED_BY_DESIGN):
            continue
        found.append(relative)
    return found


async def _unreferenced_media(db: AsyncSession) -> Section:
    """Files under `MEDIA_DIR` that no row points at any more.

    The count is the visible edge of what `docs/data-protection.md` records
    under "What deletion reaches": a `chat_files` row cascades away with its
    message while the bytes stay, so this grows with every deleted conversation
    until #1421 removes them together.
    """
    referenced: set[str] = set()
    for column in MEDIA_PATH_COLUMNS:
        result = await db.execute(select(column).where(column.is_not(None)))
        referenced.update(str(value) for value in result.scalars().all())

    media_dir = Path(settings.MEDIA_DIR)
    orphans = [path for path in _walk_media(media_dir) if path not in referenced]
    rows: list[list[str]] = [[path] for path in orphans[:ORPHAN_SAMPLE]]
    if len(orphans) > ORPHAN_SAMPLE:
        rows.append([f"... and {len(orphans) - ORPHAN_SAMPLE} more"])
    return Section(
        title=f"Files on disk with no row ({len(orphans)} under {media_dir})",
        note=(
            "Generated images and the parse scratch directory are excluded - "
            "they have no row by design. Everything else here is bytes the "
            "product can no longer find, and cannot delete."
        ),
        headers=("Path",),
        rows=rows,
    )


async def _collect(older_than_days: int) -> list[Section]:
    async with get_db_context() as db:
        return [
            _settings_section(),
            await _model_destinations(db),
            await _credentials(db),
            await _collections(db),
            await _local_services(db),
            await _external_connections(db),
            await _tracing(db),
            await _retention(db, older_than_days),
            await _unreferenced_media(db),
        ]


def _render(section: Section) -> None:
    info("")
    success(f"## {section.title}")
    info(section.note)
    info("")
    if section.rows:
        info(tabulate(section.rows, headers=list(section.headers)))
    else:
        info("(none)")


@command(
    "data-protection-report",
    help="Print the configuration a data-protection review of this deployment asks for",
)
@click.option(
    "--older-than",
    "older_than_days",
    type=click.IntRange(min=1),
    default=365,
    show_default=True,
    help="The retention period to measure each store against, in days",
)
def data_protection_report(older_than_days: int) -> None:
    """Report where this deployment sends data, what it keeps and for how long.

    Prints configuration, never content: providers, endpoints, parsers, bots and
    row counts, with no message text, no document, no credential and no hint of
    one. Attach the output to a data-protection review beside the provider
    agreements `docs/data-protection.md` lists, which no command can produce.

    Example:
        agenticos cmd data-protection-report
        agenticos cmd data-protection-report --older-than 90
    """
    info(f"Data-protection report, {datetime.now(UTC).isoformat(timespec='seconds')}")
    for section in asyncio.run(_collect(older_than_days)):
        _render(section)
    info("")
    warning(
        "Configuration only. Whether each provider above is covered by a processing "
        "agreement, sits where this deployment needs it to sit and excludes the "
        "traffic from training is evidence to obtain - see docs/data-protection.md."
    )
