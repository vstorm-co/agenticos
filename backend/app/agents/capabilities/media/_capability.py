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
        """This organization's media store, built once, or `None` outside a run."""
        if self.organization_id is None:
            return None
        if self._store is None:
            self._store = OrganizationMediaStore(self.organization_id)
        return self._store

    async def externalize(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The history to store, with its large parts written out and referenced.

        Returns the history unchanged when there is no store - a preview - and
        when the walk fails. **A failure here must not lose the summary**: the
        alternative to a smaller history is the history, and losing it costs the
        conversation the compaction it just paid a model to produce.
        """
        store = self.store()
        if store is None:
            return messages
        try:
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
    messages: list[dict[str, Any]], *, organization_id: UUID
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
        walked = await restore_media(messages, media_store=OrganizationMediaStore(organization_id))
    except Exception:
        logger.exception("media_restore_failed", extra={"organization_id": str(organization_id)})
        return messages
    return walked if isinstance(walked, list) else messages
