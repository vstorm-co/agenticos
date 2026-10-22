"""Carrying out an Improve or Verify: read the evidence, ask the improver, record what it proposes.

Runs in the worker, not in the request that started it - a request reads up to
twenty runs and makes several model calls. Every call is an ordinary run of the
organization's improver through :class:`SystemAgentRunner`: budget-checked
before it is made, priced, and listed in Activity.

**Map, then reduce.** Evidence that fits the improver's budget is read in one
call. Past it, each group of runs is digested first - what went wrong, with
quotes - and the proposal is written from the digests. Every quote, the
digests' and the proposal's, is checked against the runs before it is kept.

**Nothing changes an agent.** An improve records a batch of hunks for the draft
- or a skill or context file proposal - and a person decides each; a verify adds its findings
to the open batch without replacing what is still waiting there.
"""

import difflib
import json
import logging
from collections import Counter
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import REGISTRY, TOOL_NAME_PATTERN, ToolOverride, load_builtins
from app.agents.spec import AgentSpec
from app.agents.system_agents import IMPROVER
from app.core.exceptions import AppException, SystemAgentOutputError, SystemAgentRunError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.authoring import (
    AuthoringKind,
    AuthoringRequest,
    AuthoringStatus,
    AuthoringTarget,
    BatchStatus,
    HunkKind,
    HunkOrigin,
    HunkStatus,
)
from app.db.models.context import ContextFile
from app.db.models.skill import Skill
from app.db.session import get_worker_db_context
from app.repositories import (
    agent_repo,
    agent_run_repo,
    authoring_repo,
    context_proposal_repo,
    context_repo,
    member_repo,
    skill_proposal_repo,
    skill_repo,
)
from app.schemas.authoring import (
    MAX_REJECTED,
    ContextImprovement,
    EvidenceQuote,
    FieldChange,
    ImprovementProposal,
    InstructionChange,
    Rejection,
    RunFindings,
    SkillImprovement,
    ToolChange,
    VerifyReport,
)
from app.services import authoring_hunks
from app.services.access import AGENT, CONTEXT, SKILL, resolve_access
from app.services.authoring_config import ConfigurationService
from app.services.authoring_evidence import (
    EvidencePack,
    EvidenceService,
    PackedRun,
    render_runs,
)
from app.services.system_agent_runner import SystemAgentRunner

logger = logging.getLogger(__name__)

type Sessions = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class Stopped(Exception):
    """A request that cannot go on, with the reason the person reads."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def tool_catalog(spec: AgentSpec) -> list[tuple[str, str, str, str]]:
    """Every tool the spec binds, as `(capability_id, tool_id, name, description)`.

    The stable id is what a proposal names: the model reads effective names, but
    an override is keyed on the id, and a tool not yet overridden has only that.
    """
    load_builtins()
    rows: list[tuple[str, str, str, str]] = []
    for binding in spec.capabilities:
        definition = REGISTRY.get(binding.id)
        if definition is None:
            continue
        for tool in definition.effective_tools(binding.tool_overrides):
            rows.append((binding.id, tool.id, tool.name, tool.description))
    return rows


def _evidence_section(pack: EvidencePack, digests: Sequence[RunFindings] | None) -> str:
    if digests is None:
        return render_runs(pack.runs)
    lines: list[str] = []
    for digest in digests:
        for finding in digest.findings:
            lines.append(f"- {finding.observation}")
            lines += [f'  - run {quote.run_id}: "{quote.quote}"' for quote in finding.evidence]
    return "\n".join(lines) or "(The runs showed nothing in particular.)"


def _tool_lines(spec: AgentSpec) -> str:
    return "\n".join(
        f"- {capability} / {tool}: {label} - {description}"
        for capability, tool, label, description in tool_catalog(spec)
    )


def _tool_diff(published: AgentSpec, draft: AgentSpec) -> str:
    """Each tool the edit added, removed, renamed or re-described, one line each."""
    before = {(row[0], row[1]): row[2:] for row in tool_catalog(published)}
    after = {(row[0], row[1]): row[2:] for row in tool_catalog(draft)}
    lines: list[str] = []
    for key in sorted(before.keys() | after.keys()):
        label = f"{key[0]} / {key[1]}"
        old, new = before.get(key), after.get(key)
        if old is None:
            lines.append(f"+ {label}: added")
        elif new is None:
            lines.append(f"- {label}: removed")
        elif old != new:
            lines.append(f"~ {label}: {old[0]} - {old[1]}\n  now: {new[0]} - {new[1]}")
    return "\n".join(lines)


_CONFIG_FIELDS = (
    "description",
    "model_profile_id",
    "model_settings",
    "max_steps",
    "capabilities",
    "collection_ids",
    "context_ids",
    "mcp_servers",
)


def _config_diff(published: AgentSpec, draft: AgentSpec) -> str:
    """Each configuration field the edit changed, before and after, one line each."""
    before, after = published.model_dump(mode="json"), draft.model_dump(mode="json")
    return "\n".join(
        f"~ {field}: {json.dumps(before.get(field), sort_keys=True, default=str)}\n"
        f"  now: {json.dumps(after.get(field), sort_keys=True, default=str)}"
        for field in _CONFIG_FIELDS
        if before.get(field) != after.get(field)
    )


def _improve_prompt(
    name: str,
    spec: AgentSpec,
    configuration: str,
    pack: EvidencePack,
    digests: Sequence[RunFindings] | None,
) -> str:
    tools = _tool_lines(spec)
    return (
        f'Propose improvements to the agent "{name}".\n\n'
        f"# Its current instructions\n<instructions>\n{spec.instructions}\n</instructions>\n\n"
        f"# Its tools (capability_id / tool_id: name - description)\n{tools or '(none)'}\n\n"
        f"{configuration}\n\n"
        f"# What its runs show\n{_evidence_section(pack, digests)}"
    )


def _skill_prompt(skill: Skill, pack: EvidencePack, digests: Sequence[RunFindings] | None) -> str:
    return (
        f'Propose an improved body for the skill "{skill.name}".\n\n'
        f"# Its description\n{skill.description}\n\n"
        f"# Its current body\n<skill>\n{skill.content}\n</skill>\n\n"
        f"# Runs that opened it\n{_evidence_section(pack, digests)}"
    )


def _context_prompt(
    file: ContextFile, pack: EvidencePack, digests: Sequence[RunFindings] | None
) -> str:
    how = (
        "It is put into every bound agent's instructions verbatim."
        if file.mode == "inject"
        else "Bound agents read it on demand, by its name and description."
    )
    return (
        f'Propose an improved body for the context file "{file.name}". {how}\n\n'
        f"# Its description\n{file.description or '(none)'}\n\n"
        f"# Its current body\n<context>\n{file.content}\n</context>\n\n"
        f"# Runs of the agents that use it\n{_evidence_section(pack, digests)}"
    )


def _verify_prompt(
    name: str,
    published: AgentSpec,
    draft: AgentSpec,
    configuration: str,
    pack: EvidencePack,
    digests: Sequence[RunFindings] | None,
) -> str:
    diff = "\n".join(
        difflib.unified_diff(
            published.instructions.splitlines(),
            draft.instructions.splitlines(),
            "published",
            "draft",
            lineterm="",
        )
    )
    return (
        f'A person edited the agent "{name}" by hand. Check their edits against the '
        "evidence: what the edits improve, what they risk, and what they removed that the "
        "evidence relied on. Propose changes only where the evidence asks for them.\n\n"
        f"# The edit to its instructions\n{diff or '(no change to the instructions)'}\n\n"
        f"# The edit to its tools\n{_tool_diff(published, draft) or '(no change to the tools)'}\n\n"
        "# The edit to its configuration\n"
        f"{_config_diff(published, draft) or '(no change to the configuration)'}\n\n"
        f"# The draft's instructions\n<instructions>\n{draft.instructions}\n</instructions>\n\n"
        "# The draft's tools (capability_id / tool_id: name - description)\n"
        f"{_tool_lines(draft) or '(none)'}\n\n"
        f"{configuration}\n\n"
        f"# What its runs show\n{_evidence_section(pack, digests)}"
    )


def _digest_prompt(subject: str, runs: Sequence[PackedRun]) -> str:
    return (
        f"Read these runs of {subject} and list what went wrong - and what went well where "
        "it explains a contrast - each with exact quotes.\n\n"
        f"{render_runs(runs)}"
    )


def _signature(values: dict[str, Any]) -> tuple[Any, ...]:
    return (
        values["kind"],
        values.get("old_text", ""),
        values.get("new_text", ""),
        values.get("capability_id"),
        values.get("tool_id"),
        values.get("new_name"),
        values.get("new_description"),
        values.get("path"),
        values.get("op"),
        json.dumps(values.get("new_value"), sort_keys=True, default=str),
    )


def _proposed(hunk: dict[str, Any]) -> dict[str, Any]:
    """A hunk's change in the words the model proposed it, as a rejection lists it."""
    if hunk["kind"] == HunkKind.TOOL_OVERRIDE.value:
        return {
            "capability_id": hunk["capability_id"],
            "tool_id": hunk["tool_id"],
            "name": hunk["new_name"],
            "description": hunk["new_description"],
            "rationale": hunk["rationale"],
        }
    if hunk["kind"] == HunkKind.SPEC_FIELD.value:
        return {
            "path": hunk["path"],
            "op": hunk["op"],
            "value": hunk["new_value"],
            "rationale": hunk["rationale"],
        }
    return {
        "old_text": hunk["old_text"],
        "new_text": hunk["new_text"],
        "rationale": hunk["rationale"],
    }


class AuthoringRun:
    """One request, carried out on one session as the person who started it."""

    def __init__(self, db: AsyncSession, ctx: AuthContext, request: AuthoringRequest) -> None:
        self.db = db
        self.ctx = ctx
        self.request = request
        self.runner = SystemAgentRunner(db)
        self.evidence = EvidenceService(db)
        self.configuration = ConfigurationService(db)
        self.cost = Decimal(0)
        self.run_ids: list[UUID] = []
        self.rejected: list[dict[str, Any]] = []

    async def _ask[T: BaseModel](self, prompt: str, output_type: type[T]) -> T:
        try:
            result = await self.runner.run(
                self.ctx, key=IMPROVER.key, prompt=prompt, output_type=output_type
            )
        except (SystemAgentRunError, SystemAgentOutputError) as exc:
            # The call was made and priced even though it gave no answer.
            run = await agent_run_repo.get_run(
                self.db, exc.run_id, organization_id=self.ctx.organization_id
            )
            await self._count(exc.run_id, Decimal(0) if run is None else run.cost_usd)
            raise
        await self._count(result.run.id, result.run.cost_usd)
        return result.output

    async def _count(self, run_id: UUID, cost: Decimal) -> None:
        self.run_ids.append(run_id)
        self.cost += cost
        await authoring_repo.update_request(
            self.db,
            request=self.request,
            values={
                "run_ids": list(self.run_ids),
                "cost_usd": self.cost,
                "heartbeat_at": datetime.now(UTC),
            },
        )

    async def _digests(self, pack: EvidencePack, subject: str) -> list[RunFindings] | None:
        """The groups' findings, quotes checked - or `None` when the runs are read whole."""
        groups = pack.groups()
        if len(groups) <= 1:
            return None
        digests: list[RunFindings] = []
        for group in groups:
            found = await self._ask(_digest_prompt(subject, group), RunFindings)
            for finding in found.findings:
                kept, _ = pack.verify(finding.evidence)
                finding.evidence = [EvidenceQuote.model_validate(item) for item in kept]
            digests.append(found)
        return digests

    async def execute(self) -> None:
        # Authority is read as it is now: what the starter could do when they
        # asked may have been taken away while the request waited.
        if not self.ctx.has(Perm.RUNS_VIEW):
            raise Stopped("Whoever started this may no longer read runs.")
        if self.request.target == AuthoringTarget.SKILL.value:
            await self._improve_skill()
        elif self.request.target == AuthoringTarget.CONTEXT.value:
            await self._improve_context()
        elif self.request.kind == AuthoringKind.VERIFY.value:
            await self._verify()
        else:
            await self._improve_agent()

    async def _target_agent(self) -> Agent | None:
        agent_id = self.request.agent_id
        org = self.ctx.organization_id
        agent = (
            None
            if agent_id is None
            else await agent_repo.get(self.db, agent_id, organization_id=org)
        )
        if agent is not None and not await resolve_access(
            self.db, self.ctx, agent, Perm.AGENTS_EDIT, resource_type=AGENT
        ):
            raise Stopped("Whoever started this may no longer edit the agent.")
        return agent

    async def _improve_agent(self) -> None:
        agent = await self._target_agent()
        if agent is None:
            raise Stopped("The agent is gone.")
        spec = AgentSpec.model_validate(agent.draft_spec)
        pack = await self.evidence.for_agent(
            self.ctx, agent.id, window_days=self.request.window_days
        )
        self._record_evidence(pack)
        digests = await self._digests(pack, f'the agent "{agent.name}"')
        configuration = await self.configuration.describe(self.ctx, spec)
        proposal = await self._ask(
            _improve_prompt(agent.name, spec, configuration, pack, digests), ImprovementProposal
        )
        hunks = [
            *self._instruction_hunks(spec, pack, proposal.instructions, HunkOrigin.IMPROVE),
            *self._tool_hunks(spec, pack, proposal.tools, HunkOrigin.IMPROVE),
            *await self._field_hunks(agent.id, spec, pack, proposal.fields, HunkOrigin.IMPROVE),
        ]
        recorded = await self._supersede_with(agent.id, pack, proposal.expected_effect, hunks)
        await self._finish(
            {
                "summary": proposal.summary,
                "expected_effect": proposal.expected_effect,
                "proposed": len(proposal.instructions) + len(proposal.tools) + len(proposal.fields),
                "recorded": recorded,
                **self._rejections(),
            }
        )

    async def _verify(self) -> None:
        agent = await self._target_agent()
        if agent is None or agent.current_version_id is None:
            raise Stopped("The agent has no published version to compare with.")
        version = await agent_repo.get_version(
            self.db, agent.current_version_id, organization_id=self.ctx.organization_id
        )
        if version is None:
            raise Stopped("The agent's published version is gone.")
        published = AgentSpec.model_validate(version.spec)
        draft = AgentSpec.model_validate(agent.draft_spec)
        pack = await self.evidence.for_agent(
            self.ctx, agent.id, window_days=self.request.window_days
        )
        self._record_evidence(pack)
        digests = await self._digests(pack, f'the agent "{agent.name}"')
        configuration = await self.configuration.describe(self.ctx, draft)
        report = await self._ask(
            _verify_prompt(agent.name, published, draft, configuration, pack, digests),
            VerifyReport,
        )
        findings: list[dict[str, Any]] = []
        for finding in report.findings:
            kept, dropped = pack.verify(finding.evidence)
            findings.append(
                {
                    "verdict": finding.verdict,
                    "text": finding.text,
                    "evidence": kept,
                    "evidence_dropped": dropped,
                }
            )
        hunks = [
            *self._instruction_hunks(draft, pack, report.instructions, HunkOrigin.VERIFY),
            *self._tool_hunks(draft, pack, report.tools, HunkOrigin.VERIFY),
            *await self._field_hunks(agent.id, draft, pack, report.fields, HunkOrigin.VERIFY),
        ]
        merged = await self._merge_into_open(agent.id, pack, hunks)
        proposed = len(report.instructions) + len(report.tools) + len(report.fields)
        await self._finish(
            {
                "findings": findings,
                "proposed": proposed,
                "recorded": merged,
                **self._rejections(),
            }
        )

    async def _improve_skill(self) -> None:
        skill_id = self.request.skill_id
        org = self.ctx.organization_id
        skill = (
            None
            if skill_id is None
            else await skill_repo.get(self.db, skill_id, organization_id=org)
        )
        if skill is None:
            raise Stopped("The skill is gone.")
        if not await resolve_access(
            self.db, self.ctx, skill, Perm.SKILLS_EDIT, resource_type=SKILL
        ):
            raise Stopped("Whoever started this may no longer edit the skill.")
        pack = await self.evidence.for_skill(
            self.ctx, skill.name, window_days=self.request.window_days
        )
        self._record_evidence(pack)
        digests = await self._digests(pack, f'agents using the skill "{skill.name}"')
        proposal = await self._ask(_skill_prompt(skill, pack, digests), SkillImprovement)
        kept, dropped = pack.verify(proposal.evidence)
        improver = await self.runner.agents.ensure(
            organization_id=self.ctx.organization_id, key=IMPROVER.key
        )
        values = {
            "description": proposal.description[:500],
            "content": proposal.content,
            "resources": {},
            "conversation_id": None,
        }
        existing = await skill_proposal_repo.get_pending_for_skill(
            self.db,
            organization_id=self.ctx.organization_id,
            skill_id=skill.id,
            name=skill.name,
            agent_id=improver.id,
        )
        proposal_row = (
            await skill_proposal_repo.replace_body(self.db, proposal=existing, **values)
            if existing is not None
            else await skill_proposal_repo.create(
                self.db,
                organization_id=self.ctx.organization_id,
                skill_id=skill.id,
                agent_id=improver.id,
                name=skill.name,
                **values,
            )
        )
        await skill_proposal_repo.annotate(
            self.db,
            proposal=proposal_row,
            values={
                "base_version": skill.version,
                "rationale": proposal.rationale,
                "evidence": kept,
                "evidence_dropped": dropped,
                "expected_effect": proposal.expected_effect,
                "authoring_request_id": self.request.id,
            },
        )
        await self._finish(
            {
                "summary": proposal.summary,
                "expected_effect": proposal.expected_effect,
                "skill_proposal_id": str(proposal_row.id),
            }
        )

    async def _improve_context(self) -> None:
        context_id = self.request.context_id
        org = self.ctx.organization_id
        file = (
            None
            if context_id is None
            else await context_repo.get(self.db, context_id, organization_id=org)
        )
        if file is None:
            raise Stopped("The context file is gone.")
        if not await resolve_access(
            self.db, self.ctx, file, Perm.CONTEXT_EDIT, resource_type=CONTEXT
        ):
            raise Stopped("Whoever started this may no longer edit the context file.")
        pack = await self.evidence.for_context(
            self.ctx, file.id, window_days=self.request.window_days
        )
        self._record_evidence(pack)
        digests = await self._digests(pack, f'agents using the context file "{file.name}"')
        proposal = await self._ask(_context_prompt(file, pack, digests), ContextImprovement)
        kept, dropped = pack.verify(proposal.evidence)
        values = {
            "base_updated_at": file.updated_at,
            "description": proposal.description[:500],
            "content": proposal.content,
            "rationale": proposal.rationale,
            "evidence": kept,
            "evidence_dropped": dropped,
            "expected_effect": proposal.expected_effect,
            "authoring_request_id": self.request.id,
        }
        existing = await context_proposal_repo.get_pending_for_context(
            self.db, organization_id=org, context_id=file.id
        )
        row = (
            await context_proposal_repo.update(self.db, proposal=existing, values=values)
            if existing is not None
            else await context_proposal_repo.create(
                self.db, organization_id=org, context_id=file.id, values=values
            )
        )
        await self._finish(
            {
                "summary": proposal.summary,
                "expected_effect": proposal.expected_effect,
                "context_proposal_id": str(row.id),
            }
        )

    def _record_evidence(self, pack: EvidencePack) -> None:
        self.request.evidence = pack.summary()
        if not pack.runs:
            raise Stopped(
                "Nothing to learn from yet: no run in this window was rated or failed. "
                "Widen the window, or come back once people have rated some answers."
            )

    def _instruction_hunks(
        self,
        spec: AgentSpec,
        pack: EvidencePack,
        changes: Sequence[InstructionChange],
        origin: HunkOrigin,
    ) -> list[dict[str, Any]]:
        hunks: list[dict[str, Any]] = []
        for change in changes:
            columns = authoring_hunks.anchor_change(spec.instructions, change)
            if isinstance(columns, Rejection):
                self._reject(
                    HunkKind.INSTRUCTIONS,
                    columns,
                    {
                        "old_text": change.old_text,
                        "new_text": change.new_text,
                        "after": change.after,
                        "rationale": change.rationale,
                    },
                )
                continue
            kept, dropped = pack.verify(change.evidence)
            hunks.append(
                {
                    **columns,
                    "kind": HunkKind.INSTRUCTIONS.value,
                    "origin": origin.value,
                    "rationale": change.rationale,
                    "evidence": kept,
                    "evidence_dropped": dropped,
                }
            )
        return hunks

    def _tool_hunks(
        self,
        spec: AgentSpec,
        pack: EvidencePack,
        changes: Sequence[ToolChange],
        origin: HunkOrigin,
    ) -> list[dict[str, Any]]:
        """Tool changes for tools the draft binds, with names a binding may take."""
        known = {(capability, tool) for capability, tool, _, _ in tool_catalog(spec)}
        hunks: list[dict[str, Any]] = []
        for change in changes:
            reason = self._tool_refusal(known, change)
            if reason is not None:
                self._reject(
                    HunkKind.TOOL_OVERRIDE,
                    reason,
                    {
                        "capability_id": change.capability_id,
                        "tool_id": change.tool_id,
                        "name": change.name,
                        "description": change.description,
                        "rationale": change.rationale,
                    },
                )
                continue
            _, base_name, base_description = authoring_hunks.current_override(
                spec, change.capability_id, change.tool_id
            )
            kept, dropped = pack.verify(change.evidence)
            hunks.append(
                {
                    "kind": HunkKind.TOOL_OVERRIDE.value,
                    "origin": origin.value,
                    "capability_id": change.capability_id,
                    "tool_id": change.tool_id,
                    "base_name": base_name,
                    "base_description": base_description,
                    "new_name": change.name,
                    "new_description": change.description,
                    "rationale": change.rationale,
                    "evidence": kept,
                    "evidence_dropped": dropped,
                }
            )
        return hunks

    @staticmethod
    def _tool_refusal(known: set[tuple[str, str]], change: ToolChange) -> Rejection | None:
        if (change.capability_id, change.tool_id) not in known:
            return Rejection.UNKNOWN_TOOL
        if change.name is None and change.description is None:
            return Rejection.NO_CHANGE
        if change.name is not None and not TOOL_NAME_PATTERN.fullmatch(change.name):
            return Rejection.INVALID_TOOL_CHANGE
        try:
            ToolOverride(name=change.name, description=change.description)
        except ValidationError:
            return Rejection.INVALID_TOOL_CHANGE
        return None

    async def _field_hunks(
        self,
        agent_id: UUID,
        spec: AgentSpec,
        pack: EvidencePack,
        changes: Sequence[FieldChange],
        origin: HunkOrigin,
    ) -> list[dict[str, Any]]:
        hunks, refused = await self.configuration.stage(
            self.ctx, agent_id=agent_id, spec=spec, changes=changes, pack=pack, origin=origin
        )
        for change, reason in refused:
            self._reject(
                HunkKind.SPEC_FIELD,
                reason,
                {
                    "path": change.path,
                    "op": change.op,
                    "value": change.value,
                    "rationale": change.rationale,
                },
            )
        return hunks

    def _reject(self, kind: HunkKind, reason: Rejection, change: dict[str, Any]) -> None:
        self.rejected.append({"kind": kind.value, "reason": reason.value, "change": change})

    def _rejections(self) -> dict[str, Any]:
        """What the report says about the changes nothing recorded, and the log line for them.

        The changes are the model's own words without the quotes they cite, so the
        report's readers - those who read the suggestions - see no more than they would.
        """
        if not self.rejected:
            return {}
        dropped = dict(Counter(item["reason"] for item in self.rejected))
        logger.warning(
            "authoring_changes_rejected",
            extra={"request": str(self.request.id), "rejected": dropped},
        )
        return {
            "dropped": dropped,
            "rejected": self.rejected[:MAX_REJECTED],
            "rejected_more": max(0, len(self.rejected) - MAX_REJECTED),
        }

    async def _supersede_with(
        self, agent_id: UUID, pack: EvidencePack, expected_effect: str, hunks: list[dict[str, Any]]
    ) -> int:
        """Replace the open batch with this request's - unless a newer request already did.

        A change somebody dismissed in the batch being replaced is not proposed again.
        """
        started = self.request.started_at or self.request.created_at
        await self._serialize(agent_id)
        current = await authoring_repo.get_open_batch(
            self.db, organization_id=self.ctx.organization_id, agent_id=agent_id, lock=True
        )
        if current is not None:
            if current.source_started_at > started:
                return 0
            dismissed = {
                _signature(
                    {
                        "kind": hunk.kind,
                        "old_text": hunk.old_text,
                        "new_text": hunk.new_text,
                        "capability_id": hunk.capability_id,
                        "tool_id": hunk.tool_id,
                        "new_name": hunk.new_name,
                        "new_description": hunk.new_description,
                        "path": hunk.path,
                        "op": hunk.op,
                        "new_value": hunk.new_value,
                    }
                )
                for hunk in await authoring_repo.list_hunks(
                    self.db, organization_id=self.ctx.organization_id, batch_id=current.id
                )
                if hunk.status == HunkStatus.DISMISSED.value
            }
            for hunk in hunks:
                if _signature(hunk) in dismissed:
                    self._reject(
                        HunkKind(hunk["kind"]), Rejection.DISMISSED_BEFORE, _proposed(hunk)
                    )
            hunks = [hunk for hunk in hunks if _signature(hunk) not in dismissed]
            await authoring_repo.close_batch(self.db, batch=current, status=BatchStatus.SUPERSEDED)
        batch = await authoring_repo.create_batch(
            self.db,
            organization_id=self.ctx.organization_id,
            agent_id=agent_id,
            request_id=self.request.id,
            source_started_at=started,
            expected_effect=expected_effect,
            evidence_conversation_ids=pack.conversation_ids,
        )
        await authoring_repo.add_hunks(
            self.db, organization_id=self.ctx.organization_id, batch_id=batch.id, hunks=hunks
        )
        return len(hunks)

    async def _merge_into_open(
        self, agent_id: UUID, pack: EvidencePack, hunks: list[dict[str, Any]]
    ) -> int:
        """Add verify's changes to the open batch, opening one when there is none.

        Verify is offered while Improve's suggestions may still wait, so it adds
        to them rather than replacing them.
        """
        if not hunks:
            return 0
        await self._serialize(agent_id)
        batch = await authoring_repo.get_open_batch(
            self.db, organization_id=self.ctx.organization_id, agent_id=agent_id, lock=True
        )
        if batch is None:
            batch = await authoring_repo.create_batch(
                self.db,
                organization_id=self.ctx.organization_id,
                agent_id=agent_id,
                request_id=self.request.id,
                source_started_at=self.request.started_at or self.request.created_at,
                expected_effect="",
                evidence_conversation_ids=pack.conversation_ids,
            )
        else:
            merged = list(dict.fromkeys([*batch.evidence_conversation_ids, *pack.conversation_ids]))
            await authoring_repo.update_batch(
                self.db, batch=batch, values={"evidence_conversation_ids": merged}
            )
        await authoring_repo.add_hunks(
            self.db, organization_id=self.ctx.organization_id, batch_id=batch.id, hunks=hunks
        )
        return len(hunks)

    async def _serialize(self, agent_id: UUID) -> None:
        """Lock the agent, so two requests finishing at once do not both open a batch.

        The open batch is unique per agent, and there may be no batch row yet to lock.
        """
        await agent_repo.lock(self.db, agent_id, organization_id=self.ctx.organization_id)

    async def _finish(self, report: dict[str, Any]) -> None:
        await authoring_repo.update_request(
            self.db,
            request=self.request,
            values={
                "status": AuthoringStatus.COMPLETED.value,
                "report": report,
                "evidence": self.request.evidence,
                "finished_at": datetime.now(UTC),
            },
        )


async def creator(db: AsyncSession, request: AuthoringRequest) -> AuthContext | None:
    """The starter's authority as it is now, or `None` once they left the organization."""
    user_id = request.created_by_user_id
    membership = (
        None
        if user_id is None
        else await member_repo.get_active(
            db, organization_id=request.organization_id, user_id=user_id
        )
    )
    if user_id is None or membership is None:
        return None
    return AuthContext(
        user_id=user_id,
        organization_id=request.organization_id,
        role=membership.role,
        subject_is_publisher_fallback=True,
    )


class AuthoringWorker:
    """Carries one request to its end, recording why when it cannot."""

    def __init__(
        self,
        request_id: UUID,
        organization_id: UUID,
        *,
        sessions: Sessions = get_worker_db_context,
    ) -> None:
        self.request_id = request_id
        self.organization_id = organization_id
        self.sessions = sessions

    async def run(self) -> None:
        async with self.sessions() as db:
            request = await authoring_repo.get_request(
                db, self.request_id, organization_id=self.organization_id
            )
            if request is None or request.status != AuthoringStatus.QUEUED.value:
                return
            ctx = await creator(db, request)
            if ctx is None:
                await self._fail(db, request, "Whoever started this is no longer a member.")
                return
            await authoring_repo.update_request(
                db,
                request=request,
                values={"status": AuthoringStatus.RUNNING.value, "started_at": datetime.now(UTC)},
            )
            try:
                await AuthoringRun(db, ctx, request).execute()
            except Stopped as exc:
                await self._fail(db, request, exc.reason)
            except AppException as exc:
                await self._fail(db, request, exc.message)
            except Exception:
                logger.exception("authoring_request_failed", extra={"request": str(request.id)})
                await self._fail(db, request, "The assistant stopped unexpectedly. Try again.")

    @staticmethod
    async def _fail(db: AsyncSession, request: AuthoringRequest, error: str) -> None:
        await authoring_repo.update_request(
            db,
            request=request,
            values={
                "status": AuthoringStatus.FAILED.value,
                "error": error,
                "evidence": request.evidence,
                "finished_at": datetime.now(UTC),
            },
        )
