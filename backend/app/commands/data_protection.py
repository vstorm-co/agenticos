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
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import click
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from tabulate import tabulate

from app.commands import command, info, success, warning
from app.commands.vault_rotate import SEALED_TABLES
from app.core.config import settings
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_embed import AgentEmbed
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.agent_run import AgentRun
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.channel_bot import ChannelBot
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation
from app.db.models.credential import ModelProfile
from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.embed_visitor import EmbedVisitor
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

# Which capabilities send something out of the deployment when an agent runs
# with them, and where. A capability reaches the network without any row in
# `model_profiles`, `mcp_connections` or `sync_sources` naming its destination -
# `web_research` searches through DuckDuckGo with no credential at all - so a
# report built only from those tables claims an inventory it does not have.
#
# The value is the destination as a reviewer needs to read it: a fixed vendor
# where the capability has one, or what decides it where the configuration does.
# `tests/test_data_protection_report.py` asserts every registered capability is
# either named here or in `CAPABILITIES_STAYING_INSIDE`, so a new one fails a
# test rather than quietly leaving the inventory short.
OUTBOUND_CAPABILITIES: dict[str, str] = {
    "browser_use": "the browser service this deployment configures",
    "image_generation": "the image provider named in the binding",
    "knowledge": "the collection's embedding endpoint",
    "memory_mem0": "the mem0 host the binding names (MEM0_ALLOWED_HOSTS bounds it)",
    "sandbox": "the sandbox runtime this deployment configures",
    "web_fetch": "whatever address the model asks for",
    "web_research": "DuckDuckGo by default, or the search provider the binding names",
}

# Capabilities whose work never leaves the process, so they own no destination.
CAPABILITIES_STAYING_INSIDE = frozenset(
    {
        "channel_tools",
        "charts",
        "clock",
        "code_execution",
        "compaction",
        "context",
        "conversation_search",
        "guardrails",
        "memory_files",
        "planning",
        "skills",
        "subagents",
        "system_reminders",
        "thinking",
        "tool_output_limits",
        "tool_search",
    }
)

# Bytes a terminal acts on rather than prints. A tenant chooses some of the
# strings in this report - an MCP server's name, its URL - and an operator reads
# the result in a terminal, so CSI, OSC and the bidi overrides are encoded in
# every cell rather than passed through.
_ACTIONABLE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")


def _cell(value: object) -> str:
    """One cell, with anything the terminal would act on written out instead."""
    text = "" if value is None else str(value)
    return _ACTIONABLE.sub(lambda match: f"\\x{ord(match.group()):02x}", text)


def _endpoint(url: str) -> str:
    """A URL without its query string, which can be the credential itself.

    `/me/mcp-connections` takes any URL a member types and the validator refuses
    userinfo but not `?key=`, so printing one verbatim would put a live token in
    a report written to be attached to a review.
    """
    parts = urlsplit(url)
    if not parts.query:
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")) + "?<redacted>"


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
        # The selector first: with EMAIL_PROVIDER=log nothing is sent and the
        # three rows below describe a path nobody takes, and with `smtp` they
        # describe a hop that carries an address and a sign-in link.
        ["EMAIL_PROVIDER", settings.EMAIL_PROVIDER],
        ["SMTP_HOST", settings.SMTP_HOST],
        ["SMTP_PORT", str(settings.SMTP_PORT)],
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
    rows = [[org, purpose, kind, name] for org, purpose, kind, name in result.all()]

    # A sealed credential does not have to live in `organization_secrets`: a bot
    # token, an MCP connection's OAuth material and the rest are sealed in place,
    # in the tables `vault-rotate` re-wraps. Counting them here is what keeps
    # "one row per sealed credential" true; the value is never read, only the
    # number of rows holding one.
    for table in SEALED_TABLES:
        if table.model is OrganizationSecret:
            continue
        held = await db.scalar(select(func.count()).select_from(table.model))
        rows.append(
            ["-", f"{table.label} ({', '.join(table.columns)})", "sealed in place", held or 0]
        )

    return Section(
        title="Credentials held",
        note=(
            "One row per sealed credential. Each names a third party this "
            "deployment reaches and therefore needs an agreement with. The "
            "tables below organization_secrets seal their credential in place, "
            "so they are counted rather than listed."
        ),
        headers=("Organization", "Purpose", "Kind", "Name"),
        rows=rows,
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

    # `purpose` decides what a row in this table is. A portal grant is a Gmail
    # or GitHub authorization a trigger reads, not a server an agent calls, and
    # reporting one as an MCP server would tell a reviewer that tool arguments
    # reach an address nothing sends them to.
    mcp = await db.execute(
        select(McpConnection.scope, McpConnection.name, McpConnection.url, McpConnection.auth_type)
        .where(McpConnection.is_enabled.is_(True), McpConnection.purpose == "mcp")
        .order_by(McpConnection.scope, McpConnection.name)
    )
    rows += [
        ["MCP server", f"{scope}/{name}", _endpoint(url), auth_type]
        for scope, name, url, auth_type in mcp.all()
    ]

    portals = await db.execute(
        select(McpConnection.scope, McpConnection.name, McpConnection.portal_key)
        .where(McpConnection.is_enabled.is_(True), McpConnection.purpose == "portal")
        .order_by(McpConnection.portal_key, McpConnection.name)
    )
    rows += [
        ["Trigger portal", f"{scope}/{name}", portal_key or "-", "grant"]
        for scope, name, portal_key in portals.all()
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

    # A Mattermost or a self-hosted Slack-compatible server is wherever the
    # deployment says it is, so the platform label alone names no destination.
    bots = await db.execute(
        select(ChannelBot.platform, ChannelBot.name, ChannelBot.api_base_url).order_by(
            ChannelBot.platform, ChannelBot.name
        )
    )
    rows += [
        ["Channel bot", name, _endpoint(api_base_url) if api_base_url else platform, platform]
        for platform, name, api_base_url in bots.all()
    ]

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


async def _runnable_versions(db: AsyncSession) -> list[tuple[str, str, int, dict[str, Any]]]:
    """Every spec a run can actually use: the default, and each pinned one.

    `Agent.current_version_id` is only the default. A named environment pins
    its own `version_id`, and a run through that environment uses that spec -
    so reading the current version alone reports the settings of a version
    nobody may be running.
    """
    default = await db.execute(
        select(Agent.slug, AgentVersion.version, AgentVersion.spec)
        .join(AgentVersion, AgentVersion.id == Agent.current_version_id)
        .order_by(Agent.slug)
    )
    runnable: list[tuple[str, str, int, dict[str, Any]]] = [
        (slug, "default", version, spec) for slug, version, spec in default.all()
    ]

    pinned = await db.execute(
        select(Agent.slug, AgentEnvironment.name, AgentVersion.version, AgentVersion.spec)
        .join(Agent, Agent.id == AgentEnvironment.agent_id)
        .join(AgentVersion, AgentVersion.id == AgentEnvironment.version_id)
        .order_by(Agent.slug, AgentEnvironment.name)
    )
    runnable += [
        (slug, f"environment {name}", version, spec) for slug, name, version, spec in pinned.all()
    ]
    return runnable


async def _capability_destinations(db: AsyncSession) -> Section:
    """Where a capability sends something, with no row naming the address.

    Every other section in this report is built from a table: a model profile,
    an MCP connection, a sync source. A capability needs none of them -
    `web_research` searches through DuckDuckGo with no credential at all - so
    an inventory built only from those tables is short by exactly the
    capabilities an agent is running with.
    """
    rows: list[list[str]] = []
    for slug, where, version, spec in await _runnable_versions(db):
        for binding in spec.get("capabilities") or []:
            capability_id = binding.get("id") if isinstance(binding, dict) else None
            destination = OUTBOUND_CAPABILITIES.get(str(capability_id))
            if destination is None:
                continue
            rows.append([f"agent {slug}", f"{where} v{version}", str(capability_id), destination])
    return Section(
        title="Capability destinations",
        note=(
            "A capability reaches its own address with nothing in the tables "
            "above naming it. Only the versions that can run are listed: the "
            "default one, and each environment's pinned one."
        ),
        headers=("Agent", "Version", "Capability", "Reaches"),
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

    # Read off each *runnable* version, not the default one: an environment
    # pinned to another version traces under that version's observability, and
    # a row taken from the default would describe settings nothing is using.
    overrides = await db.execute(
        select(Agent.slug, AgentEnvironment.name)
        .join(Agent, Agent.id == AgentEnvironment.agent_id)
        .where(AgentEnvironment.logfire_token_secret_id.is_not(None))
        .order_by(Agent.slug, AgentEnvironment.name)
    )
    with_own_token = {(slug, f"environment {name}") for slug, name in overrides.all()}

    for slug, where, version, spec in await _runnable_versions(db):
        observability = spec.get("observability") or {}
        exported = (
            "own project"
            if observability.get("token_secret_id") or (slug, where) in with_own_token
            else "-"
        )
        rows.append(
            [
                f"agent {slug}",
                f"{where} v{version}",
                exported,
                f"content: {observability.get('content', 'full')}",
            ]
        )

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
        # Neither is reached by deleting a conversation. An embed visitor's key
        # outlives the conversation it pointed at (ON DELETE SET NULL), and a
        # user-scoped workspace holds its files under a string owner reference
        # no cascade follows.
        ("embed_visitors", EmbedVisitor),
        ("agent_workspaces", AgentWorkspace),
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

    # Counted per directory, never named. An upload keeps the original filename
    # in its stored path, so listing twenty of them would put "medical-results"
    # and a user id in a report written to be attached to a review - the one
    # thing this command says on its first line that it does not do.
    counts = Counter(PurePosixPath(path).parent.as_posix() or "." for path in orphans)
    rows: list[list[Any]] = [[directory, count] for directory, count in sorted(counts.items())]
    return Section(
        title=f"Files on disk with no row ({len(orphans)} under {media_dir})",
        note=(
            "Generated images and the parse scratch directory are excluded - "
            "they have no row by design. Everything else here is bytes the "
            "product can no longer find, and cannot delete. Directories and "
            "counts only: a stored path carries the original filename."
        ),
        headers=("Directory", "Files"),
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
            await _capability_destinations(db),
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
        safe = [[_cell(value) for value in row] for row in section.rows]
        info(tabulate(safe, headers=list(section.headers)))
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
