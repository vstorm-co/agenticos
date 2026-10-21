"""Where media an agent generated is kept, and how it is read back.

Images today; speech and video use the same store (#2259, #2260). The kind of
file is carried by its extension and nothing else - the serving route types it
from the suffix, through the same allowlist the workspace routes use.

Agent-generated media is **organization-scoped**, and that is the whole of its
tenancy: the bytes live under a per-organization directory in the same file
store chat uploads and RAG documents use, and a file is addressed by the caller's
own organization plus the file's leaf name. A caller therefore reaches only its
own organization's files - the directory a request reads is built from the
caller's `organization_id`, never from anything the client sends - so a leaked or
guessed leaf name from another tenant resolves to a path this organization does
not own and is a 404.

That is a wider scope than a chat upload, which is owned by one user
(`file_upload.py`). It is deliberate and it is the trade the prefix design makes:
there is no row recording which run or which person produced a file, so the
boundary that *can* be enforced without one is the tenant. Tightening it to a
person or a conversation is what a database-backed record would buy, and is the
shape [#55](https://github.com/vstorm-co/agenticos/issues/55) can grow into on
top of this - the directory convention and the serving route are the parts it
would inherit unchanged.

The underlying `LocalFileStorage.save`/`load` do their IO on the event loop
(#25); this module adds no new blocking of its own beyond awaiting that API, and
inherits the fix when it lands.
"""

from pathlib import PurePosixPath
from uuid import UUID

from app.core.exceptions import NotFoundError
from app.services.file_storage import get_file_storage

OWNER_PREFIX = "generated"
"""First path segment of every generated file, per organization.

`generated_<organization_id>` rather than `generated/<organization_id>` because
`LocalFileStorage.save` sanitises its owner argument into a single path component
- a slash would be collapsed to an underscore anyway, so the flat form is what is
actually written and is what the reader must reconstruct. It shares the store's
root with the per-user chat directories (`<user_id>/`), which cannot collide: a
user id is a bare UUID and this is always prefixed.
"""


def _owner(organization_id: UUID) -> str:
    """The storage owner segment for one organization's generated media."""
    return f"{OWNER_PREFIX}_{organization_id}"


async def save_generated_media(organization_id: UUID, data: bytes, *, filename: str) -> str:
    """Store one generated file and return the leaf name it is served under.

    The leaf is unique (the store stamps a UUID prefix), so it is all a caller
    needs to read the file back: :func:`load_generated_media` rebuilds the
    organization directory from the *reader's* own id, which is what keeps one
    tenant's leaf name meaningless to another.

    Args:
        organization_id: The organization the file belongs to.
        data: The file's bytes.
        filename: A name such as `image.png` or `speech.mp3`. Its extension is
            what the serving route types the file by, so it must be the real
            format of `data`.
    """
    storage = get_file_storage()
    storage_path = await storage.save(_owner(organization_id), filename, data)
    return PurePosixPath(storage_path).name


async def load_generated_media(organization_id: UUID, filename: str) -> bytes:
    """Read one generated file back, scoped to the caller's organization.

    Args:
        organization_id: The organization reading - the directory is built from
            this and never from the client, so a filename is only ever resolved
            within the caller's own tenant.
        filename: The leaf name returned by :func:`save_generated_media`.

    Raises:
        NotFoundError: If no such file exists for this organization.
    """
    if "/" in filename or "\\" in filename or filename in {"", ".", ".."}:
        # A single leaf name only. The serving route's path parameter already
        # cannot carry a separator, but a caller reaching this directly must not
        # be able to climb into another organization's directory with `../`,
        # which resolves inside the shared storage root rather than escaping it.
        raise NotFoundError(message="Generated file not found", details={"filename": filename})
    storage = get_file_storage()
    try:
        return await storage.load(f"{_owner(organization_id)}/{filename}")
    except (FileNotFoundError, ValueError) as exc:
        raise NotFoundError(
            message="Generated file not found",
            details={"filename": filename},
        ) from exc


def generated_media_url(filename: str) -> str:
    """The API path the interface fetches a stored generated file from."""
    return f"/api/v1/generated/{filename}"
