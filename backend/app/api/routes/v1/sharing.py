"""Sharing endpoints for every shareable resource.

Agents, collections, skills, context files, tables, vault secrets and artifacts each get the same
four routes,
generated from one definition in `_sharing_routes.build_sharing_router`, wired to
the per-resource loader from `_sharing_loaders`.
"""

from app.api.routes.v1._sharing_loaders import (
    load_agent,
    load_artifact,
    load_collection,
    load_context,
    load_secret,
    load_skill,
    load_table,
    load_workflow,
)
from app.api.routes.v1._sharing_routes import build_sharing_router
from app.services.access import AGENT, ARTIFACT, COLLECTION, CONTEXT, SECRET, SKILL, TABLE, WORKFLOW

agent_sharing_router = build_sharing_router(resource_type=AGENT, load=load_agent)
collection_sharing_router = build_sharing_router(resource_type=COLLECTION, load=load_collection)
skill_sharing_router = build_sharing_router(resource_type=SKILL, load=load_skill)
context_sharing_router = build_sharing_router(resource_type=CONTEXT, load=load_context)
secret_sharing_router = build_sharing_router(resource_type=SECRET, load=load_secret)
table_sharing_router = build_sharing_router(resource_type=TABLE, load=load_table)
workflow_sharing_router = build_sharing_router(resource_type=WORKFLOW, load=load_workflow)
artifact_sharing_router = build_sharing_router(resource_type=ARTIFACT, load=load_artifact)
