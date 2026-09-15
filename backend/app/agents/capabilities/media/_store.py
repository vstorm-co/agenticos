"""The deployment's own file storage, as a content-addressed media store.

`pydantic_ai_harness.media` ships the walkers and the URI scheme; what it cannot
ship is where a multi-tenant deployment puts the bytes. This is that: a
`MediaStore` over `BaseFileStorage`, so offloaded media lands wherever uploads
land - the local disk by default, an S3 bucket with server-side encryption when
the deployment configures one (#1423) - rather than in a second place with its
own backup story.

**Keyed per organization, and that is the whole of the isolation.** A media URI
is a content hash, so two tenants whose runs contain the same picture compute the
same URI - and a store that turned a URI straight into a path would let one read
the other's bytes by presenting a hash it guessed or saw. The organization is
part of the path and comes from the run, never from the URI, so a hash is only
ever resolved inside the tenant that wrote it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic_ai_harness.media import MediaContext, media_uri_for, parse_media_uri

from app.services.file_storage import BaseFileStorage, get_file_storage

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

ORGANIZATION_RESOURCE = "media.organization_id"
"""Key the factory puts the run's organization under, for the builder to read.

Not a configuration field: whose store a run writes to is decided by the run, and
a builder that could choose it could point one tenant's media at another's
prefix. `resources` is the channel for exactly this - a value the run resolved
that a capability needs and must never fetch itself.
"""

_EMPTY = MediaContext()


class OrganizationMediaStore:
    """Offloaded media for one organization, in the deployment's file storage.

    Implements the `MediaStore` protocol `externalize_media` and `restore_media`
    take. Content-addressed, so writing the same bytes twice writes one object
    and the second `put` is a no-op over an existing key.
    """

    def __init__(self, organization_id: UUID, storage: BaseFileStorage | None = None) -> None:
        self._organization_id = organization_id
        self._storage = storage if storage is not None else get_file_storage()

    def _path(self, digest: str) -> str:
        """Where one digest's bytes live, inside this organization's own prefix."""
        return f"media/{self._organization_id}/{digest}"

    async def put(self, data: bytes, *, context: MediaContext = _EMPTY) -> str:
        """Write the bytes and answer with their canonical URI.

        Deduplicated by construction: the path is the digest, so the same bytes
        offloaded from two conversations are one object. A re-write is skipped
        rather than performed - identical content, and a `put` that overwrote
        would pay for the transfer every turn a long history is replayed.
        """
        uri = media_uri_for(data)
        path = self._path(parse_media_uri(uri))
        if not await self._storage.exists(path):
            await self._storage.save_at(path, data)
        return uri

    async def get(self, uri: str, *, context: MediaContext = _EMPTY) -> bytes:
        return await self._storage.load(self._path(parse_media_uri(uri)))

    async def exists(self, uri: str, *, context: MediaContext = _EMPTY) -> bool:
        try:
            path = self._path(parse_media_uri(uri))
        except ValueError:
            return False
        return await self._storage.exists(path)

    async def public_url(self, uri: str, *, context: MediaContext = _EMPTY) -> str | None:
        """None, and deliberately.

        A public URL is what the harness's forthcoming externalizer would hand a
        *model* so it fetches the bytes itself. These bytes are a tenant's, they
        are behind this deployment's authentication, and a URL a model provider
        can fetch is a URL anybody can. Restoring from the store is the only way
        back in, which is why this store never offers one.
        """
        return None

    async def get_metadata(self, uri: str, *, context: MediaContext = _EMPTY) -> Mapping[str, str]:
        """Nothing is stored beside the bytes, so there is nothing to answer with."""
        return {}
