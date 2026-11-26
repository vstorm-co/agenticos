"""Which of a dataset's keys none of an agent's sources covers.

A person asks, for an agent and a dataset, which of the facts the dataset's
`keys` checks require the agent can find anywhere. A job gathers what the
published version's sources show for each key label - a search of every knowledge
base, the passages of context files and skills that name it, the tools of every
MCP server - and the source coverage agent judges each label from that alone.

The agent is shown labels and never a key's value, and the report keeps labels
and source names only. Sources the person who asked may not see are neither read
nor named; a reader who may not see a source the report names gets it unnamed.
"""

import logging
from collections.abc import Sequence, Set
from datetime import UTC, datetime
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.knowledge._search import search_knowledge_base
from app.agents.spec import AgentSpec, OrgMcpServerRef
from app.agents.system_agents import SOURCE_COVERAGE
from app.core.audit import record_audit
from app.core.exceptions import AppException, AuthenticationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentVersion
from app.db.models.dataset import Dataset
from app.db.models.key_coverage_report import CoverageStatus, KeyCoverageReport
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.mcp_connection import McpConnection
from app.db.session import get_worker_db_context
from app.repositories import (
    agent_repo,
    context_repo,
    dataset_repo,
    key_coverage_report_repo,
    knowledge_base_repo,
    mcp_connection_repo,
)
from app.schemas.agent import KnowledgeSource
from app.schemas.dataset_helpers import DatasetHelpers
from app.schemas.key_coverage import (
    CoverageItem,
    CoverageSource,
    JudgedCoverage,
    JudgedKey,
    KeyCoverageReportRead,
    StoredItem,
    StoredSource,
)
from app.schemas.scoring import MAX_KEYS
from app.services.agent_registry import AgentRegistryService
from app.services.api_key import job_context
from app.services.background_jobs import enqueue
from app.services.dataset import DatasetService
from app.services.knowledge_reach import KnowledgeReachService
from app.services.mcp_connection import presented_tool_names
from app.services.skills import SkillService
from app.services.system_agent_runner import SystemAgentRunner
from app.worker.jobs import REPORT_KEY_COVERAGE, ReportKeyCoverage

logger = logging.getLogger(__name__)

NO_KEYS = "This dataset has no keys checks to judge"
NOT_PUBLISHED = "Publish the agent first: a report reads the version it runs"
REQUESTER_GONE = "Whoever asked for this report is no longer a member."
STOPPED = "Judging the keys stopped before it finished. Ask again."
FAILED = "Judging the keys failed. Ask again."
SEARCH_FAILED = "Searching this knowledge base failed."
UNCHECKED_SERVER = "Nothing has reached this server yet, so its tools are unknown."

SEARCH_TOP_K = 3
"""Passages read from each knowledge base for each label."""
SEARCH_CHARS = 600
PASSAGES_PER_LABEL = 2
PASSAGE_CHARS = 300
PROMPT_CHARS = 120_000
"""What the agent is shown at most; material past it is cut and the prompt says so."""


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else f"{text[:limit]} [...]"


def _model_of(dataset: Dataset) -> UUID | None:
    return DatasetHelpers.model_validate(dataset.helper_settings or {}).generator.model_profile_id


def key_labels(checks_of_cases: list[list[dict[str, JsonValue]]]) -> list[str]:
    """Every key label the cases' `keys` checks hold, each once, in their order.

    A label is compared trimmed and without case, and the first spelling stands.
    Only labels are read: a key's value never leaves its case.
    """
    seen: set[str] = set()
    labels: list[str] = []
    for checks in checks_of_cases:
        for check in checks:
            if check.get("type") != "keys" or not isinstance(keys := check.get("keys"), list):
                continue
            for key in keys:
                label = key.get("key") if isinstance(key, dict) else None
                if not isinstance(label, str) or not label.strip():
                    continue
                if label.strip().casefold() in seen:
                    continue
                seen.add(label.strip().casefold())
                labels.append(label.strip())
                if len(labels) == MAX_KEYS:
                    return labels
    return labels


def passages(text: str, label: str) -> list[str]:
    """Up to `PASSAGES_PER_LABEL` stretches of `text` around where it names `label`."""
    folded, needle = text.casefold(), label.casefold()
    found: list[str] = []
    start = folded.find(needle)
    while start != -1 and len(found) < PASSAGES_PER_LABEL:
        begin = max(start - PASSAGE_CHARS // 2, 0)
        found.append(_clip(text[begin : begin + PASSAGE_CHARS], PASSAGE_CHARS))
        start = folded.find(needle, begin + PASSAGE_CHARS)
    return found


def settled_items(
    labels: list[str], judged: list[JudgedKey], sources: dict[str, KnowledgeSource]
) -> list[StoredItem]:
    """One item per label, in the labels' order, from what the agent judged.

    `sources` are the ones the agent was shown, by the reference it was given. A
    label the agent skipped is `unsure`, only those sources are kept, and
    `covered` without one of them is `unsure`: a verdict nobody can trace is not
    evidence.
    """
    by_label: dict[str, JudgedKey] = {}
    for verdict in judged:
        by_label.setdefault(verdict.key.strip().casefold(), verdict)
    items: list[StoredItem] = []
    for label in labels:
        verdict = by_label.get(label.casefold())
        if verdict is None:
            items.append(StoredItem(key=label, verdict="unsure", sources=[], why=None))
            continue
        named = [sources[ref] for ref in dict.fromkeys(verdict.source_ids) if ref in sources]
        outcome = verdict.verdict
        if outcome == "covered" and not named:
            outcome = "unsure"
        items.append(
            StoredItem(
                key=label,
                verdict=outcome,
                sources=[]
                if outcome == "not_covered"
                else [
                    StoredSource(kind=source.kind, id=source.id, name=source.name)
                    for source in named
                ],
                why=verdict.why.strip() or None,
            )
        )
    return items


def _bound(spec: AgentSpec, *, disabled: Set[UUID]) -> int:
    """The sources the published version reaches: every binding but a disabled server.

    A personal or platform MCP server counts too: its tools depend on who is asking,
    so a report never reads them, and they keep it from being complete.
    """
    servers = {ref.connection_id for ref in spec.mcp_servers if isinstance(ref, OrgMcpServerRef)}
    return (
        len(set(spec.collection_ids))
        + len(set(spec.skill_ids))
        + len(set(spec.context_ids))
        + len(servers - disabled)
        + sum(not isinstance(ref, OrgMcpServerRef) for ref in spec.mcp_servers)
    )


class KeyCoverageService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.datasets = DatasetService(db)
        self.agents = AgentRegistryService(db)

    async def start(
        self, ctx: AuthContext, dataset_id: UUID, agent_id: UUID
    ) -> KeyCoverageReportRead:
        """Ask which of the dataset's keys the agent's published sources cover. A job judges it.

        The pair's earlier report is replaced. The job is queued in this
        transaction, and checks the caller's access again when it runs.

        Raises:
            NotFoundError: The dataset or the agent, as their services report them.
            AuthorizationError: A visible agent the caller may not edit.
            BadRequestError: The agent was never published, or the dataset holds no keys.
            SystemAgentUnavailableError: The source coverage agent cannot run for this caller.
        """
        dataset = await self.datasets.get(ctx, dataset_id)
        agent = await self._editable_agent(ctx, agent_id)
        version = await self._published(ctx, agent)
        if not await self._labels(ctx, dataset, dataset.latest_version):
            raise BadRequestError(message=NO_KEYS, details={"dataset_id": dataset.id})
        # Refused here with the reason, rather than queued to fail at once.
        await SystemAgentRunner(self.db).require_runnable(
            ctx, key=SOURCE_COVERAGE.key, model_profile_id=_model_of(dataset)
        )
        report = await key_coverage_report_repo.replace(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            agent_version_id=version.id,
            dataset_id=dataset.id,
            dataset_version=dataset.latest_version,
            requested_by_user_id=ctx.subject_id,
            created_by_api_key_id=ctx.api_key_id,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.key_coverage_requested",
            target_type="agent",
            target_id=str(agent.id),
            details={"dataset_id": str(dataset.id), "dataset_version": dataset.latest_version},
        )
        await enqueue(
            self.db,
            REPORT_KEY_COVERAGE,
            ReportKeyCoverage(report_id=report.id, organization_id=ctx.organization_id),
            organization_id=ctx.organization_id,
        )
        return await self._read(ctx, agent, report, dataset)

    async def get(
        self, ctx: AuthContext, dataset_id: UUID, agent_id: UUID
    ) -> KeyCoverageReportRead:
        """The pair's report, naming only the sources the caller may see.

        Raises:
            NotFoundError: The dataset or the agent, as their services report them,
                or the pair has no report.
        """
        dataset = await self.datasets.get(ctx, dataset_id)
        agent = await self.agents.get(ctx, agent_id)
        report = await key_coverage_report_repo.get_for(
            self.db, organization_id=ctx.organization_id, agent_id=agent.id, dataset_id=dataset.id
        )
        if report is None:
            raise NotFoundError(
                message="This agent has no coverage report for this dataset",
                details={"agent_id": agent.id, "dataset_id": dataset.id},
            )
        return await self._read(ctx, agent, report, dataset)

    async def uncovered_labels(
        self, ctx: AuthContext, agent_id: UUID, dataset_ids: list[UUID]
    ) -> dict[UUID, frozenset[str]]:
        """The labels the agent's ready reports found no source for, by dataset, without case.

        A report whose sources changed since it was judged is left out with the rest
        that no longer describe what the agent reaches.
        """
        reports = await key_coverage_report_repo.ready_for_agent(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id, dataset_ids=dataset_ids
        )
        changed = await self._changed(ctx.organization_id, reports)
        return {
            report.dataset_id: frozenset(
                str(item["key"]).casefold()
                for item in report.items
                if item.get("verdict") == "not_covered"
            )
            for report in reports
            if report.id not in changed
        }

    async def _changed(
        self, organization_id: UUID, reports: Sequence[KeyCoverageReport]
    ) -> set[UUID]:
        """The reports whose sources hold something else now than when they were judged."""
        now = await key_coverage_report_repo.source_marks(
            self.db,
            organization_id=organization_id,
            source_ids={UUID(source) for report in reports for source in report.judged_sources},
        )
        return {
            report.id
            for report in reports
            if any(
                report.source_marks.get(source) != now.get(UUID(source))
                for source in report.judged_sources
            )
        }

    async def judge(self, report_id: UUID, organization_id: UUID) -> None:
        """Judge a report that is still running, and record how it went.

        Never raises: a refusal is the report's `error`, and the run the source
        coverage agent made - its cost included - is linked to the report whether
        it answered or not.
        """
        report = await key_coverage_report_repo.get(
            self.db, report_id, organization_id=organization_id
        )
        if report is None or report.status != CoverageStatus.RUNNING.value:
            return
        try:
            ctx = await job_context(
                self.db,
                organization_id=organization_id,
                user_id=report.requested_by_user_id,
                api_key_id=report.created_by_api_key_id,
            )
        except AuthenticationError as exc:
            await self._fail(report_id, organization_id, exc.message)
            return
        if ctx is None:
            await self._fail(report_id, organization_id, REQUESTER_GONE)
            return
        try:
            dataset = await self.datasets.get(ctx, report.dataset_id)
            agent = await self._editable_agent(ctx, report.agent_id)
            spec = AgentSpec.model_validate((await self._version(ctx, report)).spec)
            labels = await self._labels(ctx, dataset, report.dataset_version)
            if not labels:
                raise BadRequestError(message=NO_KEYS, details={"dataset_id": dataset.id})
        except AppException as exc:
            await self._fail(report_id, organization_id, exc.message)
            return
        reach = await KnowledgeReachService(self.db).for_spec(ctx, agent, spec)
        disabled = await self._disabled_servers(ctx, spec)
        reachable = [s for s in reach.sources if not (s.kind == "mcp" and s.id in disabled)]
        sources = {f"S{number}": source for number, source in enumerate(reachable, start=1)}
        runner = SystemAgentRunner(self.db)
        try:
            material = await self._material(ctx, spec, sources, labels)
            marks = await key_coverage_report_repo.source_marks(
                self.db,
                organization_id=organization_id,
                source_ids=[source.id for source in sources.values()],
            )
            result = await runner.run(
                ctx,
                key=SOURCE_COVERAGE.key,
                model_profile_id=_model_of(dataset),
                prompt=_prompt(labels, material),
                output_type=JudgedCoverage,
            )
        except AppException as exc:
            await self._fail(
                report_id, organization_id, exc.message, run_id=getattr(exc, "run_id", None)
            )
            return
        except Exception:
            logger.exception("key_coverage_failed", extra={"report_id": str(report_id)})
            await self.db.rollback()
            await self._fail(report_id, organization_id, FAILED, run_id=runner.failed_run_id)
            return
        await key_coverage_report_repo.finish(
            self.db,
            report_id,
            organization_id=organization_id,
            status=CoverageStatus.READY,
            finished_at=datetime.now(UTC),
            items=[
                item.model_dump(mode="json")
                for item in settled_items(labels, result.output.keys, sources)
            ],
            unseen_sources=max(_bound(spec, disabled=disabled) - len(sources), 0),
            judged_sources=[source.id for source in sources.values()],
            source_marks=marks,
            run_id=result.run.id,
        )

    async def _disabled_servers(self, ctx: AuthContext, spec: AgentSpec) -> set[UUID]:
        """The organization MCP servers the version binds that are switched off: no source."""
        servers = await mcp_connection_repo.get_org_scoped_by_ids(
            self.db,
            connection_ids=[
                ref.connection_id for ref in spec.mcp_servers if isinstance(ref, OrgMcpServerRef)
            ],
            organization_id=ctx.organization_id,
        )
        return {server_id for server_id, server in servers.items() if not server.is_enabled}

    async def _editable_agent(self, ctx: AuthContext, agent_id: UUID) -> Agent:
        return await self.agents.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)

    async def _published(self, ctx: AuthContext, agent: Agent) -> AgentVersion:
        version = (
            None
            if agent.current_version_id is None
            else await agent_repo.get_version(
                self.db, agent.current_version_id, organization_id=ctx.organization_id
            )
        )
        if version is None:
            raise BadRequestError(message=NOT_PUBLISHED, details={"agent_id": agent.id})
        return version

    async def _version(self, ctx: AuthContext, report: KeyCoverageReport) -> AgentVersion:
        version = await agent_repo.get_version(
            self.db, report.agent_version_id, organization_id=ctx.organization_id
        )
        # A report is deleted with its version (`ON DELETE CASCADE`).
        assert version is not None
        return version

    async def _labels(self, ctx: AuthContext, dataset: Dataset, number: int) -> list[str]:
        version = await dataset_repo.get_version(
            self.db, dataset.id, number, organization_id=ctx.organization_id
        )
        if version is None:
            return []
        cases = await dataset_repo.list_cases(
            self.db, version.id, organization_id=ctx.organization_id, limit=None
        )
        return key_labels([case.checks or [] for case in cases])

    async def _material(
        self,
        ctx: AuthContext,
        spec: AgentSpec,
        sources: dict[str, KnowledgeSource],
        labels: list[str],
    ) -> list[str]:
        """What each source shows for the labels, a block per source."""
        org = ctx.organization_id
        ids = {
            kind: [s.id for s in sources.values() if s.kind == kind]
            for kind in ("collection", "skill", "context", "mcp")
        }
        bases = {
            kb.id: kb
            for kb in await knowledge_base_repo.get_in_organization(
                self.db, ids["collection"], organization_id=org
            )
        }
        # As the run reads them: the main version or fork each binding names.
        skills = {
            skill.id: skill
            for skill in await SkillService(self.db).resolve_for_agent(
                ctx,
                [skill_id for skill_id in spec.skill_ids if skill_id in ids["skill"]],
                bindings=spec.skill_bindings,
            )
        }
        contexts = await context_repo.get_many(self.db, ids["context"], organization_id=org)
        servers = await mcp_connection_repo.get_org_scoped_by_ids(
            self.db, connection_ids=ids["mcp"], organization_id=org
        )
        bindings = {
            ref.connection_id: ref.allowed_tools
            for ref in spec.mcp_servers
            if isinstance(ref, OrgMcpServerRef)
        }
        blocks: list[str] = []
        for ref, source in sources.items():
            if source.kind == "collection":
                lines = await self._searched(bases[source.id], labels)
            elif source.kind == "mcp":
                lines = _tools(servers[source.id], bindings.get(source.id))
            else:
                row = skills[source.id] if source.kind == "skill" else contexts[source.id]
                lines = _mentions(row.description, row.content, labels)
            heading = f"## {ref} - {_KIND_NAMES[source.kind]} {source.name!r}"
            blocks.append("\n".join([heading, *lines]))
        return blocks

    async def _searched(self, kb: KnowledgeBase, labels: list[str]) -> list[str]:
        """What a search of the knowledge base returns for each label.

        Searched under the base's own scope: a collection name is not unique, and
        resolved by name alone it could read another base the requester may not.
        A base that cannot be searched - no embedding key, a store that is down -
        is said to be, rather than failing the report: the rest still count.
        """
        lines = _described(kb.description)
        for label in labels:
            try:
                found = await search_knowledge_base(
                    label,
                    kb_collection_names=[kb.collection_name],
                    kb_vector_scopes={kb.collection_name: kb.vector_scope},
                    organization_id=kb.organization_id,
                    top_k=SEARCH_TOP_K,
                )
            except Exception:
                logger.exception(
                    "key_coverage_search_failed", extra={"knowledge_base_id": str(kb.id)}
                )
                return [*lines, SEARCH_FAILED]
            lines.append(f"Search for {label!r}:\n{_clip(found, SEARCH_CHARS)}")
        return lines

    async def _read(
        self, ctx: AuthContext, agent: Agent, report: KeyCoverageReport, dataset: Dataset
    ) -> KeyCoverageReportRead:
        visible = await self._visible_sources(ctx, agent, report)
        changed = bool(await self._changed(ctx.organization_id, [report]))
        reasons = all(UUID(source) in visible for source in report.judged_sources)
        items: list[CoverageItem] = []
        for raw in report.items:
            stored = StoredItem.model_validate(raw)
            items.append(
                CoverageItem(
                    key=stored.key,
                    verdict=stored.verdict,
                    sources=[
                        CoverageSource(kind=shown.kind, id=shown.id, name=shown.name)
                        if (shown := visible.get(source.id))
                        else CoverageSource(kind=source.kind, id=None, name=None)
                        for source in stored.sources
                    ],
                    why=stored.why if reasons else None,
                )
            )
        return KeyCoverageReportRead.model_validate(
            {
                "id": report.id,
                "agent_id": report.agent_id,
                "dataset_id": report.dataset_id,
                "dataset_version": report.dataset_version,
                "status": report.status,
                "items": items,
                "unseen_sources": report.unseen_sources,
                "current": report.agent_version_id == agent.current_version_id
                and report.dataset_version == dataset.latest_version
                and not changed,
                "sources_changed": changed,
                "error": report.error,
                "created_at": report.created_at,
                "finished_at": report.finished_at,
            }
        )

    async def _visible_sources(
        self, ctx: AuthContext, agent: Agent, report: KeyCoverageReport
    ) -> dict[UUID, KnowledgeSource]:
        """The judged version's sources this reader may see, by id, as the Builder shows them."""
        if not report.judged_sources:
            return {}
        version = await self._version(ctx, report)
        reach = await KnowledgeReachService(self.db).for_spec(
            ctx, agent, AgentSpec.model_validate(version.spec)
        )
        return {source.id: source for source in reach.sources}

    async def _fail(
        self, report_id: UUID, organization_id: UUID, error: str, *, run_id: UUID | None = None
    ) -> None:
        await key_coverage_report_repo.finish(
            self.db,
            report_id,
            organization_id=organization_id,
            status=CoverageStatus.FAILED,
            finished_at=datetime.now(UTC),
            error=error[:500],
            run_id=run_id,
        )


_KIND_NAMES = {
    "collection": "knowledge base",
    "skill": "skill",
    "context": "context file",
    "mcp": "MCP server",
}


def _described(description: str | None) -> list[str]:
    return [f"Description: {_clip(description, PASSAGE_CHARS)}"] if description else []


def _mentions(description: str | None, content: str, labels: list[str]) -> list[str]:
    lines = _described(description)
    for label in labels:
        lines += [f"Mentions {label!r}: {text}" for text in passages(content, label)]
    return lines


def _tools(server: McpConnection, binding: list[str] | None) -> list[str]:
    """The tools the agent is given of `server`, by the name it calls them, and what each does."""
    if server.last_tools is None:
        return [UNCHECKED_SERVER]
    described = {tool["name"]: str(tool.get("description") or "") for tool in server.last_tools}
    return [
        f"Tool {shown}: {_clip(described[name], PASSAGE_CHARS)}"
        for name, shown in presented_tool_names(server, binding)
    ]


def _prompt(labels: list[str], blocks: list[str]) -> str:
    head = "Labels to judge:\n" + "\n".join(f"- {label}" for label in labels)
    body = "\n\n".join(blocks) if blocks else "The agent has no sources."
    text = f"{head}\n\nSources:\n\n{body}"
    if len(text) <= PROMPT_CHARS:
        return text
    return f"{text[:PROMPT_CHARS]}\n\n[The rest of the material was cut for length.]"


async def report_key_coverage(report_id: UUID, organization_id: UUID) -> None:
    """The job: judge one report in a session of its own."""
    async with get_worker_db_context() as db:
        await KeyCoverageService(db).judge(report_id, organization_id)


async def settle_lost(report_id: UUID, organization_id: UUID) -> None:
    """Fail a report whose job ended for good while it was still running.

    A worker killed under the job cannot mark the report itself, and nothing else
    would ever finish it. A report the job already ended is left as it is.
    """
    async with get_worker_db_context() as db:
        await key_coverage_report_repo.finish(
            db,
            report_id,
            organization_id=organization_id,
            status=CoverageStatus.FAILED,
            finished_at=datetime.now(UTC),
            error=STOPPED,
        )
