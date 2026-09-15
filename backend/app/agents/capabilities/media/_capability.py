"""Keeping a compacted history's pictures out of the database and off the wire."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai_harness.media import externalize_media, restore_media

from app.agents.capabilities.media._store import OrganizationMediaStore

logger = logging.getLogger(__name__)


@dataclass
class MediaOffload(AbstractCapability[AgentDepsT]):
    """Replaces large binary and text parts in a stored history with a reference.

    **What it is for, and the one place media actually piles up.** An attachment
    reaches the model once, on the turn it was attached: the ordinary history is
    rebuilt from the transcript's text, so a picture is not re-sent on every
    later turn. The exception is a conversation that has been *compacted* - the
    library's own dump of `all_messages()` is stored whole and replayed exactly
    as the model last saw it, base64 and all, until the next summary. That blob
    is written to Postgres and sent on every turn in between.

    So this walks the dump before it is stored, writes anything over the
    threshold to the organization's media store, and leaves a
    `media+sha256://…` marker in its place. Reading is the inverse and is *not*
    conditional on this capability - a conversation whose agent was unbound
    afterwards still has markers in its history, and a marker nobody re-inlines
    is a picture the model is told about in a language it does not read.

    **It contributes nothing to the run itself.** No tools, no instructions: a
    model cannot usefully decide to offload its own history, and there is nothing
    here for a person to approve. The capability is the *decision* to offload,
    and the surfaces read it off the built agent the way they already read
    compaction's gauge.
    """

    organization_id: UUID | None = None
    """Whose store the bytes go to. `None` in a preview or a test that builds
    capabilities without a run, where nothing is offloaded rather than offloaded
    somewhere shared."""

    conversation_id: UUID | None = None
    """Which thread's prefix they live under - the whole of their lifetime.

    Content-addressed objects record nothing about who still references them, so
    they are stored under the prefix of the thing that does and removed when it
    goes. `None` is a run with no conversation - a one-shot API call - which
    offloads nothing, because there would be nothing to delete it with.
    """

    threshold_bytes: int = 32_768
    """Below this, a part is left where it is.

    A marker is about 120 bytes and costs a store round trip on both sides, so
    offloading a small thumbnail makes the history bigger and slower. The default
    is well under the smallest picture worth sending and well over every text
    part that is really a sentence.
    """

    _store: OrganizationMediaStore | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def store(self) -> OrganizationMediaStore | None:
        """This thread's media store, built once, or `None` where it has no home.

        `None` for a run outside an organization or outside a conversation: a
        one-shot API call has no thread to hang the bytes on, and an object with
        nothing that will ever delete it is the failure this capability exists to
        prevent rather than a smaller history.
        """
        if self.organization_id is None or self.conversation_id is None:
            return None
        if self._store is None:
            self._store = OrganizationMediaStore(self.organization_id, self.conversation_id)
        return self._store

    async def externalize(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The history to store, with its large parts written out and referenced.

        Returns the history unchanged when there is no store - a preview - and
        when the walk fails. **A failure here must not lose the summary**: the
        alternative to a smaller history is the history, and losing it costs the
        conversation the compaction it just paid a model to produce.
        """
        try:
            # Inside the guard, because building one is `mkdir` on a volume that
            # may not be there: a turn that has already paid a model for a
            # summary must not fail on the step that was going to make it
            # smaller.
            store = self.store()
            if store is None:
                return messages
            walked = await externalize_media(
                messages, media_store=store, threshold_bytes=self.threshold_bytes
            )
        except Exception:
            logger.exception(
                "media_externalize_failed", extra={"organization_id": str(self.organization_id)}
            )
            return messages
        return walked if isinstance(walked, list) else messages


async def restore_stored_media(
    messages: list[dict[str, Any]], *, organization_id: UUID, conversation_id: UUID
) -> list[dict[str, Any]]:
    """Re-inline whatever a stored history references, before it is replayed.

    **Unconditional, and that is the point.** Offloading is the capability's
    decision; restoring is not, because a conversation whose agent was unbound
    afterwards - or bound to a different agent on the next turn - still has
    markers in its stored history, and a marker nobody re-inlines is a picture
    the model is handed in a language it does not read. The walk over a history
    that carries none is a tree traversal that changes nothing.

    A failure returns the history as stored rather than raising: the markers then
    reach the model as the marker dicts they are, which is a worse answer and
    still an answer. Losing the conversation for a storage hiccup is not.
    """
    if not messages:
        return messages
    try:
        walked = await restore_media(
            messages, media_store=OrganizationMediaStore(organization_id, conversation_id)
        )
    except Exception:
        logger.exception("media_restore_failed", extra={"organization_id": str(organization_id)})
        return messages
    return walked if isinstance(walked, list) else messages


async def offloaded_history(
    capabilities: list[Any], messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The compacted history to store, offloaded if the agent asked for it.

    Read off the built agent's capability list rather than passed down, the way
    the context gauge already is: the surface that persists the turn is the one
    that decides what is stored. Unbound - or bound on a run with no thread to
    hang the bytes on - the history is stored as it was.

    Shared by both run paths on purpose. `ChatAgentRunner.run` and
    `AgentRunnerService._run` each dump `all_messages()` and each hand the result
    to `keep_summary`, and hooking one of them gave the capability to the
    WebSocket chat and to nothing else - not the API, not a channel mention, not
    an embed, not a trigger.
    """
    offload = next((cap for cap in capabilities if isinstance(cap, MediaOffload)), None)
    if offload is None:
        return messages
    return await offload.externalize(messages)
