"""A routine's access review: its sources and a setting for each of its agent's tools.

The creator reviews both at once, in the console. The sources half - the
ceiling a run may reach - is `RoutineSourceService`; this is the tool half and
the review as a whole. See `docs/design/routine-access.md`.

A routine never releases an approval its agent, a connection or the platform
requires: `allow` is accepted only where the agent lets the tool run freely,
and the approval gate enforces those floors on every call regardless.
"""

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import CapabilityDef, CapabilityToolInfo
from app.agents.capabilities import get as capability
from app.agents.capabilities.approval import tool_needs_approval
from app.agents.mcp import approval_needed
from app.agents.spec import AgentSpec, OrgMcpServerRef, PersonalMcpServerRef, PlatformMcpServerRef
from app.core.audit import current_impersonator, record_audit
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.mcp_connection import McpConnection
from app.repositories import agent_trigger_repo, mcp_connection_repo, member_repo, organization_repo
from app.schemas.mcp_connection import McpToolRead
from app.schemas.routine_access import (
    RoutineAccessReview,
    RoutineAccessUpdate,
    RoutineCapabilityToolOption,
    RoutineMcpToolOption,
    RoutinePlatformToolOption,
    RoutineReviewReason,
    RoutineToolOption,
)
from app.schemas.routine_sources import RoutineSourcePolicy
from app.schemas.routine_tool_keys import (
    AllowBlockedReason,
    RoutineCapabilityToolKey,
    RoutineCapabilityToolSetting,
    RoutineDelegateSetting,
    RoutineMcpToolKey,
    RoutineMcpToolSetting,
    RoutinePlatformToolKey,
    RoutinePlatformToolSetting,
    RoutineToolKey,
    RoutineToolSetting,
    RoutineToolSettingValue,
)
from app.services.agent_registry import AgentRegistryService
from app.services.routine_sources import (
    PlatformRoutineIdentityRequired,
    RoutineSourceService,
    RoutineSourcesRequired,
    RoutineTrustRefused,
    read_policy,
    require_available,
    routine_intent,
    source_scope,
    stored_review,
    trust_blocked,
)

MCP_TOOLS = TypeAdapter(list[McpToolRead])

INBOX_FINDING = "publish_inbox_finding"
"""The routine's own report. Turning it off would only silence the routine."""


def setting_key(setting: RoutineToolSetting | RoutineToolOption) -> RoutineToolKey:
    """The tool a setting or an option names, without what it says about it."""
    if isinstance(setting, RoutineCapabilityToolSetting | RoutineCapabilityToolOption):
        return RoutineCapabilityToolKey(
            capability_id=setting.capability_id, tool_id=setting.tool_id
        )
    if isinstance(setting, RoutinePlatformToolSetting | RoutinePlatformToolOption):
        return RoutinePlatformToolKey(kind="platform", tool_id=setting.tool_id)
    return RoutineMcpToolKey(connection_id=setting.connection_id, tool_id=setting.tool_id)


def settings_of(policy: RoutineSourcePolicy) -> dict[RoutineToolKey, RoutineToolSettingValue]:
    return {setting_key(setting): setting.setting for setting in policy.tools}


def _setting(key: RoutineToolKey, value: RoutineToolSettingValue) -> RoutineToolSetting:
    if isinstance(key, RoutineCapabilityToolKey):
        return RoutineCapabilityToolSetting(**key.model_dump(), setting=value)
    if isinstance(key, RoutinePlatformToolKey):
        return RoutinePlatformToolSetting(**key.model_dump(), setting=value)
    return RoutineMcpToolSetting(**key.model_dump(), setting=value)


def routine_effect(definition: CapabilityDef, tool: CapabilityToolInfo, *, local: bool) -> bool:
    """Whether a capability's tool changes something, as a routine counts it."""
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


def _agent_setting(asks: bool) -> Literal["free", "ask"]:
    return "ask" if asks else "free"


def provider_executed(spec: AgentSpec) -> set[RoutineCapabilityToolKey]:
    """Capability tools the model provider runs on its side under this spec.

    Such a call never reaches this deployment's approval gate or the model's
    tool list, so no setting could be enforced on it.
    """
    handed_over: set[RoutineCapabilityToolKey] = set()
    for binding in spec.capabilities:
        if not binding.enabled:
            continue
        definition = capability(binding.id)
        if definition.provider_executed is None:
            continue
        config = definition.validate_config(binding.config)
        handed_over.update(
            RoutineCapabilityToolKey(capability_id=binding.id, tool_id=tool_id)
            for tool_id in definition.provider_executed.tools_for(config)
        )
    return handed_over


def capability_tool_options(spec: AgentSpec, *, local: bool) -> list[RoutineCapabilityToolOption]:
    """Every tool the agent's enabled capabilities give it, reads included.

    Not the ones the model provider runs: a routine could not set those.
    """
    options: list[RoutineCapabilityToolOption] = []
    handed_over = provider_executed(spec)
    for binding in spec.capabilities:
        if not binding.enabled:
            continue
        definition = capability(binding.id)
        for tool in definition.effective_tools(binding.tool_overrides):
            if RoutineCapabilityToolKey(capability_id=binding.id, tool_id=tool.id) in handed_over:
                continue
            options.append(
                RoutineCapabilityToolOption(
                    capability_id=binding.id,
                    capability_name=definition.name,
                    tool_id=tool.id,
                    name=tool.name,
                    effect=routine_effect(definition, tool, local=local),
                    agent=_agent_setting(tool_needs_approval(tool=tool, binding=binding)),
                )
            )
    return options


def platform_tool_options(spec: AgentSpec, *, as_creator: bool) -> list[RoutinePlatformToolOption]:
    """The platform's own tools the binding offers; only a routine acting as its creator has them."""
    ref = next((ref for ref in spec.mcp_servers if isinstance(ref, PlatformMcpServerRef)), None)
    if ref is None or not as_creator:
        return []
    # Imported here: the platform's tools reach workflow execution, whose node
    # handlers import the agent registry, which this module imports.
    from app.services.platform_mcp import platform_tool_catalog

    # The floor a run applies: the platform's default never drops below `writes`.
    policy = "all" if ref.approval == "all" else "writes"
    return [
        RoutinePlatformToolOption(
            kind="platform",
            tool_id=tool.name,
            name=tool.name,
            group=tool.group,
            effect=tool.writes,
            agent=_agent_setting(
                not tool.ungated
                and (
                    tool.always_asks
                    or approval_needed(
                        policy,
                        read_only=not tool.writes,
                        own=ref.tool_approval.get(tool.name, "default"),
                        default_allow=tool.default_approval_free,
                    )
                )
            ),
        )
        for tool in platform_tool_catalog()
        if tool.name != INBOX_FINDING
        and (ref.allowed_tools is None or tool.name in ref.allowed_tools)
    ]


def default_setting(option: RoutineToolOption, *, can_allow: bool) -> RoutineToolSettingValue:
    """What a new review gives a tool: everything the creator may let run, runs."""
    if option.agent == "ask" or (option.effect and not can_allow):
        return "ask"
    return "allow"


def asks_for_routine(
    option: RoutineToolOption,
    policy: RoutineSourcePolicy,
    setting: RoutineToolSettingValue | None,
    *,
    can_allow: bool,
) -> bool:
    """Whether the routine, rather than the agent, makes a call to this tool wait."""
    if option.agent == "ask" or setting == "off":
        return False
    if setting == "ask":
        return True
    if policy.mode == "trust_agent" or not option.effect:
        return False
    if setting == "allow":
        return not (can_allow or policy.grandfathered)
    return not policy.grandfathered


def in_console(ctx: AuthContext) -> bool:
    """The creator in a signed-in session, not a key, a run or an impersonation.

    Letting a tool run without asking is the decision the approval queue
    records, so - like standing consent in a chat - only the person makes it.
    """
    return not (
        ctx.api_key_id is not None
        or ctx.routine_id is not None
        or ctx.fired_as_creator is not None
        or ctx.subject_is_publisher_fallback
        or current_impersonator() is not None
    )


async def allow_blocked(db: AsyncSession, ctx: AuthContext) -> AllowBlockedReason | None:
    """Why `ctx` may not let an effectful tool run without asking, if it may not.

    The same rule as standing consent in a chat: the decision the approval
    queue exists to record, which the organization may withhold.
    """
    if not in_console(ctx):
        return "console"
    if not ctx.has(Perm.APPROVALS_DECIDE):
        return "permission"
    organization = await organization_repo.get_by_id(db, ctx.organization_id)
    if organization is None or not organization.chat_may_waive_approvals:
        return "organization"
    return None


async def allow_holds(db: AsyncSession, *, organization_id: UUID, user_id: UUID) -> bool:
    """Whether a routine's creator may still let its effectful tools run, at call time."""
    member = await member_repo.get_active(db, organization_id=organization_id, user_id=user_id)
    if member is None:
        return False
    ctx = AuthContext(user_id=user_id, organization_id=organization_id, role=member.role)
    return await allow_blocked(db, ctx) is None


class RoutineAccessService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.agents = AgentRegistryService(db)
        self.sources = RoutineSourceService(db)

    @staticmethod
    def _human(ctx: AuthContext, trigger: AgentTrigger) -> None:
        """The creator in person: a session, or a key they issued for `personal:consent`."""
        if (
            ctx.organization_id != trigger.organization_id
            or ctx.user_id is None
            or ctx.user_id != trigger.created_by_user_id
            or not ctx.acts_in_person
            or current_impersonator() is not None
        ):
            raise AuthorizationError(message="Only the routine's owner can review its access")

    async def _spec(self, ctx: AuthContext, trigger: AgentTrigger) -> AgentSpec:
        if trigger.pinned_version_id is not None:
            _, spec, _ = await self.agents.get_pinned_spec(
                ctx, trigger.agent_id, trigger.pinned_version_id
            )
        else:
            _, spec, _ = await self.agents.get_runnable_spec(
                ctx, trigger.agent_id, environment_id=trigger.environment_id
            )
        return spec

    async def offered(
        self, ctx: AuthContext, trigger: AgentTrigger
    ) -> tuple[list[RoutineToolOption], list[str], bool]:
        """Every tool the routine's version gives its root agent, as a run as `ctx` reaches it.

        With the accounts whose tool list needs a connection check first, and
        whether the agent delegates to other agents at all.
        """
        spec = await self._spec(ctx, trigger)
        mcp, unlisted = await self._mcp_tools(ctx, trigger, spec)
        from app.services.channel_actions import ChannelActionService, with_actions

        spec = with_actions(spec, await ChannelActionService(ctx, trigger.agent_id).tools(self.db))
        options: list[RoutineToolOption] = [
            *capability_tool_options(spec, local=trigger.local_target is not None),
            *mcp,
            *platform_tool_options(spec, as_creator=trigger.runs_as_creator),
        ]
        return options, unlisted, bool(spec.served_subagents)

    @staticmethod
    def _token(
        review_token: str, options: list[RoutineToolOption], has_delegates: bool, intent: str
    ) -> str:
        content = {
            "sources": review_token,
            "tools": sorted(
                json.dumps(
                    {
                        "key": setting_key(option).model_dump(mode="json"),
                        "effect": option.effect,
                        "agent": option.agent,
                    },
                    sort_keys=True,
                )
                for option in options
            ),
            "delegates": has_delegates,
            "intent": intent,
        }
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    async def review(self, ctx: AuthContext, trigger: AgentTrigger) -> RoutineAccessReview:
        """The routine's sources and tools, the stored settings and what the creator may choose."""
        self._human(ctx, trigger)
        snapshot = await self.sources.snapshot(ctx, trigger)
        options, unlisted, has_delegates = await self.offered(ctx, trigger)
        allow_reason = await allow_blocked(self.db, ctx)
        trust_reason = (
            "console" if not in_console(ctx) else await trust_blocked(self.db, ctx, trigger)
        )
        stored: RoutineSourcePolicy | None = None
        reason: RoutineReviewReason | None = None
        if trigger.setup_required:
            reason = "setup"
        else:
            try:
                stored = read_policy(trigger.approved_sources)
                await self.sources.current(ctx, trigger, expected_id=stored.id)
            except RoutineTrustRefused:
                reason = "trust_not_allowed"
            except PlatformRoutineIdentityRequired:
                reason = "platform_identity"
            except RoutineSourcesRequired as refusal:
                changed = stored is not None and (
                    stored.scope_hash != source_scope(trigger)
                    or (
                        stored.intent_hash is not None
                        and stored.intent_hash != routine_intent(trigger)
                    )
                )
                reason = (
                    "routine_changed"
                    if changed
                    else "unavailable"
                    if (refusal.details or {}).get("unavailable_sources")
                    else "sources"
                )
        settings = {} if stored is None else settings_of(stored)

        def shown(option: RoutineToolOption) -> RoutineToolSettingValue | None:
            setting = settings.get(setting_key(option))
            if setting is not None:
                return setting
            if stored is None or stored.grandfathered:
                # A routine not reviewed yet shows what a review would give it;
                # a migrated one shows what it does: follow the agent.
                return default_setting(option, can_allow=allow_reason is None or stored is not None)
            return None

        required = set(snapshot.unavailable) - snapshot.optional_unavailable
        return RoutineAccessReview(
            mode="reviewed" if stored is None else stored.mode,
            current=reason is None,
            review_reason=reason,
            review_token=self._token(
                snapshot.token(), options, has_delegates, routine_intent(trigger)
            ),
            version_id=snapshot.policy.version_id,
            sources=snapshot.items,
            unavailable_sources=snapshot.unavailable,
            required_unavailable_sources=sorted(required),
            tools=[option.model_copy(update={"setting": shown(option)}) for option in options],
            unlisted_accounts=unlisted,
            has_delegates=has_delegates,
            delegates=(
                stored.delegates
                if stored is not None
                else "allow"
                if allow_reason is None
                else "ask"
            ),
            can_allow=allow_reason is None,
            allow_blocked_reason=allow_reason,
            can_trust=trust_reason is None,
            trust_blocked_reason=trust_reason,
        )

    async def replace(
        self, ctx: AuthContext, trigger: AgentTrigger, data: RoutineAccessUpdate
    ) -> RoutineAccessReview:
        """Save the creator's review of exactly what they were shown.

        Raises:
            ConflictError: The sources, tools or the routine changed since the review.
            BadRequestError: A setting names a tool the version does not offer, twice,
                or releases an approval the agent requires.
            AuthorizationError: The creator may not let an effectful tool run without
                asking, or may not let this routine trust its agent.
        """
        self._human(ctx, trigger)
        current = await agent_trigger_repo.get_by_id(
            self.db, trigger.id, fresh=True, for_update=True
        )
        if current is None or current.organization_id != ctx.organization_id:
            raise AuthorizationError(message="This routine is no longer available")
        self._human(ctx, current)
        snapshot = await self.sources.snapshot(ctx, current)
        require_available(snapshot)
        options, _, has_delegates = await self.offered(ctx, current)
        intent = routine_intent(current)
        if data.review_token != self._token(snapshot.token(), options, has_delegates, intent):
            raise ConflictError(
                message="This routine, its agent's sources or its tools changed. Review its access again."
            )
        offered = {setting_key(option): option for option in options}
        chosen = {setting_key(setting): setting.setting for setting in data.tools}
        if len(chosen) != len(data.tools):
            raise BadRequestError(message="Name each tool once")
        unknown = [key.tool_id for key in chosen if key not in offered]
        if unknown:
            raise BadRequestError(
                message="Choose tools this routine's agent version offers",
                details={"tools": unknown},
            )
        released = [
            key.tool_id
            for key, value in chosen.items()
            if value == "allow" and offered[key].agent == "ask"
        ]
        if released:
            raise BadRequestError(
                message="A routine cannot let a tool run without asking where its agent asks first",
                details={"tools": released},
            )
        allow_reason = await allow_blocked(self.db, ctx)
        if allow_reason is not None and (
            any(value == "allow" and offered[key].effect for key, value in chosen.items())
            or (has_delegates and data.delegates == "allow")
        ):
            raise AuthorizationError(
                message=(
                    "Letting a tool that changes something run without asking needs "
                    "'approvals:decide' and the organization's standing consent setting"
                ),
                details={"reason": allow_reason},
            )
        if data.mode == "trust_agent":
            trust_reason = (
                "console" if not in_console(ctx) else await trust_blocked(self.db, ctx, current)
            )
            if trust_reason is not None:
                raise AuthorizationError(
                    message="This routine may not trust its agent", details={"reason": trust_reason}
                )
        try:
            previous = settings_of(read_policy(current.approved_sources))
        except RoutineSourcesRequired:
            previous = {}
        # A tool the request leaves out asks: the safe reading of silence. A
        # saved setting for a tool not offered now (an account whose tool list
        # is unknown, an optional source that is down) is kept as it was: the
        # creator was not shown it, so the save cannot have changed it, and
        # dropping an `off` would let the tool run when it comes back.
        tools = tuple(
            sorted(
                (
                    *(_setting(key, chosen.get(key, "ask")) for key in offered),
                    *(
                        _setting(key, value)
                        for key, value in previous.items()
                        if key not in offered
                    ),
                ),
                key=lambda setting: setting.model_dump_json(),
            )
        )
        delegates: RoutineDelegateSetting = data.delegates if has_delegates else "ask"
        policy = stored_review(
            snapshot, mode=data.mode, tools=tools, delegates=delegates, intent_hash=intent
        )
        await agent_trigger_repo.update(
            self.db,
            trigger=current,
            update_data={"approved_sources": policy.model_dump(mode="json")},
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="routine.access_reviewed",
            target_type="agent",
            target_id=str(current.agent_id),
            details={
                "trigger_id": str(current.id),
                "version_id": str(policy.version_id),
                "mode": policy.mode,
                "accounts": len(policy.mcp_sources),
                "allow": sum(1 for value in chosen.values() if value == "allow"),
                "ask": sum(1 for setting in tools if setting.setting == "ask"),
                "off": sum(1 for value in chosen.values() if value == "off"),
                "delegates": delegates,
            },
        )
        return await self.review(ctx, current)

    async def initial(self, ctx: AuthContext, trigger: AgentTrigger) -> RoutineSourcePolicy:
        """A new routine's review: its sources now, and every tool its creator may let run.

        Raises:
            RoutineSourcesRequired: A source the routine needs is unavailable.
        """
        snapshot = await self.sources.initial(ctx, trigger)
        options, _, _ = await self.offered(ctx, trigger)
        can_allow = await allow_blocked(self.db, ctx) is None
        tools = tuple(
            sorted(
                (
                    _setting(setting_key(option), default_setting(option, can_allow=can_allow))
                    for option in options
                ),
                key=lambda setting: setting.model_dump_json(),
            )
        )
        return stored_review(
            snapshot,
            mode="reviewed",
            tools=tools,
            delegates="allow" if can_allow else "ask",
            intent_hash=routine_intent(trigger),
        )

    async def waiting(self, ctx: AuthContext, trigger: AgentTrigger) -> int:
        """How many tools this routine, rather than its agent, makes wait for a person.

        `ctx` is the creator's, as a fire would run: not necessarily a console session.
        """
        policy = read_policy(trigger.approved_sources)
        options, _, _ = await self.offered(ctx, trigger)
        assert ctx.user_id is not None
        can_allow = await allow_holds(
            self.db, organization_id=ctx.organization_id, user_id=ctx.user_id
        )
        settings = settings_of(policy)
        return sum(
            1
            for option in options
            if asks_for_routine(
                option, policy, settings.get(setting_key(option)), can_allow=can_allow
            )
        )

    async def _mcp_tools(
        self, ctx: AuthContext, trigger: AgentTrigger, spec: AgentSpec
    ) -> tuple[list[RoutineMcpToolOption], list[str]]:
        offered: dict[RoutineMcpToolKey, RoutineMcpToolOption] = {}
        unavailable: set[str] = set()
        for ref in spec.mcp_servers:
            connections: list[McpConnection]
            if isinstance(ref, OrgMcpServerRef):
                connection = await mcp_connection_repo.get_org_scoped_by_id(
                    self.db, connection_id=ref.connection_id, organization_id=ctx.organization_id
                )
                connections = [] if connection is None else [connection]
            elif isinstance(ref, PersonalMcpServerRef) and trigger.runs_as_creator:
                connections = await mcp_connection_repo.list_user_scoped_by_catalog_key(
                    self.db, user_id=ctx.subject_id, catalog_key=ref.catalog_key
                )
            else:
                continue
            for connection in connections:
                if not connection.is_enabled or connection.purpose != "mcp":
                    continue
                name = connection.name
                if connection.label and connection.label != name:
                    name = f"{connection.label} ({name})"
                try:
                    tools = MCP_TOOLS.validate_python(connection.last_tools)
                except ValidationError:
                    # Never listed, or listed in a shape this version cannot read:
                    # a connection check lists it again.
                    unavailable.add(name)
                    continue
                for tool in tools:
                    if (
                        not 1 <= len(tool.name) <= 1000
                        or (ref.allowed_tools is not None and tool.name not in ref.allowed_tools)
                        or (
                            connection.allowed_tools is not None
                            and tool.name not in connection.allowed_tools
                        )
                    ):
                        continue
                    key = RoutineMcpToolKey(connection_id=connection.id, tool_id=tool.name)
                    offered[key] = RoutineMcpToolOption(
                        **key.model_dump(),
                        name=tool.name,
                        account_name=name,
                        account_scope="personal"
                        if isinstance(ref, PersonalMcpServerRef)
                        else "organization",
                        effect=not tool.read_only,
                        agent=_agent_setting(
                            approval_needed(
                                ref.approval,
                                read_only=tool.read_only,
                                own=ref.tool_approval.get(tool.name, "default"),
                            )
                        ),
                    )
        return sorted(
            offered.values(), key=lambda option: (str(option.connection_id), option.tool_id)
        ), sorted(unavailable)
