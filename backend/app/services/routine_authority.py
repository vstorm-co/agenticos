"""Current authorization for every tool of an unattended routine, including delegates.

The initial admission is still the trigger service's. This is its continuation:
pause, deletion, expiry, lost consent, role changes or revoked run grants take
effect before the next tool. A changed role requires a fresh run, so tool contexts
assembled under the previous role cannot retain its authority.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError
from pydantic_ai.tools import ToolDefinition
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import get as capability
from app.agents.mcp import needs_approval
from app.agents.routine_actions import RoutineToolDecision
from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import AgentStatus
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.watch import Watch
from app.db.session import get_db_context
from app.repositories import (
    agent_repo,
    agent_trigger_repo,
    mcp_connection_repo,
    member_repo,
    organization_repo,
    watch_repo,
)
from app.schemas.routine_actions import RoutineActionConsent
from app.schemas.watch_sources import WatchSources
from app.services.access import AGENT, resolve_access
from app.services.routine_actions import CONSENTS, action_intent, routine_effect


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
    sources: WatchSources | None = None
    action_consents: tuple[RoutineActionConsent, ...] = ()
    root_version_id: UUID | None = None

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
        action_consents: tuple[RoutineActionConsent, ...] = ()
        if kind == "trigger":
            trigger = await agent_trigger_repo.get(db, origin, organization_id=ctx.organization_id)
            if trigger is None:
                raise _refused()
            try:
                recorded = (
                    trigger.action_consents
                    if run is None
                    else (run.routine_policy or {}).get("action_consents", [])
                )
                action_consents = tuple(CONSENTS.validate_python(recorded))
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
            sources=sources,
            action_consents=action_consents,
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
        if (
            trigger is None
            or not trigger.is_active
            or trigger.created_by_user_id != self.user_id
            or trigger.agent_id != self.root_agent_id
            or (trigger.ends_at is not None and trigger.ends_at <= datetime.now(UTC))
            or (self.acts_as_creator and not trigger.runs_as_creator)
        ):
            raise _refused()

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
                # An unclassified external tool is a write unless the server declares
                # read-only, matching the existing connection's writes policy.
                return RoutineToolDecision(required=needs_approval(tool, "writes"))
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
                    if self.routine_kind != "trigger" or agent_id != self.root_agent_id:
                        return RoutineToolDecision(required=True)
                    trigger = await agent_trigger_repo.get_by_id(db, self.routine_id, fresh=True)
                    organization = await organization_repo.get_by_id(db, self.organization_id)
                    if (
                        trigger is None
                        or organization is None
                        or not organization.chat_may_waive_approvals
                    ):
                        return RoutineToolDecision(required=True)
                    member = await member_repo.get_active(
                        db, organization_id=self.organization_id, user_id=self.user_id
                    )
                    if member is None or not AuthContext(
                        user_id=self.user_id, organization_id=self.organization_id, role=member.role
                    ).has(Perm.APPROVALS_DECIDE):
                        return RoutineToolDecision(required=True)
                    current = CONSENTS.validate_python(trigger.action_consents)
                    for consent in self.action_consents:
                        if (
                            consent in current
                            and consent.consented_by == self.user_id
                            and consent.version_id == self.root_version_id
                            and consent.intent_hash == action_intent(trigger)
                            and consent.capability_id == binding.id
                            and consent.tool_id == declared.id
                        ):
                            return RoutineToolDecision(required=True, consented_by=self.user_id)
                    return RoutineToolDecision(required=True)
            # Framework/third-party capability tools absent from the declared catalog
            # have no authority that the routine can grant by guessing a name.
            return RoutineToolDecision(required=True)
