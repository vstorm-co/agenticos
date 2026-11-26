"""Channel bot management routes.

Bots are organization resources: every endpoint here acts on the caller's
active organization and requires `channels:manage`. The inbound webhook routes
live elsewhere and are deliberately unscoped.
"""

from dataclasses import asdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    Auth,
    ChannelBindingRequestSvc,
    DiscordRoleMappingSvc,
    OrgChannelBotSvc,
    require,
)
from app.core.permissions import Perm
from app.schemas.channel_binding_request import (
    ChannelBindingRequestList,
    ChannelBindingRequestRead,
)
from app.schemas.channel_bot import (
    ChannelBotCreate,
    ChannelBotList,
    ChannelBotRead,
    ChannelBotUpdate,
    ChannelDiagnosticsRead,
    ChannelSessionList,
    CustomerErasureRead,
    PublicLineRead,
    TeamsConversationList,
    TeamsConversationRead,
    WhatsAppCustomerForget,
    WhatsAppCustomerList,
    WhatsAppCustomerSearch,
    WhatsAppTemplateList,
    WhatsAppTemplateRead,
)
from app.schemas.discord_role_mapping import (
    DiscordRoleMappingCreate,
    DiscordRoleMappingList,
    DiscordRoleMappingRead,
    DiscordServerList,
    DiscordServerRead,
    DiscordServerRoleRead,
)

router = APIRouter()


@router.get(
    "/bots", response_model=ChannelBotList, dependencies=[Depends(require(Perm.CHANNELS_MANAGE))]
)
async def list_bots(
    service: OrgChannelBotSvc,
    skip: int = Query(0, ge=0, description="Items to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max items to return"),
) -> Any:
    """List the organization's registered channel bots."""
    items, total = await service.list_all(skip=skip, limit=limit)
    return ChannelBotList(items=items, total=total)


@router.get(
    "/binding-requests",
    response_model=ChannelBindingRequestList,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def list_binding_requests(
    ctx: Auth,
    service: ChannelBindingRequestSvc,
    skip: int = Query(0, ge=0, description="Items to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max items to return"),
) -> Any:
    """The pending requests to bind an agent to a bot that answers people with no account."""
    items, total = await service.list_pending(ctx, skip, limit)
    return ChannelBindingRequestList(items=items, total=total)


@router.post(
    "/binding-requests/{request_id}/approve",
    response_model=ChannelBindingRequestRead,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def approve_binding_request(
    request_id: UUID, ctx: Auth, service: ChannelBindingRequestSvc
) -> Any:
    """Apply what the request asks, as you, and tell the one who asked."""
    return await service.approve(ctx, request_id)


@router.post(
    "/binding-requests/{request_id}/decline",
    response_model=ChannelBindingRequestRead,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def decline_binding_request(
    request_id: UUID, ctx: Auth, service: ChannelBindingRequestSvc
) -> Any:
    """Decline the request. Nothing is applied; the one who asked is told."""
    return await service.decline(ctx, request_id)


@router.post(
    "/bots",
    response_model=ChannelBotRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def create_bot(
    data: ChannelBotCreate,
    ctx: Auth,
    service: OrgChannelBotSvc,
) -> Any:
    """Create a new channel bot. The bot token is encrypted before storage."""
    return await service.create(data, actor_user_id=ctx.subject_id)


@router.get(
    "/bots/{bot_id}",
    response_model=ChannelBotRead,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def get_bot(
    bot_id: UUID,
    service: OrgChannelBotSvc,
) -> Any:
    """Get a channel bot by ID.

    Carries `inherited_speech_to_text` - what the bot's voice notes would go to
    if it inherited its transcription engine - which the listing leaves out.
    """
    return await service.read(bot_id)


@router.get(
    "/bots/{bot_id}/public-line",
    response_model=PublicLineRead,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def get_public_line(bot_id: UUID, service: OrgChannelBotSvc) -> Any:
    """What the bot would answer people with no account with, and what bounds it.

    The warning to read before switching the line on: the knowledge, tools and
    delegates of the agent it serves, the spending limit, the per-customer rate,
    approval expiry, file and voice limits, and what a customer can never reach.
    """
    return await service.public_line(bot_id)


@router.get(
    "/bots/{bot_id}/diagnostics",
    response_model=ChannelDiagnosticsRead,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def get_bot_diagnostics(bot_id: UUID, service: OrgChannelBotSvc, ctx: Auth) -> Any:
    """Inspect configuration for the signed-in caller without running tools or a model.

    Personal checks describe this caller's account, not everybody in the channel.
    Stored connections are not probed; provider authorization can still expire.
    """
    return await service.diagnostics(bot_id, ctx)


@router.get(
    "/bots/{bot_id}/teams-app-package",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def get_teams_app_package(bot_id: UUID, service: OrgChannelBotSvc) -> Any:
    """The Teams app package for this bot, to upload to the tenant's app catalog (#1985).

    A zip of the manifest naming the bot's Azure registration and the two icons
    Teams requires.
    """
    package = await service.teams_app_package(bot_id)
    return Response(
        content=package,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="teams-app.zip"'},
    )


@router.get(
    "/teams-conversations",
    response_model=TeamsConversationList,
    dependencies=[Depends(require(Perm.AGENTS_VIEW))],
)
async def list_teams_conversations(service: OrgChannelBotSvc) -> Any:
    """Where a trigger can post its answer: the Teams channels and group chats the
    organization's bots are in (#1985)."""
    return TeamsConversationList(
        items=[
            TeamsConversationRead.model_validate(row, from_attributes=True)
            for row in await service.teams_conversations()
        ]
    )


@router.get(
    "/bots/{bot_id}/slack-manifest",
    response_model=dict[str, Any],
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def get_slack_manifest(bot_id: UUID, service: OrgChannelBotSvc) -> Any:
    """The Slack app's whole configuration for this bot, to paste into Slack (#2067).

    Its events, buttons, `/agent` and the message shortcut point at this
    deployment, with the assistant pane, App Home and the scopes they use.
    """
    return await service.slack_manifest(bot_id)


@router.get(
    "/bots/{bot_id}/whatsapp-templates",
    response_model=WhatsAppTemplateList,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def list_whatsapp_templates(bot_id: UUID, service: OrgChannelBotSvc) -> Any:
    """The templates on this WhatsApp bot's account that can carry a late answer (#2076).

    Read from Meta each time: only approved utility templates with one variable in
    their body, which is what a late answer fits into. A 503 says Meta refused the
    listing or the bot's token; its `details.code` is Graph's own code.
    """
    templates = await service.whatsapp_templates(bot_id)
    return WhatsAppTemplateList(
        items=[WhatsAppTemplateRead(**asdict(template)) for template in templates],
        total=len(templates),
    )


@router.patch(
    "/bots/{bot_id}",
    response_model=ChannelBotRead,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def update_bot(
    bot_id: UUID,
    data: ChannelBotUpdate,
    ctx: Auth,
    service: OrgChannelBotSvc,
) -> Any:
    """Update a channel bot.

    A new token for a Discord bot with role mappings is refused to somebody who
    could not delete those mappings.
    """
    return await service.update(bot_id, data, ctx)


@router.delete(
    "/bots/{bot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def delete_bot(
    bot_id: UUID,
    service: OrgChannelBotSvc,
    ctx: Auth,
) -> None:
    """Delete a channel bot and stop any active polling.

    Refused when the bot's Discord role mappings place people the caller could
    not remove one mapping at a time.
    """
    await service.delete(bot_id, ctx)


@router.post(
    "/bots/{bot_id}/activate",
    response_model=ChannelBotRead,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def activate_bot(
    bot_id: UUID,
    service: OrgChannelBotSvc,
) -> Any:
    """Activate a channel bot."""
    return await service.activate(bot_id)


@router.post(
    "/bots/{bot_id}/deactivate",
    response_model=ChannelBotRead,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def deactivate_bot(
    bot_id: UUID,
    service: OrgChannelBotSvc,
) -> Any:
    """Deactivate a channel bot."""
    return await service.deactivate(bot_id)


@router.post(
    "/bots/{bot_id}/webhook/register",
    response_model=None,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def register_webhook(
    bot_id: UUID,
    service: OrgChannelBotSvc,
) -> Any:
    """Register a webhook URL with the bot's platform."""
    return await service.register_webhook(bot_id)


@router.post(
    "/bots/{bot_id}/webhook/delete",
    response_model=None,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def delete_webhook(
    bot_id: UUID,
    service: OrgChannelBotSvc,
) -> Any:
    """Remove the webhook from the bot's platform (switches to polling mode)."""
    return await service.delete_webhook(bot_id)


@router.get(
    "/bots/{bot_id}/sessions",
    response_model=ChannelSessionList,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def list_sessions(
    bot_id: UUID,
    service: OrgChannelBotSvc,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """List channel sessions for this bot."""
    items, total = await service.list_sessions(bot_id, skip=skip, limit=limit)
    return ChannelSessionList(items=items, total=total)


@router.get(
    "/bots/{bot_id}/discord-servers",
    response_model=DiscordServerList,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def list_discord_servers(bot_id: UUID, service: DiscordRoleMappingSvc, ctx: Auth) -> Any:
    """The servers a Discord bot is in, and the roles in each a mapping may name (#2569).

    Read from Discord on every call. `@everyone` and the roles Discord manages
    for a bot are left out. Requires `members:manage` as well.
    """
    servers = await service.servers(ctx, bot_id)
    items = [
        DiscordServerRead(
            id=server.id,
            name=server.name,
            roles=[DiscordServerRoleRead(id=role.id, name=role.name) for role in server.roles],
        )
        for server in servers
    ]
    return DiscordServerList(items=items, total=len(items))


@router.get(
    "/bots/{bot_id}/role-mappings",
    response_model=DiscordRoleMappingList,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def list_role_mappings(bot_id: UUID, service: DiscordRoleMappingSvc, ctx: Auth) -> Any:
    """Every Discord server role this bot maps to a group. Requires `members:manage` as well."""
    rows = await service.list_mappings(ctx, bot_id)
    items = [
        DiscordRoleMappingRead.model_validate(mapping).model_copy(update={"group_name": name})
        for mapping, name in rows
    ]
    return DiscordRoleMappingList(items=items, total=len(items))


@router.post(
    "/bots/{bot_id}/role-mappings",
    response_model=DiscordRoleMappingRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def create_role_mapping(
    bot_id: UUID, data: DiscordRoleMappingCreate, service: DiscordRoleMappingSvc, ctx: Auth
) -> Any:
    """Map a role in one of the bot's servers to a group, and optionally a role, here.

    Requires `members:manage`, and `roles:manage` with a role the caller's own
    strictly outranks when one is named. A linked member holding the Discord
    role is placed at their next turn.
    """
    mapping, group_name = await service.create(ctx, bot_id, data)
    return DiscordRoleMappingRead.model_validate(mapping).model_copy(
        update={"group_name": group_name}
    )


@router.delete(
    "/bots/{bot_id}/role-mappings/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def delete_role_mapping(
    bot_id: UUID, mapping_id: UUID, service: DiscordRoleMappingSvc, ctx: Auth
) -> None:
    """Delete a mapping. What it gave people is taken back by the next role sync."""
    await service.delete(ctx, bot_id, mapping_id)


@router.get(
    "/bots/{bot_id}/whatsapp-customers",
    response_model=WhatsAppCustomerList,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def list_whatsapp_customers(
    bot_id: UUID,
    service: OrgChannelBotSvc,
    skip: int = Query(0, ge=0, description="Items to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max items to return"),
) -> Any:
    """A WhatsApp bot's customers with their full numbers, for `channels:manage` only."""
    return await service.whatsapp_customers(bot_id, skip=skip, limit=limit)


@router.post(
    "/bots/{bot_id}/whatsapp-customers/search",
    response_model=WhatsAppCustomerList,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def search_whatsapp_customers(
    bot_id: UUID,
    data: WhatsAppCustomerSearch,
    service: OrgChannelBotSvc,
) -> Any:
    """Find a WhatsApp bot's customers by number. The number is in the body, not the address."""
    return await service.find_whatsapp_customers(bot_id, data.phone)


@router.post(
    "/bots/{bot_id}/whatsapp-customers/forget",
    response_model=CustomerErasureRead,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def forget_whatsapp_customer(
    bot_id: UUID,
    data: WhatsAppCustomerForget,
    ctx: Auth,
    service: OrgChannelBotSvc,
) -> Any:
    """Erase a WhatsApp customer and what is kept of them; refused for a linked account (409)."""
    return await service.forget_whatsapp_customer(
        bot_id, data.customer_id, actor_user_id=ctx.subject_id
    )
