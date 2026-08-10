"""Sharing endpoints for every shareable resource.

Agents, collections, skills and vault secrets each get the same four routes,
generated from one definition in `_sharing_routes.build_sharing_router`, wired to
the per-resource loader from `_sharing_loaders`.
"""

from app.api.routes.v1._sharing_loaders import (
    load_agent,
    load_collection,
    load_secret,
    load_skill,
)
from app.api.routes.v1._sharing_routes import build_sharing_router
from app.services.access import AGENT, COLLECTION, SECRET, SKILL

agent_sharing_router = build_sharing_router(resource_type=AGENT, load=load_agent)
collection_sharing_router = build_sharing_router(resource_type=COLLECTION, load=load_collection)
skill_sharing_router = build_sharing_router(resource_type=SKILL, load=load_skill)
secret_sharing_router = build_sharing_router(resource_type=SECRET, load=load_secret)
