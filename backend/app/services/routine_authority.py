"""Current authorization for every tool of an unattended routine, including delegates.

The initial admission is still the trigger service's. This is its continuation:
pause, deletion, expiry, lost consent, role changes or revoked run grants take
effect before the next tool. A changed role requires a fresh run, so tool contexts
assembled under the previous role cannot retain its authority.
"""

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from pydantic_ai.tools import ToolDefinition
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import get as capability
from app.agents.mcp import McpSourceIdentity, McpToolOrigin, needs_approval, tool_origin
from app.agents.routine_actions import RoutineToolDecision
from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import AgentStatus
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.project import Project
from app.db.models.watch import Watch
from app.db.session import get_db_context
from app.repositories import (
    agent_repo,
    agent_trigger_repo,
    mcp_connection_repo,
    member_repo,
    organization_repo,
    session_repo,
    watch_repo,
)
from app.schemas.local_target import LocalTarget, target_fingerprint
from app.schemas.routine_actions import (
    RoutineAction,
    RoutineActionKey,
    RoutineConsent,
    RoutineMcpActionKey,
)
from app.schemas.routine_sources import RoutineSourcePolicy
from app.schemas.watch_sources import WatchSources
from app.services.access import AGENT, resolve_access
from app.services.project import ProjectService
from app.services.routine_actions import (
    CONSENTS,
    action_intent,
    action_key,
    instruction_fingerprint,
    routine_effect,
)
from app.services.routine_sources import (
    RoutineSourcesRequired,
    account_identities,
    project_fingerprint,
    read_policy,
    require_bound_sources,
    source_scope,
    spec_fingerprint,
)

MCP_SOURCES = TypeAdapter(dict[UUID, McpSourceIdentity])


def _refused() -> AuthorizationError:
    return AuthorizationError(
        message="This routine stopped or its authorization changed. Start a new run after reviewing its access."
    )


def _intent(watch: Watch, *, version: Literal[1, 2] = 2) -> str:
    material = [
        watch.instructions,
        watch.exclusions,
        watch.urgent,
        str(watch.source_conversation_id),
    ]
    if version == 2:
        material.append(watch.report_mode)
    return hashlib.sha256(json.dumps(material, ensure_ascii=True).encode()).hexdigest()


@dataclass(frozen=True)
class RoutineAuthority:
    routine_id: UUID
    organization_id: UUID
    user_id: UUID
    root_agent_id: UUID
    role: str
    acts_as_creator: bool
    routine_kind: Literal["trigger", "watch"] = "trigger"
    result_mode: Literal["report", "inbox"] = "report"
    sources: WatchSources | None = None
    action_consents: tuple[RoutineConsent, ...] = ()
    root_version_id: UUID | None = None
    mcp_sources: dict[UUID, McpSourceIdentity] | None = None
    local_target_hash: str | None = None
    source_policy: RoutineSourcePolicy | None = None

    def allows_tool(self, tool: ToolDefinition) -> bool:
        origin = tool_origin(tool)
        if origin is None:
            return True
        source = (
            None
            if self.source_policy is None
            else self.source_policy.mcp_sources.get(origin.connection_id)
        )
        return source is not None and origin.tool_id in source.tool_ids

    def require_project(self, project: Project | None) -> None:
        if self.routine_kind != "trigger":
            return
        if (
            self.source_policy is None
            or (None if project is None else project.id) != self.source_policy.project_id
            or (None if project is None else project_fingerprint(project))
            != self.source_policy.project_hash
        ):
            raise RoutineSourcesRequired()

    def require_spec(self, spec: AgentSpec) -> None:
        if self.routine_kind == "trigger" and (
            self.source_policy is None or spec_fingerprint(spec) != self.source_policy.spec_hash
        ):
            raise RoutineSourcesRequired()

    @classmethod
    async def capture(
        cls,
        db: AsyncSession,
        ctx: AuthContext,
        *,
        agent_id: UUID,
        run: AgentRun | None,
        version_id: UUID | None = None,
    ) -> Self | None:
        """Freeze the actor's current role, retaining origin across approval and deletion."""
        origin = ctx.routine_id if run is None else run.routine_origin_id
        if origin is None:
            if run is not None and run.surface == RunSurface.SCHEDULE.value:
                raise _refused()
            return None
        person = ctx.user_id if run is None else run.user_id
        if person is None:
            raise _refused()
        kind = ctx.routine_kind if run is None else run.routine_kind
        if kind not in ("trigger", "watch"):
            raise _refused()
        sources: WatchSources | None = None
        if kind == "watch":
            watch = await watch_repo.get_by_id(db, origin)
            if watch is None or watch.organization_id != ctx.organization_id:
                raise _refused()
            try:
                sources = WatchSources.model_validate(
                    watch.approved_sources if run is None else run.routine_policy
                )
                if run is None:
                    sources = sources.model_copy(
                        update={"intent_hash": _intent(watch), "intent_version": 2}
                    )
            except PydanticValidationError:
                raise _refused() from None
        action_consents: tuple[RoutineConsent, ...] = ()
        mcp_sources: dict[UUID, McpSourceIdentity] | None = None
        local_target_hash: str | None = None
        reviewed_sources: RoutineSourcePolicy | None = None
        result_mode: Literal["report", "inbox"] = "report"
        if kind == "trigger":
            trigger = await agent_trigger_repo.get(db, origin, organization_id=ctx.organization_id)
            if trigger is None:
                raise _refused()
            mode = (
                trigger.result_mode
                if run is None
                else (run.routine_policy or {}).get("result_mode", "report")
            )
            result_mode = "inbox" if mode == "inbox" else "report"
            reviewed_sources = read_policy(
                trigger.approved_sources
                if run is None
                else (run.routine_policy or {}).get("approved_sources")
            )
            if run is None and ctx.routine_source_policy_id != reviewed_sources.id:
                raise RoutineSourcesRequired()
            mcp_sources = account_identities(reviewed_sources)
            try:
                recorded = (
                    trigger.action_consents
                    if run is None
                    else (run.routine_policy or {}).get("action_consents", [])
                )
                action_consents = tuple(CONSENTS.validate_python(recorded))
                source_policy = (
                    None if run is None else (run.routine_policy or {}).get("mcp_sources")
                )
                if source_policy is not None:
                    mcp_sources = MCP_SOURCES.validate_python(source_policy)
                local_policy = (
                    target_fingerprint(trigger.local_target)
                    if run is None
                    else (run.routine_policy or {}).get("local_target_hash")
                )
                if local_policy is not None:
                    if (
                        not isinstance(local_policy, str)
                        or len(local_policy) != 64
                        or any(char not in "0123456789abcdef" for char in local_policy)
                    ):
                        raise _refused()
                    local_target_hash = local_policy
            except PydanticValidationError:
                raise _refused() from None
        member = await member_repo.get_active(
            db, organization_id=ctx.organization_id, user_id=person
        )
        if member is None or (run is None and member.role != ctx.role):
            raise _refused()
        authority = cls(
            routine_id=origin,
            organization_id=ctx.organization_id,
            user_id=person,
            root_agent_id=agent_id,
            role=member.role,
            acts_as_creator=(
                ctx.fired_as_creator is not None
                if run is None
                else not run.initiated_by_publisher_fallback
            ),
            routine_kind="watch" if kind == "watch" else "trigger",
            result_mode=result_mode,
            sources=sources,
            action_consents=action_consents,
            mcp_sources=mcp_sources,
            source_policy=reviewed_sources,
            local_target_hash=local_target_hash,
            root_version_id=version_id if run is None else run.agent_version_id,
        )
        await authority.check_in(db, agent_id)
        return authority

    async def check(self, agent_id: UUID) -> None:
        """Use a short, fresh session; model calls never hold an authorization snapshot."""
        async with get_db_context() as db:
            await self.check_in(db, agent_id)

    async def check_in(self, db: AsyncSession, agent_id: UUID) -> None:
        if self.routine_kind == "watch":
            await self._watch_in(db)
        else:
            await self._trigger_in(db)
        await self._actor_in(db, agent_id)

    async def _trigger_in(self, db: AsyncSession) -> None:
        trigger = await agent_trigger_repo.get(
            db, self.routine_id, organization_id=self.organization_id
        )
        trigger = self._require_trigger(trigger)
        if trigger.one_shot is True:
            from app.services.access import member_context
            from app.services.task_access import execution_allows

            ctx = await member_context(
                db, organization_id=self.organization_id, user_id=self.user_id
            )
            if ctx is None or not await execution_allows(db, ctx, trigger.id):
                raise _refused()
        assert self.source_policy is not None
        await require_bound_sources(
            db, organization_id=self.organization_id, policy=self.source_policy
        )
        if self.local_target_hash is not None:
            target = LocalTarget.model_validate(trigger.local_target)
            if (
                target.routine_grant is None
                or target.device_id is None
                or await session_repo.active_device(
                    db, session_id=target.device_id, user_id=self.user_id, now=datetime.now(UTC)
                )
                is None
            ):
                raise _refused()

    def local_context(self, ctx: AuthContext, *, public_origin: bool) -> AuthContext:
        """A resumed workspace belongs to the original routine owner, never its approver."""
        if not self.acts_as_creator or ctx.organization_id != self.organization_id:
            raise _refused()
        return replace(
            ctx,
            user_id=self.user_id,
            role=self.role,
            api_key_id=None,
            source_conversation_id=None,
            subject_is_publisher_fallback=False,
            routine_id=self.routine_id,
            routine_kind=self.routine_kind,
            fired_as_creator="event" if public_origin else "schedule",
        )

    def require_local_target(self, local: LocalTarget | None) -> None:
        if target_fingerprint(local) != self.local_target_hash:
            raise _refused()

    def _require_trigger(self, trigger: AgentTrigger | None) -> AgentTrigger:
        if (
            trigger is None
            or trigger.organization_id != self.organization_id
            or not trigger.is_active
            or trigger.created_by_user_id != self.user_id
            or trigger.agent_id != self.root_agent_id
            or (trigger.result_mode == "inbox") != (self.result_mode == "inbox")
            or (trigger.ends_at is not None and trigger.ends_at <= datetime.now(UTC))
            or (self.acts_as_creator and not trigger.runs_as_creator)
        ):
            raise _refused()
        if (
            self.source_policy is None
            or read_policy(trigger.approved_sources).id != self.source_policy.id
            or source_scope(trigger) != self.source_policy.scope_hash
            or trigger.created_by_user_id != self.source_policy.consented_by
        ):
            raise RoutineSourcesRequired()
        try:
            if target_fingerprint(trigger.local_target) != self.local_target_hash:
                raise _refused()
        except PydanticValidationError:
            raise _refused() from None
        return trigger

    async def _watch_in(self, db: AsyncSession) -> None:
        watch = await watch_repo.get_by_id(db, self.routine_id)
        if (
            self.sources is None
            or watch is None
            or watch.organization_id != self.organization_id
            or watch.user_id != self.user_id
            or watch.agent_id != self.root_agent_id
            or not watch.is_active
            or (watch.ends_at is not None and watch.ends_at <= datetime.now(UTC))
        ):
            raise _refused()
        try:
            current_sources = WatchSources.model_validate(watch.approved_sources).model_copy(
                update={
                    "intent_hash": _intent(watch, version=self.sources.intent_version),
                    "intent_version": self.sources.intent_version,
                }
            )
        except PydanticValidationError:
            raise _refused() from None
        if current_sources != self.sources:
            raise _refused()
        organization = await organization_repo.get_by_id(db, self.organization_id)
        connection = await mcp_connection_repo.get_by_id(db, self.sources.connection_id)
        if (
            organization is None
            or not organization.proactive_watches_enabled
            or connection is None
            or not connection.is_enabled
            or connection.user_id != self.user_id
            or connection.scope != "user"
            or connection.purpose != "mcp"
            or hashlib.sha256(connection.url.encode()).hexdigest() != self.sources.endpoint_hash
            or self.sources.authorization_generation is None
            or connection.authorization_generation != self.sources.authorization_generation
            or connection.catalog_key != self.sources.catalog_key
            or (
                connection.allowed_tools is not None
                and (
                    self.sources.allowed_tools is None
                    or not set(self.sources.allowed_tools).issubset(connection.allowed_tools)
                )
            )
        ):
            raise _refused()

    async def _actor_in(self, db: AsyncSession, agent_id: UUID) -> None:
        member = await member_repo.get_active(
            db, organization_id=self.organization_id, user_id=self.user_id
        )
        if member is None or member.role != self.role:
            raise _refused()
        current = AuthContext(
            user_id=self.user_id, organization_id=self.organization_id, role=member.role
        )
        if self.source_policy is not None and self.source_policy.project_id is not None:
            try:
                await ProjectService(db).source_for_routine(current, self.source_policy.project_id)
            except (AuthorizationError, BadRequestError, NotFoundError) as exc:
                raise _refused() from exc
        for identifier in sorted({self.root_agent_id, agent_id}):
            agent = await agent_repo.get(db, identifier, organization_id=self.organization_id)
            if agent is None or agent.status == AgentStatus.ARCHIVED.value:
                raise _refused()
            # A published parent lends its pinned delegates, as _resolve_delegate
            # does. Requiring a new direct grant would change that contract.
            if identifier == self.root_agent_id and not await resolve_access(
                db, current, agent, Perm.AGENTS_RUN, resource_type=AGENT
            ):
                raise _refused()

    async def action_policy(
        self, agent_id: UUID, spec: AgentSpec, tool: ToolDefinition
    ) -> RoutineToolDecision:
        """Default to approval for effects; only current, snapshotted consent may waive it."""
        async with get_db_context() as db:
            await self.check_in(db, agent_id)
            if tool.capability_id is None:
                origin = tool_origin(tool)
                if origin is not None:
                    await self._mcp_in(db, origin)
                required = needs_approval(tool, "writes")
                if not required or origin is None or not 1 <= len(origin.tool_id) <= 1000:
                    return RoutineToolDecision(required=required)
                key = RoutineMcpActionKey(
                    connection_id=origin.connection_id,
                    authorization_generation=origin.identity.authorization_generation,
                    endpoint_hash=origin.identity.endpoint_hash,
                    tool_id=origin.tool_id,
                )
                return RoutineToolDecision(
                    required=True, consented_by=await self._consent_in(db, agent_id, key)
                )
            for binding in spec.capabilities:
                if not binding.enabled or binding.id != tool.capability_id:
                    continue
                definition = capability(binding.id)
                for declared in definition.effective_tools(binding.tool_overrides):
                    if declared.name != tool.name:
                        continue
                    trigger = (
                        await agent_trigger_repo.get_by_id(db, self.routine_id, fresh=True)
                        if self.routine_kind == "trigger"
                        else None
                    )
                    effect = routine_effect(
                        definition,
                        declared,
                        local=trigger is not None and trigger.local_target is not None,
                    )
                    if not effect:
                        return RoutineToolDecision()
                    return RoutineToolDecision(
                        required=True,
                        consented_by=await self._consent_in(
                            db,
                            agent_id,
                            RoutineActionKey(capability_id=binding.id, tool_id=declared.id),
                        ),
                    )
            # Framework/third-party capability tools absent from the declared catalog
            # have no authority that the routine can grant by guessing a name.
            return RoutineToolDecision(required=True)

    async def _mcp_in(self, db: AsyncSession, origin: McpToolOrigin) -> None:
        expected = None if self.mcp_sources is None else self.mcp_sources.get(origin.connection_id)
        if self.routine_kind == "watch" and self.sources is not None:
            if origin.connection_id != self.sources.connection_id:
                raise _refused()
            expected = (
                McpSourceIdentity(
                    endpoint_hash=self.sources.endpoint_hash,
                    authorization_generation=self.sources.authorization_generation,
                )
                if self.sources.authorization_generation is not None
                else None
            )
        if (
            expected is None
            or expected.endpoint_hash != origin.identity.endpoint_hash
            or expected.authorization_generation != origin.identity.authorization_generation
            or (self.routine_kind == "trigger" and expected.tool_prefix is None)
            or (
                expected.tool_prefix is not None
                and expected.tool_prefix != origin.identity.tool_prefix
            )
        ):
            raise _refused()
        if self.routine_kind == "trigger":
            source = (
                None
                if self.source_policy is None
                else self.source_policy.mcp_sources.get(origin.connection_id)
            )
            if source is None or origin.tool_id not in source.tool_ids:
                raise RoutineSourcesRequired()
        connection = await mcp_connection_repo.get_by_id(db, origin.connection_id)
        if (
            connection is None
            or not connection.is_enabled
            or connection.purpose != "mcp"
            or (
                connection.allowed_tools is not None
                and origin.tool_id not in connection.allowed_tools
            )
            or connection.authorization_generation != expected.authorization_generation
            or hashlib.sha256(connection.url.encode()).hexdigest() != expected.endpoint_hash
            or not (
                (
                    connection.scope == "user"
                    and self.acts_as_creator
                    and connection.user_id == self.user_id
                )
                or (
                    connection.scope == "org" and connection.organization_id == self.organization_id
                )
            )
        ):
            raise _refused()

    async def _consent_in(
        self, db: AsyncSession, agent_id: UUID, key: RoutineAction
    ) -> UUID | None:
        if (
            self.routine_kind != "trigger"
            or agent_id != self.root_agent_id
            or not self.action_consents
            or self.root_version_id is None
        ):
            return None
        trigger = await agent_trigger_repo.get_by_id(db, self.routine_id, fresh=True)
        organization = await organization_repo.get_by_id(db, self.organization_id)
        trigger = self._require_trigger(trigger)
        if organization is None:
            raise _refused()
        if not organization.chat_may_waive_approvals:
            return None
        member = await member_repo.get_active(
            db, organization_id=self.organization_id, user_id=self.user_id
        )
        if member is None:
            raise _refused()
        if not AuthContext(
            user_id=self.user_id, organization_id=self.organization_id, role=member.role
        ).has(Perm.APPROVALS_DECIDE):
            return None
        try:
            current = CONSENTS.validate_python(trigger.action_consents)
        except PydanticValidationError:
            raise _refused() from None
        version = await agent_repo.get_version(
            db, self.root_version_id, organization_id=self.organization_id
        )
        if version is None:
            return None
        instructions = await instruction_fingerprint(
            db,
            organization_id=self.organization_id,
            spec=AgentSpec.model_validate(version.spec),
            project_id=trigger.project_id,
        )
        for consent in self.action_consents:
            if (
                consent in current
                and consent.consented_by == self.user_id
                and consent.version_id == self.root_version_id
                and consent.intent_hash == action_intent(trigger)
                and consent.instructions_hash == instructions
                and action_key(consent) == key
            ):
                return self.user_id
        return None
