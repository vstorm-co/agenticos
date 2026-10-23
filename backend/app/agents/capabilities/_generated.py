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
and its conversation, and :func:`admit` is asked before a tool spends anything,
so a tenant past its generated-media quota is told so rather than billed for a
file it could not keep. An admitted call holds its estimated size until its file
is recorded - the :class:`MediaSlot` it is handed - so calls in flight at once
cannot each pass on the same figure.
"""

import logging
from dataclasses import dataclass
from typing import Self
from uuid import UUID

import httpx
from pydantic_ai.tools import RunContext
from pydantic_ai.workspaces import WorkspaceError

from app.agents.deps import AgentDeps
from app.services.generated_media import (
    admit_generated_media,
    generated_media_url,
    keep_generated_media,
    release_generated_media,
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


MEDIA_TOOL_NAMES = frozenset({"generate_image", "generate_speech", "generate_video"})
"""The tools that store a generated file, each the one tool by its name.

Reserved at publish: no other tool may be renamed onto one of these, so a step
called `generate_image` is the image tool in the transcript, the console's tool
catalog and the frames a page streams. What a hosted page's link is minted for
does not lean on it - that is the run's `generated_files`, because an MCP tool's
name is the server's to choose and is never seen at publish.
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


class MediaSlot:
    """One admitted call's hold on its organization's quota, until its file is recorded.

    Used as `async with slot:` around everything from the paid call to
    :func:`store_generated`. Storing the file settles the hold; leaving the
    block without one - a refusal, a failure, a cancelled run - gives it back.
    """

    def __init__(self, organization_id: UUID | None, reservation_id: UUID | None) -> None:
        self.organization_id = organization_id
        self.reservation_id = reservation_id

    def settled(self) -> None:
        """The file is recorded, and the hold went with it."""
        self.reservation_id = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        if self.organization_id is not None and self.reservation_id is not None:
            await release_generated_media(self.organization_id, self.reservation_id)
            self.reservation_id = None


async def admit(
    ctx: RunContext[AgentDeps], *, estimate_bytes: int, verdict: str
) -> MediaSlot | str:
    """Admit one generation call against the quota, or the tool's answer refusing it.

    The refusal is a returned answer rather than a retry or an exception:
    nothing the model can rephrase changes it, and the run goes on - the model
    tells the person rather than the turn ending on an error.

    Args:
        ctx: The tool call's context, for the organization.
        estimate_bytes: The most the call is expected to store - held against
            the quota until its file is recorded.
        verdict: How the tool says it did nothing - "Not made", "Not spoken".
    """
    organization_id = ctx.deps.organization_id
    if organization_id is None:
        return MediaSlot(None, None)
    admission = await admit_generated_media(organization_id, estimate_bytes=estimate_bytes)
    if admission.admitted:
        return MediaSlot(organization_id, admission.reservation_id)
    return (
        f"{verdict}: this organization has used its storage for generated media. Tell the "
        "user; deleting conversations with generated files frees it, files made outside a "
        "conversation are deleted within a week, or the deployment's operator can raise "
        "GENERATED_MEDIA_QUOTA_MB."
    )


async def store_generated(
    ctx: RunContext[AgentDeps], data: bytes, *, filename: str, slot: MediaSlot
) -> StoredMedia:
    """Keep one generated file, and write it into the workspace if one is open.

    Args:
        ctx: The tool call's context, for the organization and the workspace.
        data: The file's bytes.
        filename: A name such as `image.png`; its extension types the file.
        slot: The call's hold on the quota, which the file's record replaces.
    """
    organization_id = ctx.deps.organization_id
    stored: str | None = None
    url: str | None = None
    if organization_id is not None:
        stored = await keep_generated_media(
            organization_id,
            data,
            filename=filename,
            conversation_id=ctx.deps.conversation_id,
            reservation_id=slot.reservation_id,
        )
        slot.settled()
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
