"""A human's version-bound exceptions to a routine's action approval policy."""

import hashlib
import json
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import CapabilityDef, CapabilityToolInfo
from app.agents.capabilities import get as capability
from app.agents.capabilities.approval import tool_needs_approval
from app.agents.spec import AgentSpec
from app.core.audit import current_impersonator, record_audit
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_trigger import AgentTrigger
from app.repositories import agent_trigger_repo, organization_repo
from app.schemas.routine_actions import (
    RoutineActionConsent,
    RoutineActionKey,
    RoutineActionOption,
    RoutineActionOptions,
    RoutineActions,
)
from app.services.agent_registry import AgentRegistryService

CONSENTS = TypeAdapter(list[RoutineActionConsent])


def action_intent(trigger: AgentTrigger) -> str:
    """A title or cadence edit grants no new authority; changing the work does."""
    content = {
        field: getattr(trigger, field)
        for field in (
            "agent_id",
            "prompt",
            "environment_id",
            "pinned_version_id",
            "runs_as_creator",
            "event_source",
            "event_config",
            "answer_to",
            "delivery_conversation_id",
            "teams_conversation_id",
            "local_target",
        )
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()


def action_review(trigger: AgentTrigger, version_id: UUID) -> str:
    return hashlib.sha256(f"{version_id}:{action_intent(trigger)}".encode()).hexdigest()


def routine_effect(definition: CapabilityDef, tool: CapabilityToolInfo, *, local: bool) -> bool:
    if definition.id == "sandbox" and local and tool.id in ("write_file", "edit_file"):
        return True
    # A task may cross an external-agent boundary where this deployment cannot
    # inspect its tools. Approval of delegation does not waive any local child tool.
    if definition.id == "subagents" and tool.id == "task":
        return True
    return definition.side_effecting if tool.side_effecting is None else tool.side_effecting


def action_options(spec: AgentSpec, *, local: bool = False) -> list[RoutineActionOption]:
    options: list[RoutineActionOption] = []
    for binding in spec.capabilities:
        if not binding.enabled:
            continue
        definition = capability(binding.id)
        for tool in definition.effective_tools(binding.tool_overrides):
            effect = routine_effect(definition, tool, local=local)
            if effect:
                options.append(
                    RoutineActionOption(
                        capability_id=binding.id,
                        tool_id=tool.id,
                        name=tool.name,
                        consented=False,
                        waivable=not tool_needs_approval(tool=tool, binding=binding),
                    )
                )
    return options


class RoutineActionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.agents = AgentRegistryService(db)

    @staticmethod
    def _human(ctx: AuthContext, trigger: AgentTrigger) -> None:
        if (
            ctx.organization_id != trigger.organization_id
            or ctx.user_id is None
            or ctx.user_id != trigger.created_by_user_id
            or ctx.api_key_id is not None
            or ctx.routine_id is not None
            or ctx.fired_as_creator is not None
            or ctx.subject_is_publisher_fallback
            or current_impersonator() is not None
        ):
            raise AuthorizationError(
                message="Only the routine's owner can review its action consent in the console"
            )

    async def _spec(self, ctx: AuthContext, trigger: AgentTrigger) -> tuple[AgentSpec, UUID]:
        if trigger.pinned_version_id is not None:
            _, spec, version = await self.agents.get_pinned_spec(
                ctx, trigger.agent_id, trigger.pinned_version_id
            )
        else:
            _, spec, version = await self.agents.get_runnable_spec(
                ctx, trigger.agent_id, environment_id=trigger.environment_id
            )
        return spec, version

    async def options(self, ctx: AuthContext, trigger: AgentTrigger) -> RoutineActionOptions:
        self._human(ctx, trigger)
        spec, version = await self._spec(ctx, trigger)
        consented = {
            (consent.capability_id, consent.tool_id)
            for consent in CONSENTS.validate_python(trigger.action_consents)
            if consent.version_id == version
            and consent.intent_hash == action_intent(trigger)
            and consent.consented_by == ctx.user_id
        }
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        return RoutineActionOptions(
            review_token=action_review(trigger, version),
            can_waive=ctx.has(Perm.APPROVALS_DECIDE)
            and organization is not None
            and organization.chat_may_waive_approvals,
            items=[
                option.model_copy(
                    update={"consented": (option.capability_id, option.tool_id) in consented}
                )
                for option in action_options(spec, local=trigger.local_target is not None)
            ],
        )

    async def replace(
        self, ctx: AuthContext, trigger: AgentTrigger, data: RoutineActions
    ) -> RoutineActionOptions:
        self._human(ctx, trigger)
        if data.actions:
            organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
            if (
                not ctx.has(Perm.APPROVALS_DECIDE)
                or organization is None
                or not organization.chat_may_waive_approvals
            ):
                raise AuthorizationError(
                    message="Your organization and approval permissions must allow standing consent"
                )
        current = await agent_trigger_repo.get_by_id(
            self.db, trigger.id, fresh=True, for_update=True
        )
        if current is None or current.organization_id != ctx.organization_id:
            raise AuthorizationError(message="This routine is no longer available")
        self._human(ctx, current)
        spec, version = await self._spec(ctx, current)
        if data.actions and data.review_token != action_review(current, version):
            raise ConflictError(
                message="This routine or its published version changed. Review its actions again before consenting."
            )
        available = {
            (option.capability_id, option.tool_id)
            for option in action_options(spec, local=current.local_target is not None)
            if option.waivable
        }
        chosen = {(action.capability_id, action.tool_id) for action in data.actions}
        if len(chosen) != len(data.actions) or not chosen.issubset(available):
            raise BadRequestError(
                message="Choose distinct actions whose agent approval policy permits standing consent"
            )
        intent = action_intent(current)
        # A replacement gets fresh identities: revoking and regranting cannot revive
        # the consent snapshot of a parked run.
        consents = [
            RoutineActionConsent(
                **RoutineActionKey(capability_id=cap, tool_id=tool).model_dump(),
                id=uuid4(),
                consented_by=ctx.subject_id,
                version_id=version,
                intent_hash=intent,
            ).model_dump(mode="json")
            for cap, tool in sorted(chosen)
        ]
        await agent_trigger_repo.update(
            self.db, trigger=current, update_data={"action_consents": consents}
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            action="routine.action_consent",
            target_type="agent",
            target_id=str(current.agent_id),
            details={
                "trigger_id": str(current.id),
                "version_id": str(version),
                "actions": [
                    {"capability_id": cap, "tool_id": tool} for cap, tool in sorted(chosen)
                ],
            },
        )
        return await self.options(ctx, current)
