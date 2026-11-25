"""A routine's narrowing of its agent's tool settings.

The agent's spec decides which tools run freely and which ask first. A routine
can only narrow that, per tool: `ask` waits for approval, `off` hides the tool
from the model and refuses a call to it. It can never release an approval the
agent requires, because neither value says "run freely": a tool runs without
asking only where the agent lets it and the routine leaves it alone.

Saving a narrowing moves the routine to `action_mode = "agent"`, so the agent's
own settings are the base the narrowing applies to.
"""

from typing import Literal

from pydantic import TypeAdapter, ValidationError

from app.agents.capabilities import get as capability
from app.agents.capabilities.approval import tool_needs_approval
from app.agents.mcp import approval_needed
from app.agents.spec import AgentSpec, OrgMcpServerRef, PersonalMcpServerRef, PlatformMcpServerRef
from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.mcp_connection import McpConnection
from app.repositories import agent_trigger_repo, mcp_connection_repo
from app.schemas.routine_actions import RoutineActionKey, RoutinePlatformActionKey
from app.schemas.routine_tools import (
    RoutineCapabilityToolOption,
    RoutineCapabilityToolSetting,
    RoutineMcpToolKey,
    RoutineMcpToolOption,
    RoutineMcpToolSetting,
    RoutinePlatformToolOption,
    RoutinePlatformToolSetting,
    RoutineToolKey,
    RoutineToolOption,
    RoutineToolOptions,
    RoutineToolSetting,
    RoutineToolSettings,
    RoutineToolSettingValue,
)
from app.services.routine_actions import MCP_TOOLS, RoutineActionService, routine_effect

TOOL_SETTINGS = TypeAdapter(list[RoutineToolSetting])

INBOX_FINDING = "publish_inbox_finding"
"""The routine's own report. Turning it off would only silence the routine."""


def setting_key(setting: RoutineToolSetting | RoutineToolOption) -> RoutineToolKey:
    """The tool a setting or an option names, without what it says about it."""
    if isinstance(setting, RoutineCapabilityToolSetting | RoutineCapabilityToolOption):
        return RoutineActionKey(capability_id=setting.capability_id, tool_id=setting.tool_id)
    if isinstance(setting, RoutinePlatformToolSetting | RoutinePlatformToolOption):
        return RoutinePlatformActionKey(kind="platform", tool_id=setting.tool_id)
    return RoutineMcpToolKey(connection_id=setting.connection_id, tool_id=setting.tool_id)


def read_tool_settings(value: object) -> dict[RoutineToolKey, RoutineToolSettingValue]:
    """A stored narrowing by tool. Unreadable storage refuses rather than releasing."""
    try:
        settings = TOOL_SETTINGS.validate_python(value)
    except ValidationError:
        raise AuthorizationError(
            message="This routine's tool settings cannot be read. Save them again."
        ) from None
    return {setting_key(setting): setting.setting for setting in settings}


def tool_settings_of(
    settings: dict[RoutineToolKey, RoutineToolSettingValue],
) -> list[RoutineToolSetting]:
    """The stored form of a narrowing, in a stable order."""
    stored: list[RoutineToolSetting] = []
    for key, value in settings.items():
        if isinstance(key, RoutineActionKey):
            stored.append(RoutineCapabilityToolSetting(**key.model_dump(), setting=value))
        elif isinstance(key, RoutinePlatformActionKey):
            stored.append(RoutinePlatformToolSetting(**key.model_dump(), setting=value))
        else:
            stored.append(RoutineMcpToolSetting(**key.model_dump(), setting=value))
    return sorted(stored, key=lambda setting: setting.model_dump_json())


def stricter(
    *settings: RoutineToolSettingValue | None,
) -> RoutineToolSettingValue | None:
    """`off` over `ask` over nothing: two narrowings never add up to a release."""
    if "off" in settings:
        return "off"
    if "ask" in settings:
        return "ask"
    return None


def _agent_setting(asks: bool) -> Literal["free", "ask"]:
    return "ask" if asks else "free"


def capability_tool_options(spec: AgentSpec, *, local: bool) -> list[RoutineCapabilityToolOption]:
    """Every tool the agent's enabled capabilities give it, reads included."""
    options: list[RoutineCapabilityToolOption] = []
    for binding in spec.capabilities:
        if not binding.enabled:
            continue
        definition = capability(binding.id)
        for tool in definition.effective_tools(binding.tool_overrides):
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
    # Imported here for the same cycle as `platform_action_options`.
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


class RoutineToolService(RoutineActionService):
    """The owner's per-tool narrowing of one routine, reviewed in the console.

    Built on the consent review for the routine's version and its owner check.
    """

    async def tool_options(self, ctx: AuthContext, trigger: AgentTrigger) -> RoutineToolOptions:
        self._human(ctx, trigger)
        return await self.tools(ctx, trigger)

    async def tools(self, ctx: AuthContext, trigger: AgentTrigger) -> RoutineToolOptions:
        """Every tool the routine's version gives it, with the agent's and the routine's setting.

        `ctx` is the owner's: the accounts listed are the ones a run as them reaches.
        """
        spec, _ = await self._spec(ctx, trigger)
        mcp, unavailable = await self._mcp_tools(ctx, trigger, spec)
        from app.services.channel_actions import ChannelActionService, with_actions

        spec = with_actions(spec, await ChannelActionService(ctx, trigger.agent_id).tools(self.db))
        stored = read_tool_settings(trigger.tool_settings)
        options: list[RoutineToolOption] = [
            *capability_tool_options(spec, local=trigger.local_target is not None),
            *mcp,
            *platform_tool_options(spec, as_creator=trigger.runs_as_creator),
        ]
        return RoutineToolOptions(
            unavailable_sources=unavailable,
            items=[
                option.model_copy(update={"setting": _shown(option, stored)}) for option in options
            ],
        )

    async def replace_settings(
        self, ctx: AuthContext, trigger: AgentTrigger, data: RoutineToolSettings
    ) -> RoutineToolOptions:
        """Replace the narrowing and follow the agent's settings under it.

        Each setting must name a tool the routine's version offers. `ask` on a
        tool the agent already asks before says nothing, so it is not kept.
        """
        self._human(ctx, trigger)
        current = await agent_trigger_repo.get_by_id(
            self.db, trigger.id, fresh=True, for_update=True
        )
        if current is None or current.organization_id != ctx.organization_id:
            raise AuthorizationError(message="This routine is no longer available")
        self._human(ctx, current)
        offered = {setting_key(option): option for option in (await self.tools(ctx, current)).items}
        chosen = {setting_key(setting): setting for setting in data.settings}
        if len(chosen) != len(data.settings):
            raise BadRequestError(message="Name each tool once")
        unknown = [key for key in chosen if key not in offered]
        if unknown:
            raise BadRequestError(
                message="Choose tools this routine's agent version offers",
                details={"tools": [key.tool_id for key in unknown]},
            )
        kept = sorted(
            (
                setting
                for key, setting in chosen.items()
                if not (setting.setting == "ask" and offered[key].agent == "ask")
            ),
            key=lambda setting: setting.model_dump_json(),
        )
        await agent_trigger_repo.update(
            self.db,
            trigger=current,
            update_data={
                "tool_settings": [setting.model_dump(mode="json") for setting in kept],
                "action_mode": "agent",
                # Consent waived approvals a narrowing never can; under the
                # agent's own settings it has nothing left to stand in for.
                "action_consents": [],
            },
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            action="routine.tool_settings",
            target_type="agent",
            target_id=str(current.agent_id),
            details={
                "trigger_id": str(current.id),
                "settings": [setting.model_dump(mode="json") for setting in kept],
            },
        )
        return await self.tools(ctx, current)

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


def _shown(
    option: RoutineToolOption, stored: dict[RoutineToolKey, RoutineToolSettingValue]
) -> RoutineToolSettingValue | None:
    setting = stored.get(setting_key(option))
    # Asking before a tool the agent already asks before is the agent's setting.
    return None if setting == "ask" and option.agent == "ask" else setting
