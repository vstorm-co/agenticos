"""API v1 router aggregation."""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

from fastapi import APIRouter

from app.api.routes.v1 import health
from app.api.routes.v1 import admin_users, auth, users
from app.api.routes.v1 import admin_ratings
from app.api.routes.v1 import oauth
from app.api.routes.v1 import sessions
from app.api.routes.v1 import conversations
from app.api.routes.v1 import admin_conversations
from app.api.routes.v1 import me_mcp_connections
from app.api.routes.v1 import org_mcp_connections
from app.api.routes.v1 import agent
from app.api.routes.v1 import rag
from app.api.routes.v1 import files
from app.api.routes.v1 import channels
from app.api.routes.v1 import audit
from app.api.routes.v1 import sharing
from app.api.routes.v1 import agent_embeds
from app.api.routes.v1 import agent_environments, agent_exposures
from app.api.routes.v1 import agents as agent_registry
from app.api.routes.v1 import model_providers
from app.api.routes.v1 import secrets
from app.api.routes.v1 import runs as agent_runs
from app.api.routes.v1 import skills as agent_skills
from app.api.routes.v1 import permissions
from app.api.routes.v1 import telegram_webhook
from app.api.routes.v1 import slack_webhook
from app.api.routes.v1 import mattermost_webhook
from app.api.routes.v1 import embed as embed_widget
from app.api.routes.v1 import members, organizations
from app.api.routes.v1.invitations import (
    org_router as invitations_org_router,
    token_router as invitations_token_router,
)
from app.api.routes.v1 import knowledge_bases
from app.api.routes.v1 import me_slash_commands
from app.api.routes.v1 import admin_stats
from app.api.routes.v1 import catalog_icons
from app.api.routes.v1 import org_integrations

v1_router = APIRouter()

v1_router.include_router(health.router, tags=["health"])

v1_router.include_router(auth.router, prefix="/auth", tags=["auth"])
v1_router.include_router(users.router, prefix="/users", tags=["users"])
v1_router.include_router(permissions.router, tags=["permissions"])
v1_router.include_router(audit.router, tags=["audit"])
v1_router.include_router(model_providers.router, prefix="/providers", tags=["providers"])
v1_router.include_router(catalog_icons.router, prefix="/catalog", tags=["catalog"])
v1_router.include_router(secrets.router, prefix="/secrets", tags=["secrets"])
v1_router.include_router(agent_registry.router, prefix="/agents", tags=["agents"])
v1_router.include_router(agent_environments.router, prefix="/agents", tags=["agents:environments"])
v1_router.include_router(agent_exposures.router, prefix="/agents", tags=["agents:exposures"])
v1_router.include_router(agent_embeds.router, prefix="/agents", tags=["agents:embeds"])
v1_router.include_router(embed_widget.router, prefix="/embed", tags=["embed"])
v1_router.include_router(agent_runs.router, tags=["runs"])
v1_router.include_router(agent_skills.router, prefix="/skills", tags=["skills"])
v1_router.include_router(
    sharing.collection_sharing_router, prefix="/kb", tags=["collections:sharing"]
)
v1_router.include_router(sharing.agent_sharing_router, prefix="/agents", tags=["agents:sharing"])
v1_router.include_router(sharing.skill_sharing_router, prefix="/skills", tags=["skills:sharing"])
v1_router.include_router(sharing.secret_sharing_router, prefix="/secrets", tags=["secrets:sharing"])

v1_router.include_router(admin_ratings.router, prefix="/admin/ratings", tags=["admin:ratings"])

v1_router.include_router(oauth.router, prefix="/oauth", tags=["oauth"])

v1_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])

v1_router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])

v1_router.include_router(
    org_mcp_connections.router, prefix="/mcp-connections", tags=["mcp-connections"]
)

v1_router.include_router(
    me_mcp_connections.router, prefix="/me/mcp-connections", tags=["me:mcp-connections"]
)

v1_router.include_router(agent.router, tags=["agent"])

v1_router.include_router(rag.router, prefix="/rag", tags=["rag"])

v1_router.include_router(files.router, tags=["files"])

v1_router.include_router(
    admin_conversations.router, prefix="/admin/conversations", tags=["admin-conversations"]
)

v1_router.include_router(admin_users.router, prefix="/admin/users", tags=["admin:users"])

v1_router.include_router(channels.router, prefix="/channels", tags=["channels"])

v1_router.include_router(telegram_webhook.router, prefix="/telegram", tags=["telegram"])

v1_router.include_router(slack_webhook.router, prefix="/slack", tags=["slack"])

v1_router.include_router(mattermost_webhook.router, prefix="/mattermost", tags=["mattermost"])

v1_router.include_router(organizations.router, prefix="/orgs", tags=["organizations"])
v1_router.include_router(members.router, prefix="/orgs", tags=["members"])
v1_router.include_router(invitations_org_router, prefix="/orgs", tags=["invitations"])
v1_router.include_router(invitations_token_router, tags=["invitations"])

v1_router.include_router(knowledge_bases.router, prefix="/kb", tags=["knowledge-bases"])
v1_router.include_router(
    me_slash_commands.router, prefix="/me/slash-commands", tags=["me:slash-commands"]
)
v1_router.include_router(admin_stats.router, prefix="/admin", tags=["admin:stats"])
v1_router.include_router(
    org_integrations.router, prefix="/org/integrations", tags=["org:integrations"]
)
