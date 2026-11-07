"""Compile a watch's approved sources without borrowing a newly published agent's reach.

A read-only watch approves one personal account and the selected agent's attached
knowledge/context. Other tools, delegates, accounts and executable skills are
outside that approval. Instructions, model and stricter tool/resource settings
continue to come from the selected published version.
"""

import hashlib
import json

from app.agents.mcp import McpSourceIdentity
from app.agents.spec import AgentSpec, CapabilityBindingSpec, PersonalMcpServerRef
from app.core.exceptions import AuthorizationError
from app.db.models.mcp_connection import McpConnection
from app.schemas.watch_sources import WatchSources
from app.services.integrations import PRODUCTS, AccountSelection


def _binding(spec: AgentSpec, catalog_key: str | None) -> PersonalMcpServerRef:
    for ref in spec.mcp_servers:
        if isinstance(ref, PersonalMcpServerRef) and ref.catalog_key == catalog_key:
            return ref
    raise AuthorizationError(
        message="This agent does not have a personal binding for the watched service. Configure the agent before starting the watch."
    )


def _intersection(
    left: list[str] | tuple[str, ...] | None, right: list[str] | None
) -> tuple[str, ...] | None:
    if left is None:
        return None if right is None else tuple(right)
    return tuple(tool for tool in left if right is None or tool in right)


def _native_binding(spec: AgentSpec, product_id: str) -> CapabilityBindingSpec:
    binding = next((b for b in spec.capabilities if b.id == product_id and b.enabled), None)
    if binding is None or binding.approval == "required":
        raise AuthorizationError(
            message="The watched product must be enabled for unattended reading on this agent"
        )
    selection = AccountSelection.model_validate(binding.config)
    readable = {
        f"{product_id}_{op.id}" for op in PRODUCTS[product_id].operations if not op.side_effecting
    }
    if readable.intersection(selection.disabled_tools) or any(
        binding.tool_approval.get(tool_id) == "required" for tool_id in readable
    ):
        raise AuthorizationError(
            message="A watch cannot bypass disabled or approval-gated product reads"
        )

    if selection.account != "personal":
        raise AuthorizationError(message="A watch reads only a personal integration account")
    return binding


def _native_hash(binding: CapabilityBindingSpec) -> str:
    return hashlib.sha256(json.dumps(binding.config, sort_keys=True).encode()).hexdigest()


def _approve_native(
    spec: AgentSpec, connection: McpConnection, product_id: str | None = None
) -> WatchSources:
    product_id = product_id or {
        "google": "gmail",
        "microsoft": "outlook_mail",
        "slack": "slack",
        "imap": "imap_mail",
        "odoo": "odoo_contacts",
    }.get(connection.catalog_key or "")
    if (
        product_id
        not in {
            "gmail",
            "google_calendar",
            "outlook_mail",
            "outlook_calendar",
            "teams",
            "slack",
            "imap_mail",
            "odoo_contacts",
            "odoo_crm",
            "odoo_sales",
            "odoo_accounting",
            "odoo_inventory",
            "odoo_projects",
        }
        or PRODUCTS[product_id].provider != connection.catalog_key
    ):
        raise AuthorizationError(
            message="This integration product cannot read the selected account"
        )
    binding = _native_binding(spec, product_id)
    selection = AccountSelection.model_validate(binding.config)
    from app.services.integrations import can_read_feed

    if not can_read_feed(connection, product_id, tuple(selection.channels)):
        raise AuthorizationError(
            message="Reconnect this watch account with the product's read permissions"
        )
    if selection.account_name and selection.account_name not in {
        connection.name,
        connection.label,
        connection.account_email,
    }:
        raise AuthorizationError(message="This agent targets a different named integration account")
    if (
        product_id in {"slack", "teams"}
        and not selection.channels
        and connection.auth_type != "application"
    ):
        raise AuthorizationError(
            message="Choose the conversations in this agent's integration capability first"
        )
    return WatchSources(
        integration_product_id=product_id,
        integration_binding_hash=_native_hash(binding),
        integration_channels=tuple(selection.channels),
        connection_id=connection.id,
        authorization_generation=connection.authorization_generation,
        catalog_key=connection.catalog_key or "",
        endpoint_hash=hashlib.sha256(connection.url.encode()).hexdigest(),
        allowed_tools=("read_integration_changes",),
        collection_ids=tuple(spec.collection_ids),
        context_ids=tuple(spec.context_ids),
    )


def approve_sources(
    spec: AgentSpec, connection: McpConnection, product_id: str | None = None
) -> WatchSources:
    if connection.purpose == "account":
        return _approve_native(spec, connection, product_id)
    ref = _binding(spec, connection.catalog_key)
    _unattended_reads(spec, ref)
    tools = _intersection(ref.allowed_tools, connection.allowed_tools)
    if tools == ():
        raise AuthorizationError(message="This agent has no allowed tools for the watched account.")
    return WatchSources(
        connection_id=connection.id,
        authorization_generation=connection.authorization_generation,
        catalog_key=ref.catalog_key,
        endpoint_hash=hashlib.sha256(connection.url.encode()).hexdigest(),
        allowed_tools=tools,
        collection_ids=tuple(spec.collection_ids),
        context_ids=tuple(spec.context_ids),
    )


def constrain_sources(spec: AgentSpec, approved: WatchSources) -> AgentSpec:
    """A later publication can narrow, but never widen, this watch's source approval."""
    if approved.integration_product_id is not None:
        binding = _native_binding(spec, approved.integration_product_id)
        if _native_hash(binding) != approved.integration_binding_hash:
            raise AuthorizationError(
                message="Review this watch's integration account settings after the agent changed"
            )
        return spec.model_copy(
            update={
                "capabilities": [
                    b
                    for b in spec.capabilities
                    if b.id
                    in {"knowledge", "context", "guardrails", "planning", "system_reminders"}
                ],
                "mcp_servers": [],
                "skill_ids": [],
                "subagents": [],
                "external_agents": [],
                "collection_ids": [i for i in spec.collection_ids if i in approved.collection_ids],
                "context_ids": [i for i in spec.context_ids if i in approved.context_ids],
                "code_mode": spec.code_mode.model_copy(update={"enabled": False}),
            }
        )
    current = _binding(spec, approved.catalog_key)
    _unattended_reads(spec, current)
    tools = _intersection(approved.allowed_tools, current.allowed_tools)
    if tools == ():
        raise AuthorizationError(
            message="The published agent no longer has approved tools for this watch."
        )
    return spec.model_copy(
        update={
            "capabilities": [
                binding
                for binding in spec.capabilities
                if binding.id
                in {"knowledge", "context", "guardrails", "planning", "system_reminders"}
            ],
            "mcp_servers": [
                current.model_copy(update={"allowed_tools": None if tools is None else list(tools)})
            ],
            "collection_ids": [
                identifier
                for identifier in spec.collection_ids
                if identifier in approved.collection_ids
            ],
            "context_ids": [
                identifier for identifier in spec.context_ids if identifier in approved.context_ids
            ],
            "code_mode": spec.code_mode.model_copy(update={"enabled": False}),
            "skill_ids": [],
            "subagents": [],
            "external_agents": [],
        }
    )


def _unattended_reads(spec: AgentSpec, ref: PersonalMcpServerRef) -> None:
    if ref.approval == "all" or any(
        binding.approval == "required" or "required" in binding.tool_approval.values()
        for binding in spec.capabilities
        if binding.id in {"knowledge", "context", "guardrails", "planning", "system_reminders"}
    ):
        raise AuthorizationError(
            message="This agent requires interactive approval for watch reads. Review its read approvals before starting an unattended watch."
        )


def source_identity(approved: WatchSources) -> McpSourceIdentity:
    if approved.authorization_generation is None:
        raise AuthorizationError(
            message="Review this watch's sources after the integration upgrade."
        )
    return McpSourceIdentity(
        endpoint_hash=approved.endpoint_hash,
        authorization_generation=approved.authorization_generation,
    )
