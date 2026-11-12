"""A human's version-bound exceptions to a routine's action approval policy."""

import hashlib
import json
from collections.abc import Sequence
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import CapabilityDef, CapabilityToolInfo
from app.agents.capabilities import get as capability
from app.agents.capabilities.approval import tool_needs_approval
from app.agents.mcp import approval_needed
from app.agents.spec import AgentSpec, OrgMcpServerRef, PersonalMcpServerRef
from app.core.audit import current_impersonator, record_audit
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.mcp_connection import McpConnection
from app.repositories import agent_repo, agent_trigger_repo, mcp_connection_repo, organization_repo
from app.schemas.mcp_connection import McpToolRead
from app.schemas.routine_actions import (
    RoutineAction,
    RoutineActionConsent,
    RoutineActionKey,
    RoutineActionOption,
    RoutineActionOptions,
    RoutineActions,
    RoutineConsent,
    RoutineMcpActionConsent,
    RoutineMcpActionKey,
    RoutineMcpActionOption,
    RoutineReviewChange,
)
from app.services.agent_registry import AgentRegistryService

CONSENTS = TypeAdapter(list[RoutineConsent])
MCP_TOOLS = TypeAdapter(list[McpToolRead])


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
    if trigger.result_mode == "inbox":
        content["result_mode"] = "inbox"
    if trigger.project_id is not None:
        content["project_id"] = trigger.project_id
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()


def activation_intent(trigger: AgentTrigger) -> str:
    """A waiting activation cannot borrow exceptions granted after it was queued."""
    return hashlib.sha256(
        json.dumps(
            [action_intent(trigger), trigger.action_consents, trigger.approved_sources],
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()


def action_key(action: RoutineAction) -> RoutineAction:
    if isinstance(action, RoutineActionKey):
        return RoutineActionKey(capability_id=action.capability_id, tool_id=action.tool_id)
    return RoutineMcpActionKey(
        connection_id=action.connection_id,
        authorization_generation=action.authorization_generation,
        endpoint_hash=action.endpoint_hash,
        tool_id=action.tool_id,
    )


async def instruction_fingerprint(
    db: AsyncSession,
    *,
    organization_id: UUID,
    spec: AgentSpec,
    project_id: UUID | None,
) -> str | None:
    skills, contexts = set(spec.skill_ids), set(spec.context_ids)
    pending = list(spec.subagents)
    seen: set[UUID] = set()
    while pending:
        delegate = pending.pop()
        if delegate.agent_version_id in seen:
            continue
        if len(seen) >= 64:
            raise BadRequestError(message="A routine can review at most 64 delegate versions")
        seen.add(delegate.agent_version_id)
        version = await agent_repo.get_version(
            db, delegate.agent_version_id, organization_id=organization_id
        )
        if version is None or version.agent_id != delegate.agent_id:
            raise BadRequestError(
                message="A pinned delegate is no longer available for routine consent"
            )
        child = AgentSpec.model_validate(version.spec)
        skills.update(child.skill_ids)
        contexts.update(child.context_ids)
        pending.extend(child.subagents)
    if not skills and not contexts and project_id is None:
        return None
    material = await agent_repo.mutable_instruction_material(
        db,
        organization_id=organization_id,
        skill_ids=sorted(skills),
        context_ids=sorted(contexts),
        project_id=project_id,
    )
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def action_review(
    trigger: AgentTrigger,
    version_id: UUID,
    mcp: Sequence[RoutineMcpActionOption] = (),
    *,
    instructions_hash: str | None = None,
) -> str:
    content = f"{version_id}:{action_intent(trigger)}"
    if instructions_hash is not None:
        content += f":instructions:{instructions_hash}"
    if mcp:
        content += json.dumps(
            [
                {"action": action_key(option).model_dump(mode="json"), "waivable": option.waivable}
                for option in mcp
            ],
            sort_keys=True,
        )
    return hashlib.sha256(content.encode()).hexdigest()


def routine_effect(definition: CapabilityDef, tool: CapabilityToolInfo, *, local: bool) -> bool:
    if definition.id == "mirage" and tool.id in {
        "mirage_write_file",
        "mirage_edit_file",
        "mirage_execute",
    }:
        return True
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
        mcp, unavailable = await self._mcp_options(ctx, trigger, spec)
        instructions = await instruction_fingerprint(
            self.db, organization_id=ctx.organization_id, spec=spec, project_id=trigger.project_id
        )
        previous = [
            consent
            for consent in CONSENTS.validate_python(trigger.action_consents)
            if consent.consented_by == ctx.user_id
        ]
        prior_keys = {action_key(consent) for consent in previous}
        consented = {
            action_key(consent)
            for consent in previous
            if consent.version_id == version
            and consent.intent_hash == action_intent(trigger)
            and consent.instructions_hash == instructions
        }
        options = [*action_options(spec, local=trigger.local_target is not None), *mcp]
        review_changes: list[RoutineReviewChange] = []
        if any(consent.version_id != version for consent in previous):
            review_changes.append("version")
        if any(consent.intent_hash != action_intent(trigger) for consent in previous):
            review_changes.append("intent")
        if any(consent.instructions_hash != instructions for consent in previous):
            review_changes.append("instructions")
        if not prior_keys.issubset({action_key(option) for option in options if option.waivable}):
            review_changes.append("actions")
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        return RoutineActionOptions(
            review_changes=review_changes,
            review_token=action_review(trigger, version, mcp, instructions_hash=instructions),
            unavailable_sources=unavailable,
            can_waive=ctx.has(Perm.APPROVALS_DECIDE)
            and organization is not None
            and organization.chat_may_waive_approvals,
            items=[
                option.model_copy(
                    update={
                        "consented": action_key(option) in consented,
                        "previously_consented": action_key(option) in prior_keys,
                    }
                )
                for option in options
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
        mcp, _ = await self._mcp_options(ctx, current, spec)
        instructions = await instruction_fingerprint(
            self.db, organization_id=ctx.organization_id, spec=spec, project_id=current.project_id
        )
        if data.actions and data.review_token != action_review(
            current, version, mcp, instructions_hash=instructions
        ):
            raise ConflictError(
                message="This routine, its published version, instructions or connected actions changed. Review its actions again before consenting."
            )
        available = {
            action_key(option)
            for option in [*action_options(spec, local=current.local_target is not None), *mcp]
            if option.waivable
        }
        chosen = {action_key(action) for action in data.actions}
        if len(chosen) != len(data.actions) or not chosen.issubset(available):
            raise BadRequestError(
                message="Choose distinct actions whose agent approval policy permits standing consent"
            )
        intent = action_intent(current)
        # A replacement gets fresh identities: revoking and regranting cannot revive
        # the consent snapshot of a parked run.
        ordered = sorted(
            chosen, key=lambda key: json.dumps(key.model_dump(mode="json"), sort_keys=True)
        )
        consents = [
            (
                RoutineActionConsent
                if isinstance(key, RoutineActionKey)
                else RoutineMcpActionConsent
            )(
                **key.model_dump(),
                id=uuid4(),
                consented_by=ctx.subject_id,
                version_id=version,
                intent_hash=intent,
                instructions_hash=instructions,
            ).model_dump(mode="json")
            for key in ordered
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
                "actions": [key.model_dump(mode="json") for key in ordered],
            },
        )
        return await self.options(ctx, current)

    async def _mcp_options(
        self, ctx: AuthContext, trigger: AgentTrigger, spec: AgentSpec
    ) -> tuple[list[RoutineMcpActionOption], list[str]]:
        offered: dict[RoutineMcpActionKey, RoutineMcpActionOption] = {}
        unavailable: set[str] = set()
        for ref in spec.mcp_servers:
            connections: list[McpConnection]
            if isinstance(ref, OrgMcpServerRef):
                connection = await mcp_connection_repo.get_org_scoped_by_id(
                    self.db,
                    connection_id=ref.connection_id,
                    organization_id=ctx.organization_id,
                )
                connections = [] if connection is None else [connection]
            elif isinstance(ref, PersonalMcpServerRef) and trigger.runs_as_creator:
                connections = await mcp_connection_repo.list_user_scoped_by_catalog_key(
                    self.db,
                    user_id=ctx.subject_id,
                    catalog_key=ref.catalog_key,
                )
            else:
                continue
            for connection in connections:
                if not connection.is_enabled or connection.purpose != "mcp":
                    continue
                name = connection.name
                if connection.label and connection.label != name:
                    name = f"{connection.label} ({name})"
                if connection.last_tools is None:
                    unavailable.add(name)
                    continue
                try:
                    tools = MCP_TOOLS.validate_python(connection.last_tools)
                except ValidationError:
                    # Old or invalid provider metadata is explicitly unavailable to
                    # review; revocation must still work without probing a provider.
                    unavailable.add(name)
                    continue
                for tool in tools:
                    if (
                        tool.read_only
                        or not 1 <= len(tool.name) <= 1000
                        or (ref.allowed_tools is not None and tool.name not in ref.allowed_tools)
                        or (
                            connection.allowed_tools is not None
                            and tool.name not in connection.allowed_tools
                        )
                    ):
                        continue
                    key = RoutineMcpActionKey(
                        connection_id=connection.id,
                        authorization_generation=connection.authorization_generation,
                        endpoint_hash=hashlib.sha256(connection.url.encode()).hexdigest(),
                        tool_id=tool.name,
                    )
                    # Standing consent may only stand in for an approval the
                    # agent itself does not demand - this tool's own, or else
                    # its binding's.
                    waivable = not approval_needed(
                        ref.approval,
                        read_only=tool.read_only,
                        own=ref.tool_approval.get(tool.name, "default"),
                    )
                    previous = offered.get(key)
                    offered[key] = RoutineMcpActionOption(
                        **key.model_dump(),
                        name=tool.name,
                        account_name=name,
                        account_scope="personal"
                        if isinstance(ref, PersonalMcpServerRef)
                        else "organization",
                        consented=False,
                        waivable=waivable and (previous is None or previous.waivable),
                    )
        return sorted(
            offered.values(), key=lambda option: (str(option.connection_id), option.tool_id)
        ), sorted(unavailable)
