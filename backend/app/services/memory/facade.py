"""Operator-facing management of an agent's memory files.

A memory file has no human owner - the agent writes it - so access is not a
per-row grant the way a context file's is. It rides on the parent agent: whoever
may view the agent may read its memory, whoever may edit the agent may change it.
The check is :func:`resolve_access` against the agent, and a denial is a 404 on
the file rather than a 403, because whether an agent (and therefore its memory)
exists is itself something the caller may not learn.

This is the operator half of the `memory` capability. The agent's own runtime
reads and writes go through `app.services.memory._native`, which opens its own
session; this service runs on the request's session like every other.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import SpendLedger, metered_by
from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.memory import AgentMemoryFact, AgentMemoryFile, MemoryOrigin
from app.db.updates import writable
from app.repositories import agent_repo, ingestion_spend_repo, member_repo, memory_repo
from app.repositories.memory import MemorySort
from app.schemas.memory import (
    AgentMemoryFactCreate,
    AgentMemoryFactList,
    AgentMemoryFactRead,
    AgentMemoryFileCreate,
    AgentMemoryFileList,
    AgentMemoryFileSummary,
    AgentMemoryFileUpdate,
    MemoryOriginLiteral,
)
from app.services.access import AGENT, resolve_access
from app.services.memory._native import embed_operator_fact
from app.services.spend import assert_organization_within_budget

logger = logging.getLogger(__name__)


def _summary(
    file: AgentMemoryFile, *, partition_label: str | None = None
) -> AgentMemoryFileSummary:
    """A memory file as the index shows it - the body is a byte count only."""
    return AgentMemoryFileSummary(
        id=file.id,
        name=file.name,
        description=file.description,
        format=file.format,
        kind=file.kind,
        origin=cast(MemoryOriginLiteral, file.origin),
        end_user_scope_key=file.end_user_scope_key,
        partition_label=partition_label,
        size_bytes=len(file.content.encode("utf-8")),
    )


async def _record_operator_embedding_spend(
    db: AsyncSession, ledger: SpendLedger, *, organization_id: UUID
) -> None:
    """Book an operator seed's embedding to the org's ingestion spend, if any.

    The same shape RAG ingestion books its embeddings in (`_record_embedding_spend`
    in `rag_tasks`): one row per model, into the ledger the monthly budget reads,
    so an operator seeding a fact is charged exactly as one seeding a RAG document -
    with no `rag_document_id`, because a fact is not one. Written on the request's
    session, so it commits with the fact it paid for. Empty when the embedding
    reported no usage, and then nothing is written.
    """
    if not ledger.entries:
        return
    for model_name in dict.fromkeys(entry.model_name for entry in ledger.entries):
        entries = [entry for entry in ledger.entries if entry.model_name == model_name]
        await ingestion_spend_repo.record(
            db,
            organization_id=organization_id,
            rag_document_id=None,
            model=model_name,
            input_tokens=sum(entry.input_tokens for entry in entries),
            output_tokens=sum(entry.output_tokens for entry in entries),
            cost_usd=sum((entry.cost_usd for entry in entries), Decimal(0)),
            cost_is_partial=any(not entry.priced for entry in entries),
        )


class MemoryService:
    """Manage an agent's memory files on behalf of an operator."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _agent_or_404(self, ctx: AuthContext, agent_id: UUID, *, perm: Perm) -> Agent:
        """The parent agent, if the caller may exercise `perm` on it; else a 404.

        Both misses are one answer: an agent in another organization, and an
        agent this caller may not reach, are equally "not found" - neither may
        be distinguished from a truly absent one.
        """
        agent = await agent_repo.get(self.db, agent_id, organization_id=ctx.organization_id)
        if agent is None or not await resolve_access(
            self.db, ctx, agent, perm, resource_type=AGENT
        ):
            raise NotFoundError(message="Agent not found", details={"agent_id": str(agent_id)})
        return agent

    async def _file_row_or_404(self, ctx: AuthContext, file_id: UUID) -> AgentMemoryFile:
        file = await memory_repo.get(self.db, file_id, organization_id=ctx.organization_id)
        if file is None:
            raise NotFoundError(message="Memory file not found", details={"file_id": str(file_id)})
        return file

    async def _file_or_404(self, ctx: AuthContext, file_id: UUID, *, perm: Perm) -> AgentMemoryFile:
        """One memory file, if the caller may exercise `perm` on its agent; else 404."""
        file = await self._file_row_or_404(ctx, file_id)
        # The agent decides access; a denial hides the file the same as a miss.
        await self._agent_or_404(ctx, file.agent_id, perm=perm)
        return file

    async def get(self, ctx: AuthContext, file_id: UUID) -> AgentMemoryFile:
        file = await self._file_row_or_404(ctx, file_id)
        await self._agent_or_404(
            ctx, file.agent_id, perm=self._read_perm(ctx, file.end_user_scope_key)
        )
        return file

    def _own_personal(self, ctx: AuthContext, scope_key: str | None) -> bool:
        """Whether a partition is the caller's own personal store.

        A person may keep, amend and forget their *own* personal memory with only
        view on the agent - the relaxation `create` already makes, extended to
        update and delete so a viewer is not left with personal data they can
        create but never remove (codex P1). Any other partition - the shared store
        or another person's - stays an editor act, so a viewer can never touch what
        is not theirs.
        """
        own = f"user:{ctx.user_id}" if ctx.user_id is not None else None
        return scope_key is not None and scope_key == own

    async def _require_write(
        self, ctx: AuthContext, *, agent_id: UUID, scope_key: str | None
    ) -> None:
        """View suffices to write one's own personal partition; else editor."""
        perm = Perm.AGENTS_VIEW if self._own_personal(ctx, scope_key) else Perm.AGENTS_EDIT
        await self._agent_or_404(ctx, agent_id, perm=perm)

    def _cross_user_read(
        self, ctx: AuthContext, *, scope_key: str | None, all_partitions: bool, scoped_only: bool
    ) -> bool:
        """Whether a listing reaches beyond the shared store and the caller's own.

        Reading every partition, every per-user store, or a specific other person's
        is cross-user inspection - an editor act. A viewer sees the shared store and
        their own personal partition, nothing else, so a member with view on a shared
        agent cannot page through everyone's private memory (codex P2).
        """
        if all_partitions or scoped_only:
            return True
        return scope_key is not None and not self._own_personal(ctx, scope_key)

    def _read_perm(self, ctx: AuthContext, scope_key: str | None) -> Perm:
        """The permission a read of one row by id demands.

        The shared store and the caller's own personal partition are view; another
        person's personal partition is cross-user inspection, an editor act - the
        same rule `_cross_user_read` applies to a listing. Without it a viewer who
        learned an id could `GET` a stranger's personal file or fact it may not list
        (codex).
        """
        if scope_key is None or self._own_personal(ctx, scope_key):
            return Perm.AGENTS_VIEW
        return Perm.AGENTS_EDIT

    def _refuse_if_mem0(self, agent: Agent) -> None:
        """Operator fact management is native-only; refuse it for a mem0-backed agent.

        These operations read and write the deployment's own pgvector store, but a
        mem0-backed agent keeps its facts in mem0. Left unchecked, an operator seed
        would report a success the agent can never recall, and the listing would show
        an empty native store while the agent's real facts sit in mem0 (codex P1).
        Routing the console to mem0 is a separate feature; until then this refuses
        rather than misleads. Read from the draft spec the operator is managing.
        """
        spec = agent.draft_spec if isinstance(agent.draft_spec, dict) else {}
        for binding in spec.get("capabilities", []):
            if (
                isinstance(binding, dict)
                and binding.get("id") == "memory"
                and binding.get("enabled", True)
                and (binding.get("config") or {}).get("backend") == "mem0"
            ):
                raise BadRequestError(
                    message="Operator fact management is unavailable for the mem0 backend",
                    details={"agent_id": str(agent.id)},
                )

    async def _partition_labels(
        self, ctx: AuthContext, scope_keys: set[str | None]
    ) -> dict[str, str]:
        """Map each `user:<id>` partition key in a page to a readable label.

        The member's email, resolved org-scoped through `get_emails_for_users` -
        which restricts to members precisely so a partition key cannot surface the
        identity of someone outside the tenant. The shared store, a channel account
        (`chan:`) and a departed or non-member user have no label, so the console
        falls back to the raw key. One query for a page, not one per row.
        """
        user_ids: list[UUID] = []
        for key in scope_keys:
            if key and key.startswith("user:"):
                try:
                    user_ids.append(UUID(key.removeprefix("user:")))
                except ValueError:
                    continue
        if not user_ids:
            return {}
        emails = await member_repo.get_emails_for_users(
            self.db, organization_id=ctx.organization_id, user_ids=user_ids
        )
        return {f"user:{user_id}": email for user_id, email in emails.items() if email}

    async def list_files(
        self,
        ctx: AuthContext,
        *,
        agent_id: UUID,
        scope_key: str | None = None,
        all_partitions: bool = False,
        scoped_only: bool = False,
        search: str | None = None,
        sort: MemorySort = "name",
        skip: int = 0,
        limit: int = 50,
    ) -> AgentMemoryFileList:
        """A page of one agent's memory files, and the total the pager needs."""
        perm = (
            Perm.AGENTS_EDIT
            if self._cross_user_read(
                ctx, scope_key=scope_key, all_partitions=all_partitions, scoped_only=scoped_only
            )
            else Perm.AGENTS_VIEW
        )
        await self._agent_or_404(ctx, agent_id, perm=perm)
        items, total = await memory_repo.list_for_agent(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            scope_key=scope_key,
            all_partitions=all_partitions,
            scoped_only=scoped_only,
            search=search,
            sort=sort,
            skip=skip,
            limit=limit,
        )
        labels = await self._partition_labels(ctx, {file.end_user_scope_key for file in items})
        return AgentMemoryFileList(
            items=[
                _summary(file, partition_label=labels.get(file.end_user_scope_key or ""))
                for file in items
            ],
            total=total,
        )

    async def create(self, ctx: AuthContext, data: AgentMemoryFileCreate) -> AgentMemoryFile:
        """Create a human-authored (trusted) memory file.

        Authored through the management surface, so `origin` is always `operator`
        (the agent cannot edit or delete it) regardless of who created it - the
        trust tier is human-vs-agent, not a role. The *tier* decides the
        permission: writing the shared store, or another person's personal store,
        is an operator act (`AGENTS_EDIT`); writing one's *own* personal store
        needs only `AGENTS_VIEW`, so any member can keep their own notes without
        being able to touch the shared store or anyone else's. The own-key is
        `user:<caller>`, the same key the runtime derives when that person chats
        (see `derive_end_user_scope_key`), so a note seeded here is the one the
        agent reads back. The check rides on the parent agent through
        `resolve_access`, so an explicit edit grant widens it the usual way.

        Raises:
            AlreadyExistsError: If the name is taken in that partition - the name
                is how the agent and a person refer to a file, so two with one
                name in one partition is an ambiguity nothing can resolve.
        """
        own_key = f"user:{ctx.user_id}" if ctx.user_id is not None else None
        creating_own_personal = (
            data.end_user_scope_key is not None and data.end_user_scope_key == own_key
        )
        perm = Perm.AGENTS_VIEW if creating_own_personal else Perm.AGENTS_EDIT
        await self._agent_or_404(ctx, data.agent_id, perm=perm)
        if await memory_repo.get_by_name(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=data.agent_id,
            end_user_scope_key=data.end_user_scope_key,
            name=data.name,
        ):
            raise AlreadyExistsError(
                message=f"A memory file named '{data.name}' already exists in this partition.",
                details={"name": data.name},
            )
        try:
            file = await memory_repo.create(
                self.db,
                organization_id=ctx.organization_id,
                agent_id=data.agent_id,
                end_user_scope_key=data.end_user_scope_key,
                name=data.name,
                description=data.description,
                content=data.content,
                content_format=data.format,
                kind=data.kind,
                origin=MemoryOrigin.OPERATOR.value,
            )
        except IntegrityError as exc:
            # The `get_by_name` check above and this insert are not atomic; a
            # concurrent create with the same name in the same partition loses the
            # race here. The unique index is the real guard, so a race gets the
            # same 409 as a sequential duplicate rather than a 500.
            raise AlreadyExistsError(
                message=f"A memory file named '{data.name}' already exists in this partition.",
                details={"name": data.name},
            ) from exc
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.file.created",
            target_type="memory",
            target_id=str(file.id),
            details={"agent_id": str(data.agent_id), "name": data.name},
        )
        return file

    async def update(
        self, ctx: AuthContext, file_id: UUID, data: AgentMemoryFileUpdate
    ) -> AgentMemoryFile:
        """Edit a memory file's content or metadata.

        The `origin` is deliberately not touched: editing an agent-authored file
        does not make it trusted. Promoting it is a separate, explicit act
        (:meth:`promote`), so a Save can never quietly turn untrusted content
        into something the prompt will splice in.
        """
        file = await self._file_or_404(ctx, file_id, perm=Perm.AGENTS_VIEW)
        await self._require_write(ctx, agent_id=file.agent_id, scope_key=file.end_user_scope_key)
        update_data = writable(data, over=AgentMemoryFile)
        updated = await memory_repo.update(self.db, file=file, update_data=update_data)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.file.updated",
            target_type="memory",
            target_id=str(file.id),
            details={"name": file.name, "fields": sorted(update_data)},
        )
        return updated

    async def promote(self, ctx: AuthContext, file_id: UUID) -> AgentMemoryFile:
        """Mark an agent-authored file as operator-authored (trusted).

        The one path from `agent` to `operator`, deliberate rather than a side
        effect of editing: a person vouches that the content is safe to treat as
        the operator's own. `origin` is what the poisoning defense turns on - an
        agent-authored file is untrusted - so promoting is how a reviewed note
        graduates. Splicing trusted files into the prompt is a separate capability
        not shipped in v1; for now the trust this confers is the badge the console
        shows, and the gate that later feature will read.
        """
        file = await self._file_or_404(ctx, file_id, perm=Perm.AGENTS_EDIT)
        updated = await memory_repo.update(
            self.db, file=file, update_data={"origin": MemoryOrigin.OPERATOR.value}
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.file.promoted",
            target_type="memory",
            target_id=str(file.id),
            details={"name": file.name},
        )
        return updated

    async def delete(self, ctx: AuthContext, file_id: UUID) -> None:
        file = await self._file_or_404(ctx, file_id, perm=Perm.AGENTS_VIEW)
        await self._require_write(ctx, agent_id=file.agent_id, scope_key=file.end_user_scope_key)
        await memory_repo.delete(self.db, file)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.file.deleted",
            target_type="memory",
            target_id=str(file_id),
        )

    async def create_fact(
        self, ctx: AuthContext, data: AgentMemoryFactCreate
    ) -> AgentMemoryFactRead:
        """Seed a fact an operator authored, embedded server-side.

        The tier decides the permission the same way file create does: the shared
        store or another person's personal store is an operator act (`AGENTS_EDIT`),
        one's own personal store needs only `AGENTS_VIEW`. The fact is written with
        `origin=operator` - the trusted tier - so, unlike an agent-authored one, it
        may enter the standing brief injected into the agent's instructions (a person
        vouched for it). The embedding is metered to the organization's ingestion
        spend: a seed is off any run, so it books to the org budget rather than a
        run's ledger - the same way RAG charges an operator-uploaded document, and
        the inconsistency that a fact seed escaped that ledger while a RAG one did
        not. The organization's monthly cap is checked before the embed, so a seed
        cannot spend past an exhausted budget.
        """
        own_key = f"user:{ctx.user_id}" if ctx.user_id is not None else None
        creating_own_personal = (
            data.end_user_scope_key is not None and data.end_user_scope_key == own_key
        )
        perm = Perm.AGENTS_VIEW if creating_own_personal else Perm.AGENTS_EDIT
        agent = await self._agent_or_404(ctx, data.agent_id, perm=perm)
        self._refuse_if_mem0(agent)
        # Check the cap before spending on the embed, the pre-check RAG ingestion
        # makes, so a seed cannot embed past an exhausted monthly budget (codex P2).
        await assert_organization_within_budget(self.db, ctx.organization_id)
        ledger = SpendLedger(organization_id=ctx.organization_id)
        with metered_by(ledger):
            embedding = await embed_operator_fact(data.content)
        await _record_operator_embedding_spend(self.db, ledger, organization_id=ctx.organization_id)
        fact_id, created_at = await memory_repo.create_fact(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=data.agent_id,
            end_user_scope_key=data.end_user_scope_key,
            content=data.content,
            embedding=embedding,
            origin=MemoryOrigin.OPERATOR.value,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.fact.created",
            target_type="memory",
            target_id=str(fact_id),
            details={"agent_id": str(data.agent_id)},
        )
        return AgentMemoryFactRead(
            id=fact_id,
            agent_id=data.agent_id,
            content=data.content,
            origin=cast(MemoryOriginLiteral, MemoryOrigin.OPERATOR.value),
            end_user_scope_key=data.end_user_scope_key,
            created_at=created_at,
        )

    async def _fact_row_or_404(self, ctx: AuthContext, fact_id: UUID) -> AgentMemoryFact:
        fact = await memory_repo.get_fact(self.db, fact_id, organization_id=ctx.organization_id)
        if fact is None:
            raise NotFoundError(message="Memory fact not found", details={"fact_id": str(fact_id)})
        return fact

    async def _fact_or_404(self, ctx: AuthContext, fact_id: UUID, *, perm: Perm) -> AgentMemoryFact:
        fact = await self._fact_row_or_404(ctx, fact_id)
        await self._agent_or_404(ctx, fact.agent_id, perm=perm)
        return fact

    async def list_facts(
        self,
        ctx: AuthContext,
        *,
        agent_id: UUID,
        scope_key: str | None = None,
        all_partitions: bool = False,
        scoped_only: bool = False,
        search: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> AgentMemoryFactList:
        """A page of an agent's facts. Search is a substring match, not semantic -
        an operator's KNN query would embed off the run's spend ledger (N4), so
        semantic recall stays the agent's runtime tool."""
        perm = (
            Perm.AGENTS_EDIT
            if self._cross_user_read(
                ctx, scope_key=scope_key, all_partitions=all_partitions, scoped_only=scoped_only
            )
            else Perm.AGENTS_VIEW
        )
        agent = await self._agent_or_404(ctx, agent_id, perm=perm)
        self._refuse_if_mem0(agent)
        items, total = await memory_repo.list_facts(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            scope_key=scope_key,
            all_partitions=all_partitions,
            scoped_only=scoped_only,
            search=search,
            skip=skip,
            limit=limit,
        )
        labels = await self._partition_labels(ctx, {fact.end_user_scope_key for fact in items})
        return AgentMemoryFactList(
            items=[
                AgentMemoryFactRead(
                    id=fact.id,
                    agent_id=fact.agent_id,
                    content=fact.content,
                    origin=cast(MemoryOriginLiteral, fact.origin),
                    end_user_scope_key=fact.end_user_scope_key,
                    partition_label=labels.get(fact.end_user_scope_key or ""),
                    created_at=fact.created_at,
                )
                for fact in items
            ],
            total=total,
        )

    async def get_fact(self, ctx: AuthContext, fact_id: UUID) -> AgentMemoryFact:
        fact = await self._fact_row_or_404(ctx, fact_id)
        await self._agent_or_404(
            ctx, fact.agent_id, perm=self._read_perm(ctx, fact.end_user_scope_key)
        )
        return fact

    async def delete_fact(self, ctx: AuthContext, fact_id: UUID) -> None:
        """Forget a fact. There is no operator create or edit - facts are the
        agent's own runtime writes - but clearing one is a management action."""
        fact = await self._fact_or_404(ctx, fact_id, perm=Perm.AGENTS_VIEW)
        await self._require_write(ctx, agent_id=fact.agent_id, scope_key=fact.end_user_scope_key)
        await memory_repo.delete_fact(self.db, fact)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.fact.deleted",
            target_type="memory",
            target_id=str(fact_id),
        )

    async def clear(self, ctx: AuthContext, agent_id: UUID) -> None:
        """Delete every file and fact for an agent, in every partition.

        The danger-zone counterpart to per-row delete: a memory store nobody can
        clear is a liability (#788). One agent-scoped action, checked against
        `AGENTS_EDIT` like every other write, and audited with what it removed.

        Refused for a mem0 agent before anything is deleted: its facts live in
        mem0, so a native clear would drop the files, report "cleared", and leave
        every fact still recallable - a partial wipe wearing a success. The
        single-target clear refuses the same way; routing the delete to mem0 is a
        separate feature (codex).
        """
        agent = await self._agent_or_404(ctx, agent_id, perm=Perm.AGENTS_EDIT)
        self._refuse_if_mem0(agent)
        files = await memory_repo.delete_all_files(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id
        )
        facts = await memory_repo.delete_all_facts(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.cleared",
            target_type="memory",
            target_id=str(agent_id),
            details={"files": files, "facts": facts},
        )

    async def clear_facts(self, ctx: AuthContext, agent_id: UUID) -> None:
        """Delete every fact for an agent, leaving its files untouched.

        The facts pane's own clear, for resetting what the agent has learned
        without discarding the reference files an operator authored.
        """
        agent = await self._agent_or_404(ctx, agent_id, perm=Perm.AGENTS_EDIT)
        self._refuse_if_mem0(agent)
        facts = await memory_repo.delete_all_facts(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.facts.cleared",
            target_type="memory",
            target_id=str(agent_id),
            details={"facts": facts},
        )
