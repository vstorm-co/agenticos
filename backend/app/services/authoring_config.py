"""What the improver is told about an agent's configuration, and what it may add to it.

The instructions and tools are not all an agent is: the evidence often points at
the model, a capability configured too narrowly, a collection that is missing.
So the improver reads the configuration as the paths it may change
(:mod:`app.services.authoring_fields`), and - for anything it may *add* - only
what the person who asked may grant: their models, the collections and context
files they can read, the capabilities anybody may bind. A proposal naming
anything else is not staged, and the same check runs again for whoever accepts.

A change of model also says what it would cost: the agent's recent runs, their
tokens priced on both models. A handful of runs is a rough estimate and says so.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import REGISTRY, load_builtins
from app.agents.capabilities.budget import price_request
from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext, Perm
from app.db.models.authoring import HunkKind, HunkOrigin, SpecProposalHunk
from app.repositories import agent_run_repo, context_repo, credential_repo, mcp_connection_repo
from app.schemas.authoring import FieldChange
from app.services import authoring_fields
from app.services.access import CONTEXT, MCP_CONNECTION, accessible_ids
from app.services.agent_registry import AgentRegistryService
from app.services.authoring_evidence import EvidencePack
from app.services.context import ContextService
from app.services.knowledge_base import KnowledgeBaseService

logger = logging.getLogger(__name__)

COST_SAMPLE = 20
"""How many recent runs a model change is priced on."""

ROUGH_BELOW = 5
"""Fewer runs than this and the price of a model change is a rough estimate."""

_CATALOG_LIMIT = 40


def _uuids(values: set[str]) -> list[UUID]:
    found: list[UUID] = []
    for value in sorted(values):
        try:
            found.append(UUID(value))
        except ValueError:
            continue
    return found


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class ConfigurationService:
    """The configuration section of the improver's prompt, and staging what it proposes."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)

    async def describe(self, ctx: AuthContext, spec: AgentSpec) -> str:
        """The agent's configuration as changeable paths, and what the caller may add."""
        load_builtins()
        profiles = await credential_repo.list_profiles(self.db, organization_id=ctx.organization_id)
        labels = {
            str(profile.id): f"{profile.label} ({profile.provider}/{profile.model})"
            for profile in profiles
        }
        collections = {
            str(item.id): item.name
            for item in await KnowledgeBaseService(self.db).list_accessible(ctx)
        }
        contexts_page, _ = await ContextService(self.db).list_context(ctx, limit=_CATALOG_LIMIT)
        contexts = {str(item.id): f"{item.name} ({item.mode})" for item in contexts_page}
        document = spec.model_dump(mode="json")
        lines = [
            f"description: {_json(spec.description)}",
            f"model_profile_id: {spec.model_profile_id} - "
            f"{labels.get(str(spec.model_profile_id), 'not set')}",
            *(
                f"model_settings/{name}: {_json(getattr(spec.model_settings, name))}"
                for name in ("temperature", "top_p", "max_tokens", "timeout", "parallel_tool_calls")
            ),
            f"max_steps: {_json(spec.max_steps)}",
            *self._capability_lines(document),
            "collection_ids: "
            + _json(
                [
                    f"{item} ({collections.get(str(item), 'no access')})"
                    for item in spec.collection_ids
                ]
            ),
            "context_ids: "
            + _json(
                [f"{item} ({contexts.get(str(item), 'no access')})" for item in spec.context_ids]
            ),
            *await self._mcp_lines(ctx, document),
        ]
        bound = {binding.id for binding in spec.capabilities}
        grantable = [
            f"- {definition.id}: {definition.name} - {definition.description}"
            + (" (configurable)" if definition.tunable else "")
            for definition in REGISTRY.values()
            if definition.selectable and definition.id not in bound
        ]
        return (
            "# Its configuration (path: current value)\n"
            + "\n".join(lines)
            + "\n\n# What you may add - nothing else\n"
            + "Models (model_profile_id):\n"
            + ("\n".join(f"- {key}: {label}" for key, label in labels.items()) or "(none)")
            + "\nCollections (collection_ids):\n"
            + (
                "\n".join(
                    f"- {key}: {name}" for key, name in list(collections.items())[:_CATALOG_LIMIT]
                )
                or "(none)"
            )
            + "\nContext files (context_ids):\n"
            + ("\n".join(f"- {key}: {name}" for key, name in contexts.items()) or "(none)")
            + '\nCapabilities (capabilities, add as {"id": ..., "config": {...}}):\n'
            + ("\n".join(grantable) or "(none)")
            + "\n\n# Rules for configuration changes\n"
            "Change only the paths above, with ids only from these lists. Approval may only "
            "become stricter. A safeguard (guardrails) may be added, never removed or "
            "reconfigured. A config marked fixed never changes, and only a capability marked "
            "configurable may be added with a config; add any other without one. Subagents are never added or reconfigured; of a specialist, only "
            "its description may change. Every change states its expected effect on quality and on cost; "
            "a cheaper model must not cost quality the evidence shows the agent needs."
        )

    @staticmethod
    def _capability_lines(document: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        for binding in document.get("capabilities", []):
            capability = str(binding.get("id"))
            definition = REGISTRY.get(capability)
            writes = authoring_fields.writing_tools(capability)
            lines.append(
                f"capabilities/{capability}: {definition.name if definition else capability}"
                f" - config{'' if definition and definition.tunable else ' (fixed)'} "
                f"{_json(binding.get('config') or {})}, approval "
                f"{binding.get('approval', 'default')}, tool_approval "
                f"{_json(binding.get('tool_approval') or {})}"
                + (f", tools that write: {', '.join(writes)}" if writes else "")
            )
            if capability == "subagents":
                for specialist in (binding.get("config") or {}).get("inline", []):
                    lines.append(
                        f"capabilities/subagents/inline/{specialist.get('name')}/description: "
                        f"{_json(specialist.get('description'))}"
                    )
        return lines

    async def _mcp_lines(self, ctx: AuthContext, document: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        for ref in document.get("mcp_servers", []):
            key = authoring_fields.server_key(ref)
            tools = await self._server_tools(ctx, ref)
            listed = ", ".join(
                f"{tool['name']} ({'reads' if tool.get('read_only') else 'writes'})"
                for tool in tools
            )
            lines.append(
                f"mcp_servers/{key}/allowed_tools: {_json(ref.get('allowed_tools'))}"
                + (f" - the server offers: {listed}" if listed else "")
            )
        return lines

    async def _server_tools(self, ctx: AuthContext, ref: dict[str, Any]) -> list[dict[str, Any]]:
        """What an organization binding's server offered when it was last probed."""
        if ref.get("account", "organization") != "organization":
            return []
        connection = await mcp_connection_repo.get_org_scoped_by_id(
            self.db,
            connection_id=UUID(str(ref["connection_id"])),
            organization_id=ctx.organization_id,
        )
        return list(connection.last_tools or []) if connection is not None else []

    async def names(self, ctx: AuthContext, hunks: Sequence[SpecProposalHunk]) -> dict[str, str]:
        """What the field hunks refer to, by id, named only where the reader may see it.

        A model, a collection, a context file, an MCP connection or a capability a
        change adds or removes; anything the reader cannot see keeps only its id.
        """
        wanted: dict[str, set[str]] = {
            "model": set(),
            "collection": set(),
            "context": set(),
            "mcp": set(),
        }
        names: dict[str, str] = {}
        for hunk in hunks:
            if hunk.kind != HunkKind.SPEC_FIELD.value or hunk.path is None:
                continue
            values = [value for value in (hunk.base_value, hunk.new_value) if value is not None]
            if hunk.path == "model_profile_id":
                wanted["model"].update(str(value) for value in values)
            elif hunk.path == "collection_ids":
                wanted["collection"].update(str(value) for value in values)
            elif hunk.path == "context_ids":
                wanted["context"].update(str(value) for value in values)
            elif hunk.path.startswith("mcp_servers/"):
                wanted["mcp"].add(hunk.path.split("/")[1])
            elif hunk.path == "capabilities":
                for value in values:
                    capability = str(value.get("id") if isinstance(value, dict) else value)
                    definition = REGISTRY.get(capability)
                    if definition is not None:
                        names[capability] = definition.name
        names |= await self._model_names(ctx, wanted["model"])
        names |= await self._collection_names(ctx, wanted["collection"])
        names |= await self._context_names(ctx, wanted["context"])
        names |= await self._connection_names(ctx, wanted["mcp"])
        return names

    async def _model_names(self, ctx: AuthContext, ids: set[str]) -> dict[str, str]:
        profiles = await credential_repo.get_profiles_by_ids(
            self.db, _uuids(ids), organization_id=ctx.organization_id
        )
        return {str(key): profile.label for key, profile in profiles.items()}

    async def _collection_names(self, ctx: AuthContext, ids: set[str]) -> dict[str, str]:
        if not ids:
            return {}
        readable = await KnowledgeBaseService(self.db).list_accessible(ctx)
        return {str(item.id): item.name for item in readable if str(item.id) in ids}

    async def _context_names(self, ctx: AuthContext, ids: set[str]) -> dict[str, str]:
        files = await context_repo.get_many(
            self.db, _uuids(ids), organization_id=ctx.organization_id
        )
        visible = await accessible_ids(
            self.db, ctx, list(files.values()), Perm.CONTEXT_VIEW, resource_type=CONTEXT
        )
        return {str(key): file.name for key, file in files.items() if key in visible}

    async def _connection_names(self, ctx: AuthContext, ids: set[str]) -> dict[str, str]:
        connections = await mcp_connection_repo.get_org_scoped_by_ids(
            self.db, connection_ids=_uuids(ids), organization_id=ctx.organization_id
        )
        visible = await accessible_ids(
            self.db, ctx, list(connections.values()), Perm.MCP_MANAGE, resource_type=MCP_CONNECTION
        )
        return {str(key): row.name for key, row in connections.items() if key in visible}

    async def stage(
        self,
        ctx: AuthContext,
        *,
        agent_id: UUID,
        spec: AgentSpec,
        changes: Sequence[FieldChange],
        pack: EvidencePack,
        origin: HunkOrigin,
    ) -> list[dict[str, Any]]:
        """The hunks for the field changes that may be staged, as the caller.

        A change that does not stage - not a target, does not apply, loosens
        approval - or that adds something the caller may not grant is left out,
        and only counted.
        """
        hunks: list[dict[str, Any]] = []
        for change in changes:
            staged = authoring_fields.stage(spec, change.path, change.op, change.value)
            if isinstance(staged, str):
                logger.info("authoring_field_refused", extra={"reason": staged})
                continue
            base, new = staged
            applied = authoring_fields.apply(spec, change.path, change.op, base, new)
            assert applied is not None, "stage() applied it already"
            if await self.registry.reference_problems(ctx, applied, path=change.path, op=change.op):
                logger.info("authoring_field_not_grantable", extra={"path": change.path})
                continue
            kept, dropped = pack.verify(change.evidence)
            hunks.append(
                {
                    "kind": HunkKind.SPEC_FIELD.value,
                    "origin": origin.value,
                    "path": change.path,
                    "op": change.op,
                    "base_value": base,
                    "new_value": new,
                    "effect": await self._effect(ctx, agent_id, change.path, change.op, base, new),
                    "rationale": change.rationale,
                    "expected_effect": change.expected_effect,
                    "evidence": kept,
                    "evidence_dropped": dropped,
                }
            )
        return hunks

    async def _effect(
        self, ctx: AuthContext, agent_id: UUID, path: str, op: str, base: Any, new: Any
    ) -> dict[str, Any] | None:
        if path == "model_profile_id":
            return await self.cost(ctx, agent_id, base, new)
        if path == "capabilities" and op == "add":
            writes = authoring_fields.writing_tools(str(new.get("id")))
            return {"writes": writes} if writes else None
        if path.startswith("mcp_servers/"):
            return await self._mcp_writes(ctx, path, base, new)
        return None

    async def _mcp_writes(
        self, ctx: AuthContext, path: str, base: Any, new: Any
    ) -> dict[str, Any] | None:
        """The tools a widened MCP binding newly reaches that the server says write.

        `None` is every tool the connection allows, so widening to it reaches all
        the server offers, and narrowing from it reaches nothing new.
        """
        try:
            connection_id = UUID(path.split("/")[1])
        except ValueError:
            return None
        tools = await self._server_tools(
            ctx, {"account": "organization", "connection_id": connection_id}
        )
        offered = {str(tool["name"]) for tool in tools}
        reached = offered if new is None else set(new)
        before = offered if base is None else set(base)
        writes = sorted(
            str(tool["name"])
            for tool in tools
            if tool["name"] in reached - before and not tool.get("read_only")
        )
        return {"writes": writes} if writes else None

    async def cost(
        self, ctx: AuthContext, agent_id: UUID, before: Any, after: Any
    ) -> dict[str, Any]:
        """What one of the agent's recent runs would cost on each model.

        Recent runs' average tokens, priced on both: a model that is not priced
        says so with `None`, and fewer than `ROUGH_BELOW` runs is marked rough.
        """
        runs, input_tokens, output_tokens = await agent_run_repo.recent_usage(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id, sample=COST_SAMPLE
        )
        usage = RunUsage(input_tokens=round(input_tokens), output_tokens=round(output_tokens))
        return {
            "runs": runs,
            "rough": runs < ROUGH_BELOW,
            "cost_per_run_before": await self._price(ctx, before, usage, runs),
            "cost_per_run_after": await self._price(ctx, after, usage, runs),
        }

    async def _price(
        self, ctx: AuthContext, profile_id: Any, usage: RunUsage, runs: int
    ) -> str | None:
        if profile_id is None or runs == 0:
            return None
        profile = await credential_repo.get_profile(
            self.db, UUID(str(profile_id)), organization_id=ctx.organization_id
        )
        if profile is None:
            return None
        priced = price_request(usage, profile.model, profile.provider)
        return None if priced is None else str(Decimal(priced).quantize(Decimal("0.000001")))
