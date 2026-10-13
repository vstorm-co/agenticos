"""Folders for apps, skills, context files and knowledge bases (#2124).

One set of routes per kind, generated from `_folder_routes.build_folder_router`
and wired to the per-resource loader from `_sharing_loaders`: under
`/folders/apps`, `/folders/skills`, `/folders/context` and `/folders/kb`.
"""

from app.api.routes.v1._folder_routes import build_folder_router
from app.api.routes.v1._sharing_loaders import (
    load_artifact,
    load_collection,
    load_context,
    load_skill,
)

app_folders_router = build_folder_router(kind="artifact", load=load_artifact)
skill_folders_router = build_folder_router(kind="skill", load=load_skill)
context_folders_router = build_folder_router(kind="context", load=load_context)
collection_folders_router = build_folder_router(kind="collection", load=load_collection)
