"""Explicit administrative actions, with on-demand contracts and no arbitrary HTTP proxy."""

import json
import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastmcp.exceptions import ToolError
from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from app.core.config import settings
from app.schemas.assistant import AssistantUpdate
from app.schemas.deployment_settings import DeploymentSettingsUpdate
from app.schemas.group import GroupCreate, GroupLeadUpdate, GroupMemberAdd, GroupUpdate
from app.schemas.organization import OrganizationMemberUpdate, OrganizationUpdate
from app.schemas.retention import RetentionUpdate
from app.schemas.system_agent import SystemAgentUpdate, SystemRole
from app.schemas.updates import UpdateApply, UpdateCancel, UpdatePrepare
from app.services.platform_mcp._api import PlatformApi
from app.services.platform_mcp._disclosure import (
    Chars,
    Limit,
    Operation,
    Skip,
    details,
    encoded,
    listing,
    metadata,
    page,
)

type Area = Literal["deployment", "organization"]
_JSON = TypeAdapter(JsonValue)
_OBJECT = TypeAdapter(dict[str, JsonValue])
_ROLE = TypeAdapter(SystemRole)


@dataclass(frozen=True)
class AdministrationAction:
    id: str
    area: Area
    method: Literal["GET", "POST", "PATCH", "PUT", "DELETE"]
    path: str
    description: str
    permission: str
    writes: bool = False
    model: type[BaseModel] | None = None
    pagination: Literal["none", "server", "local"] = "none"
    search_key: str | None = None
    filters: tuple[str, ...] = ()
    read_action: str = ""
    handoff: str | None = None


ACTION_CATALOG = (
    AdministrationAction(
        "deployment.settings.read",
        "deployment",
        "GET",
        "/admin/settings",
        "Read installation identity, access, notices, limits and service defaults.",
        "deployment:admin",
    ),
    AdministrationAction(
        "deployment.settings.update",
        "deployment",
        "PATCH",
        "/admin/settings",
        "Change branding, signup, domains, automatic organization membership, limits, maintenance, notices and compressed dictation audio.",
        "deployment:admin",
        writes=True,
        model=DeploymentSettingsUpdate,
        read_action="deployment.settings.read",
    ),
    AdministrationAction(
        "deployment.organizations.list",
        "deployment",
        "GET",
        "/admin/organizations",
        "Find organizations across the installation, including candidates for default membership.",
        "deployment:admin",
        pagination="server",
        search_key="search",
        filters=("kind", "sort_by", "sort_dir"),
    ),
    AdministrationAction(
        "deployment.updates.read",
        "deployment",
        "GET",
        "/admin/updates",
        "Read updater availability, prepared images, backup and current operation status.",
        "deployment:admin",
    ),
    AdministrationAction(
        "deployment.updates.prepare",
        "deployment",
        "POST",
        "/admin/updates/prepare",
        "Prepare a published stable release: preflight, immutable image references and backup. This does not apply it.",
        "deployment:admin",
        writes=True,
        model=UpdatePrepare,
        read_action="deployment.updates.read",
    ),
    AdministrationAction(
        "deployment.updates.apply",
        "deployment",
        "POST",
        "/admin/updates/apply",
        "Apply a prepared operation now or schedule it. Can drain requests, migrate and restart services; explicit approval required.",
        "deployment:admin",
        writes=True,
        model=UpdateApply,
        read_action="deployment.updates.read",
    ),
    AdministrationAction(
        "deployment.updates.cancel",
        "deployment",
        "POST",
        "/admin/updates/cancel",
        "Cancel an update before draining or migration; uncertain effects must be inspected rather than repeated.",
        "deployment:admin",
        writes=True,
        model=UpdateCancel,
        read_action="deployment.updates.read",
    ),
    AdministrationAction(
        "deployment.diagnostics.read",
        "deployment",
        "GET",
        "/admin/diagnostics",
        "Read diagnostics and administrator presence; diagnostic configuration may be environment-owned.",
        "deployment:admin",
    ),
    AdministrationAction(
        "deployment.apns.read",
        "deployment",
        "GET",
        "/push/apns",
        "Inspect iPhone push readiness and key metadata, never private key material.",
        "deployment:admin",
    ),
    AdministrationAction(
        "deployment.apns.clear",
        "deployment",
        "DELETE",
        "/push/apns",
        "Remove the APNs credential and stop iPhone push notifications.",
        "deployment:admin",
        writes=True,
        read_action="deployment.apns.read",
    ),
    AdministrationAction(
        "deployment.apns.configure",
        "deployment",
        "GET",
        "",
        "Have the administrator enter the APNs private key in the secure console form, then inspect readiness.",
        "deployment:admin",
        handoff="/admin/settings?section=services",
    ),
    AdministrationAction(
        "deployment.branding.upload",
        "deployment",
        "GET",
        "",
        "Upload a logo or favicon in the console without putting image bytes into model context; settings.read verifies the saved URLs.",
        "deployment:admin",
        handoff="/admin/settings?section=identity",
    ),
    AdministrationAction(
        "deployment.logo.clear",
        "deployment",
        "DELETE",
        "/admin/settings/logo",
        "Restore the built-in deployment logo.",
        "deployment:admin",
        writes=True,
        read_action="deployment.settings.read",
    ),
    AdministrationAction(
        "deployment.favicon.clear",
        "deployment",
        "DELETE",
        "/admin/settings/favicon",
        "Restore the built-in browser icon.",
        "deployment:admin",
        writes=True,
        read_action="deployment.settings.read",
    ),
    AdministrationAction(
        "organization.settings.read",
        "organization",
        "GET",
        "/orgs/{org_id}",
        "Read organization identity, budgets, approval policy, public attribution, proactivity, dictation and voice defaults.",
        "organization membership",
    ),
    AdministrationAction(
        "organization.settings.update",
        "organization",
        "PATCH",
        "/orgs/{org_id}",
        "Change organization settings, voice/speech defaults and vault references. Spending and proactivity changes retain their stronger API checks.",
        "org:settings; budgets:manage for spending",
        writes=True,
        model=OrganizationUpdate,
        read_action="organization.settings.read",
    ),
    AdministrationAction(
        "organization.retention.read",
        "organization",
        "GET",
        "/orgs/{org_id}/retention",
        "Read requested and effective retention alongside deployment bounds.",
        "org:settings",
    ),
    AdministrationAction(
        "organization.retention.update",
        "organization",
        "PUT",
        "/orgs/{org_id}/retention",
        "Set retention per data class. Explicit null means keep forever, not leave unchanged.",
        "org:settings",
        writes=True,
        model=RetentionUpdate,
        read_action="organization.retention.read",
    ),
    AdministrationAction(
        "organization.assistant.read",
        "organization",
        "GET",
        "/assistant/configuration",
        "Read the current Architect configuration without installing or publishing anything.",
        "org:settings",
    ),
    AdministrationAction(
        "organization.assistant.install",
        "organization",
        "POST",
        "/assistant/install",
        "Install or refresh shipped Architect and starter agents. May publish their defaults when a model is ready; never run them.",
        "org:settings",
        writes=True,
        read_action="organization.assistant.read",
    ),
    AdministrationAction(
        "organization.assistant.update",
        "organization",
        "PATCH",
        "/assistant",
        "Enable or disable the Architect and set its greeting. Model, instructions and capabilities are edited through its agent spec.",
        "org:settings",
        writes=True,
        model=AssistantUpdate,
        read_action="organization.assistant.read",
    ),
    AdministrationAction(
        "organization.system_agents.read",
        "organization",
        "GET",
        "/system-agents/configuration",
        "Read memory maintenance and daily briefing configuration, budget and recent history without provisioning profiles.",
        "budgets:manage",
        pagination="local",
    ),
    AdministrationAction(
        "organization.system_agents.update",
        "organization",
        "PUT",
        "/system-agents/{role}",
        "Replace memory maintenance model, enabled state and monthly budget. Daily briefing is configured through organization settings.",
        "budgets:manage",
        writes=True,
        model=SystemAgentUpdate,
        read_action="organization.system_agents.read",
    ),
    AdministrationAction(
        "organization.members.list",
        "organization",
        "GET",
        "/orgs/{org_id}/members",
        "Page organization members and their roles.",
        "members:view",
        pagination="server",
    ),
    AdministrationAction(
        "organization.members.update",
        "organization",
        "PATCH",
        "/orgs/{org_id}/members/{target_user_id}",
        "Change a member's role, preserving assignable-role and last-owner safeguards.",
        "roles:manage",
        writes=True,
        model=OrganizationMemberUpdate,
        read_action="organization.members.list",
    ),
    AdministrationAction(
        "organization.members.remove",
        "organization",
        "DELETE",
        "/orgs/{org_id}/members/{target_user_id}",
        "Remove membership, subject to ownership and directory safeguards.",
        "members:manage",
        writes=True,
        read_action="organization.members.list",
    ),
    AdministrationAction(
        "organization.groups.list",
        "organization",
        "GET",
        "/orgs/{org_id}/groups",
        "Find departments/groups before creating or editing one.",
        "members:view",
        pagination="local",
    ),
    AdministrationAction(
        "organization.groups.create",
        "organization",
        "POST",
        "/orgs/{org_id}/groups",
        "Create an organization group with its explicit name and budget.",
        "members:manage",
        writes=True,
        model=GroupCreate,
        read_action="organization.groups.list",
    ),
    AdministrationAction(
        "organization.groups.update",
        "organization",
        "PATCH",
        "/orgs/{org_id}/groups/{group_id}",
        "Change a group's name, description, icon or spending limit with existing budget checks.",
        "members:manage",
        writes=True,
        model=GroupUpdate,
        read_action="organization.groups.list",
    ),
    AdministrationAction(
        "organization.groups.remove",
        "organization",
        "DELETE",
        "/orgs/{org_id}/groups/{group_id}",
        "Delete a group and the grants/mappings that refer to it.",
        "members:manage",
        writes=True,
        read_action="organization.groups.list",
    ),
    AdministrationAction(
        "organization.groups.members.list",
        "organization",
        "GET",
        "/orgs/{org_id}/groups/{group_id}/members",
        "Read members of a selected department.",
        "members:view",
        pagination="local",
    ),
    AdministrationAction(
        "organization.groups.members.add",
        "organization",
        "POST",
        "/orgs/{org_id}/groups/{group_id}/members",
        "Add an existing organization member to a department.",
        "members:manage or group lead",
        writes=True,
        model=GroupMemberAdd,
        read_action="organization.groups.members.list",
    ),
    AdministrationAction(
        "organization.groups.members.remove",
        "organization",
        "DELETE",
        "/orgs/{org_id}/groups/{group_id}/members/{member_user_id}",
        "Remove a department membership with the same authority as the console.",
        "members:manage or group lead",
        writes=True,
        read_action="organization.groups.members.list",
    ),
    AdministrationAction(
        "organization.groups.lead.update",
        "organization",
        "PATCH",
        "/orgs/{org_id}/groups/{group_id}/members/{member_user_id}",
        "Set or remove a department lead.",
        "members:manage",
        writes=True,
        model=GroupLeadUpdate,
        read_action="organization.groups.members.list",
    ),
    AdministrationAction(
        "organization.invitations.list",
        "organization",
        "GET",
        "/orgs/{org_id}/invitations",
        "Page pending/accepted/revoked invitations without invitation tokens.",
        "members:manage",
        pagination="server",
        filters=("status",),
    ),
    AdministrationAction(
        "organization.invitations.revoke",
        "organization",
        "DELETE",
        "/orgs/{org_id}/invitations/{invitation_id}",
        "Revoke a pending invitation; use invite_member to send a new invitation.",
        "members:manage",
        writes=True,
        read_action="organization.invitations.list",
    ),
)

_ACTIONS = {action.id: action for action in ACTION_CATALOG}


def _action(identity: str) -> AdministrationAction:
    action = _ACTIONS.get(identity)
    if action is None:
        raise ToolError("Unknown administration action. Search list_administration_actions.")
    return action


def _path(action: AdministrationAction, parameters: dict[str, str] | None) -> str:
    parameters = parameters or {}
    names = set(re.findall(r"{([a-z_]+)}", action.path))
    if set(parameters) != names:
        raise ToolError(
            f"Supply exactly these path parameters: {', '.join(sorted(names)) or 'none'}"
        )
    try:
        values = {
            key: str(_ROLE.validate_python(value) if key == "role" else UUID(value))
            for key, value in parameters.items()
        }
    except (ValidationError, ValueError) as error:
        raise ToolError(
            "Path IDs must be UUIDs; role must be a supported system-agent role."
        ) from error
    return action.path.format(**values)


def administration_operations(api: PlatformApi) -> tuple[Operation, ...]:
    async def list_administration_actions(
        q: str | None = None,
        area: Literal["all", "deployment", "organization"] = "all",
        limit: Limit = 10,
        skip: Skip = 0,
    ) -> dict[str, JsonValue]:
        """Search available settings/member/department actions, not their values or all schemas.

        Discovery does not grant authority. Deployment changes need an external
        OAuth connection explicitly granted deployment:admin and a live app admin.
        Organization actions retain tenant, role, scope and spending controls.
        Follow next_skip and load get_administration_schema for the selected action.
        """
        found: list[JsonValue] = []
        for action in ACTION_CATALOG:
            fields = (
                " ".join(
                    f"{key} {field.description or ''}"
                    for key, field in action.model.model_fields.items()
                )
                if action.model is not None
                else ""
            )
            text = f"{action.id} {action.description} {fields}".replace("_", " ").casefold()
            if (area == "all" or area == action.area) and (
                not q or q.replace("_", " ").casefold() in text
            ):
                found.append(
                    {
                        "id": action.id,
                        "area": action.area,
                        "description": action.description,
                        "needs": action.permission,
                        "writes": action.writes,
                        "execution": "console_handoff"
                        if action.handoff
                        else "change_" + action.area
                        if action.writes
                        else "read_administration",
                    }
                )
        return page(found, limit=limit, skip=skip)

    async def get_administration_schema(
        action_id: str,
        pointer: str = "",
        mode: Literal["inspect", "content"] = "inspect",
        limit: Limit = 10,
        skip: Skip = 0,
        offset: Skip = 0,
        chars: Chars = 2000,
        expected_hash: str | None = None,
    ) -> dict[str, JsonValue]:
        """Read one administrative contract on demand. Schema discovery contains no settings values.

        /body is a standalone JSON schema: resolve its $refs against that root.
        /path lists the exact required UUIDs (or system role). /filters lists
        additional supported query keys. Read field definitions before changing
        policy; null and omitted fields differ. Assemble JSON fragments before use.
        """
        action = _action(action_id)
        return details(
            {
                "body": _OBJECT.validate_python(action.model.model_json_schema())
                if action.model is not None
                else {"type": "object", "maxProperties": 0},
                "path": sorted(set(re.findall(r"{([a-z_]+)}", action.path))),
                "filters": list(action.filters),
                "pagination": action.pagination,
                "search": action.search_key is not None or action.pagination == "local",
            },
            path=pointer,
            mode=mode,
            limit=limit,
            skip=skip,
            offset=offset,
            chars=chars,
            expected_hash=expected_hash,
        )

    async def read_administration(
        action_id: str,
        parameters: dict[str, str] | None = None,
        filters: dict[str, str] | None = None,
        q: str | None = None,
        limit: Limit = 10,
        skip: Skip = 0,
        detailed: bool = False,
    ) -> dict[str, JsonValue]:
        """Read one discovered administrative resource, or a bounded page; never perform a change.

        Use only a listed read action. IDs are exact UUID path parameters, never
        URLs. Search/pagination apply to collections. Bodies are metadata unless
        detailed is requested. Global reads need explicit external OAuth consent;
        organization reads remain limited to the connection's organization.
        Secure credential and image handoffs return the console form, not values.
        """
        action = _action(action_id)
        if action.writes:
            raise ToolError("This action changes state. Use its explicit change tool and approval.")
        path = _path(action, parameters)
        if action.handoff:
            return {
                "action": action.id,
                "user_action_required": True,
                "url": settings.FRONTEND_URL.rstrip("/") + action.handoff,
                "instruction": "The person enters the credential or uploads the image in this form. Never request or print secret values; verify the saved metadata afterwards.",
            }
        filters = filters or {}
        if set(filters) - set(action.filters):
            raise ToolError("Unsupported query key; inspect this action's filters schema.")
        query: dict[str, str | int] = dict(filters)
        if action.pagination == "server":
            query.update(limit=limit, skip=skip)
        if q and action.search_key is not None:
            query[action.search_key] = q
        elif q and action.pagination != "local":
            raise ToolError(
                "This action has no search; narrow its identity or page the collection."
            )
        response = _JSON.validate_python(await api.request("GET", path, params=query or None))
        if action.pagination != "none":
            return listing(
                response,
                local=action.pagination == "local",
                q=q if action.pagination == "local" else None,
                limit=limit,
                skip=skip,
                detailed=detailed,
            )
        return _OBJECT.validate_python(response)

    async def change(
        area: Area,
        action_id: str,
        parameters: dict[str, str] | None,
        changes: dict[str, JsonValue] | None,
    ) -> dict[str, JsonValue]:
        action = _action(action_id)
        if action.area != area or not action.writes:
            raise ToolError(
                "Choose a write action from this administration area; reads and handoffs cannot be executed here."
            )
        path = _path(action, parameters)
        if action.model is None:
            if changes:
                raise ToolError("This action takes no body.")
            body = None
        else:
            try:
                body = action.model.model_validate(changes or {}, extra="forbid").model_dump(
                    mode="json", exclude_unset=True
                )
            except ValidationError as error:
                raise ToolError(
                    json.dumps(
                        error.errors(include_input=False, include_context=False, include_url=False)[
                            :5
                        ],
                        ensure_ascii=False,
                        default=str,
                    )
                ) from error
        response = _JSON.validate_python(await api.request(action.method, path, json=body))
        read_parameters: dict[str, JsonValue] = {
            key: value
            for key, value in (parameters or {}).items()
            if action.read_action is not None
            and "{" + key + "}" in _ACTIONS[action.read_action].path
        }
        return {
            "action": action.id,
            "request_completed": True,
            "read_tool": "read_administration",
            "read_action": action.read_action,
            "parameters": read_parameters,
            "result": metadata(response) if len(encoded(response).encode()) > 12000 else response,
            "instruction": "The API request completed, not necessarily its background work. Read the saved state; never repeat a write just to obtain its body.",
        }

    async def change_deployment(
        action_id: str,
        parameters: dict[str, str] | None = None,
        changes: dict[str, JsonValue] | None = None,
    ) -> dict[str, JsonValue]:
        """Perform one reviewed deployment action; never accepts arbitrary routes or HTTP methods.

        External OAuth only: requires explicit deployment:admin plus the current
        application-admin flag. Agents/routines and organization keys cannot borrow
        this scope. Read the selected action's schema first and explain the exact
        change. Updates may restart the server; inspect their receipt after reconnecting.
        """
        return await change("deployment", action_id, parameters, changes)

    async def change_organization(
        action_id: str,
        parameters: dict[str, str] | None = None,
        changes: dict[str, JsonValue] | None = None,
    ) -> dict[str, JsonValue]:
        """Perform one reviewed organization settings/member/group change through its existing API.

        Needs the selected action's permissions, including stronger budget/role
        checks. The connection's tenant binding is unchanged. Fields left out stay
        unchanged except explicit replacement contracts (system-agent settings).
        Every call asks; it cannot waive proactivity or membership approval floors.
        """
        return await change("organization", action_id, parameters, changes)

    operations = (
        (list_administration_actions, False),
        (get_administration_schema, False),
        (read_administration, False),
        (change_deployment, True),
        (change_organization, True),
    )
    return tuple((function.__name__, function, writes) for function, writes in operations)
