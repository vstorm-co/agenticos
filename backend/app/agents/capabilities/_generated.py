"""Where a file an agent generated goes: the same two places, whatever it is.

An image, a clip of speech and a video are kept and shown the same way (#2259,
#2260), and this is the one copy of how. The bytes are always stored
organization-scoped (:mod:`app.services.generated_media`) and handed back as a
URL the interface renders. When the run also has a workspace open - an agent with
the sandbox capability - the same bytes are written into it under `output/`, so a
later step can build with what was just made. An agent without a workspace still
generates; it has nowhere to build with the result, which is the honest
difference between the two.

What is kept is bounded (#2310): each file is recorded against its organization
and its conversation, and :func:`quota_refusal` is asked before a tool spends
anything, so a tenant past its generated-media quota is told so rather than
billed for a file it could not keep.
"""

import logging
from dataclasses import dataclass

import httpx
from pydantic_ai.tools import RunContext
from pydantic_ai.workspaces import WorkspaceError

from app.agents.deps import AgentDeps
from app.services.generated_media import (
    generated_media_quota_reached,
    generated_media_url,
    keep_generated_media,
)

logger = logging.getLogger(__name__)

WORKSPACE_OUTPUT_DIR = "output"
"""Where a generated file lands in the run's workspace, when there is one.

A single well-known directory so the model can be told where to look for what it
made without the path being an argument it has to remember and repeat.

Relative to the working directory, for the reason `UPLOAD_DIR` is: an absolute
path is resolved as absolute, which put a generated image outside the workspace -
unreachable by the agent's own shell, absent from the browser, and not in the
snapshot a channel diffs to decide what to post back (#1039).
"""


@dataclass(frozen=True)
class StoredMedia:
    """Where a generated file was kept.

    `filename` and `url` are `None` only on a run with no organization to scope
    storage to (a preview, a test); `workspace_path` is `None` where no workspace
    was open or it had no room.
    """

    filename: str | None
    url: str | None
    workspace_path: str | None


async def quota_refusal(ctx: RunContext[AgentDeps], *, verdict: str) -> str | None:
    """The tool's answer when its organization has used its generated-media quota.

    A returned answer rather than a retry or an exception: nothing the model
    can rephrase changes it, and the run goes on - the model tells the person
    rather than the turn ending on an error.

    Args:
        ctx: The tool call's context, for the organization.
        verdict: How the tool says it did nothing - "Not made", "Not spoken".
    """
    organization_id = ctx.deps.organization_id
    if organization_id is None or not await generated_media_quota_reached(organization_id):
        return None
    return (
        f"{verdict}: this organization has used its storage for generated media. Tell the "
        "user; deleting conversations with generated files frees it, files made outside a "
        "conversation are deleted within a week, or the deployment's operator can raise "
        "GENERATED_MEDIA_QUOTA_MB."
    )


async def store_generated(ctx: RunContext[AgentDeps], data: bytes, *, filename: str) -> StoredMedia:
    """Keep one generated file, and write it into the workspace if one is open.

    Args:
        ctx: The tool call's context, for the organization and the workspace.
        data: The file's bytes.
        filename: A name such as `image.png`; its extension types the file.
    """
    organization_id = ctx.deps.organization_id
    stored: str | None = None
    url: str | None = None
    if organization_id is not None:
        stored = await keep_generated_media(
            organization_id, data, filename=filename, conversation_id=ctx.deps.conversation_id
        )
        url = generated_media_url(stored)
        ctx.deps.generated_files.add(stored)

    workspace_path: str | None = None
    if ctx.workspace.attached:
        leaf = stored or filename
        try:
            await ctx.workspace.write_bytes(f"{WORKSPACE_OUTPUT_DIR}/{leaf}", data)
            workspace_path = f"{WORKSPACE_OUTPUT_DIR}/{leaf}"
        except (OSError, WorkspaceError, httpx.HTTPError) as exc:
            # A full workspace - a `state` document past its ceiling raises
            # `OSError`, a container's shell `WorkspaceError` - or a sandbox
            # service that would not open a session, whose client raises its HTTP
            # error unmapped. The file was generated, paid for, and is stored and
            # linked above; naming a path that holds nothing would send the model
            # to it, and failing the call would lose the file with the turn.
            logger.warning(
                "generated_media_not_written",
                extra={"leaf": leaf, "error": exc.__class__.__name__},
            )
    return StoredMedia(filename=stored, url=url, workspace_path=workspace_path)
