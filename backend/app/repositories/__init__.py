"""Repository layer for database operations."""
# ruff: noqa: I001, RUF022 - Imports structured for Jinja2 template conditionals

from app.repositories import user as user_repo

from app.repositories import session as session_repo

from app.repositories import conversation as conversation_repo

from app.repositories import rag_document as rag_document_repo
from app.repositories import sync_log as sync_log_repo
from app.repositories import sync_source as sync_source_repo

from app.repositories import chat_file as chat_file_repo

from app.repositories import conversation_share as conversation_share_repo
from app.repositories import message_rating as message_rating_repo

from app.repositories import knowledge_base as knowledge_base_repo

from app.repositories import channel_bot as channel_bot_repo
from app.repositories import channel_identity as channel_identity_repo
from app.repositories import channel_link_request as channel_link_request_repo
from app.repositories import channel_session as channel_session_repo

from app.repositories import agent as agent_repo
from app.repositories import agent_embed as agent_embed_repo
from app.repositories import embed_visitor as embed_visitor_repo
from app.repositories import agent_environment as agent_environment_repo
from app.repositories import agent_exposure as agent_exposure_repo
from app.repositories import agent_run as agent_run_repo
from app.repositories import agent_trigger as agent_trigger_repo
from app.repositories import run_manifest as run_manifest_repo
from app.repositories import agent_workspace as agent_workspace_repo
from app.repositories import sandbox_connection as sandbox_connection_repo
from app.repositories import sandbox_operation as sandbox_operation_repo
from app.repositories import skill_proposal as skill_proposal_repo
from app.repositories import audit_log as audit_log_repo
from app.repositories import ingestion_spend as ingestion_spend_repo
from app.repositories import credential as credential_repo
from app.repositories import resource_grant as resource_grant_repo
from app.repositories import skill as skill_repo
from app.repositories import context as context_repo
from app.repositories import memory as memory_repo

from app.repositories import invitation as invitation_repo
from app.repositories import member as member_repo
from app.repositories import organization as organization_repo

from app.repositories import user_slash_command as user_slash_command_repo

from app.repositories import dashboard_layout as dashboard_layout_repo
from app.repositories import deployment_settings as deployment_settings_repo
from app.repositories import dashboard_preset as dashboard_preset_repo

from app.repositories import mcp_connection as mcp_connection_repo
from app.repositories import organization_secret as organization_secret_repo

__all__ = [
    "user_repo",
    "session_repo",
    "conversation_repo",
    "rag_document_repo",
    "sync_log_repo",
    "sync_source_repo",
    "chat_file_repo",
    "conversation_share_repo",
    "message_rating_repo",
    "knowledge_base_repo",
    "channel_bot_repo",
    "channel_identity_repo",
    "channel_link_request_repo",
    "channel_session_repo",
    "organization_repo",
    "member_repo",
    "invitation_repo",
    "user_slash_command_repo",
    "dashboard_layout_repo",
    "deployment_settings_repo",
    "dashboard_preset_repo",
    "mcp_connection_repo",
    "organization_secret_repo",
    "resource_grant_repo",
    "audit_log_repo",
    "credential_repo",
    "agent_repo",
    "agent_environment_repo",
    "agent_exposure_repo",
    "agent_embed_repo",
    "embed_visitor_repo",
    "agent_run_repo",
    "agent_trigger_repo",
    "run_manifest_repo",
    "agent_workspace_repo",
    "sandbox_connection_repo",
    "sandbox_operation_repo",
    "skill_proposal_repo",
    "ingestion_spend_repo",
    "skill_repo",
    "context_repo",
    "memory_repo",
]
