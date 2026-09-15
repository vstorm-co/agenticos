"""How a stored file reaches a browser, whichever backend is holding it.

Seven routes serve one file out of `BaseFileStorage`: two avatars, an agent's,
a hosted page's logo, the deployment's mark, a chat attachment and a
knowledge-base document. Each of them used to resolve the file to a path on this
host and hand that path to `FileResponse`, which is correct for the local
backend and answers 404 for every file in an object store - the S3 backend has
no path to give (#1423).

So the decision moves here. A backend with a local path still gets
`FileResponse`, which streams from disk without the bytes passing through this
process; one without it is read into memory and sent as a body. Nothing above
this module knows which.

Both builders answer `None` rather than raising, because the wording of the
refusal belongs to the route: "No avatar set" and "No logo" are different
sentences about the same missing object.
"""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import Response
from fastapi.responses import FileResponse

from app.api.responses import content_disposition
from app.services.file_storage import (
    IMAGE_MIME_TYPES,
    get_file_storage,
    sniff_image_header,
    sniff_image_media_type,
)


async def stored_file_response(
    storage_path: str,
    *,
    media_type: str,
    headers: Mapping[str, str],
    attachment_name: str | None = None,
) -> Response | None:
    """One stored file as a response, or `None` when the backend no longer has it.

    Args:
        storage_path: The path a row recorded, as the storage backend wrote it.
        media_type: The type to serve it as. Decided by the caller, never
            guessed from the stored name by Starlette - a file keeps whatever
            suffix its uploader chose, and the caller knows what it is allowed
            to be.
        headers: Sent as they are given.
        attachment_name: The name a download is offered under. Present, the
            response is a download - which is what `FileResponse(filename=...)`
            did for the routes that passed one, and it is spelled out here
            because a body response has no such default.
    """
    header_map = dict(headers)
    if attachment_name is not None:
        header_map["Content-Disposition"] = content_disposition("attachment", attachment_name)
    storage = get_file_storage()
    path = storage.get_full_path(storage_path)
    if path is not None:
        return FileResponse(path=path, media_type=media_type, headers=header_map)
    data = await _load(storage_path)
    if data is None:
        return None
    return Response(content=data, media_type=media_type, headers=header_map)


async def stored_image_response(
    storage_path: str, *, headers: Mapping[str, str]
) -> Response | None:
    """One stored image, typed from its own bytes, or `None`.

    `None` covers both "the backend does not have it" and "its bytes are not one
    of the four image types this platform accepts", and the routes answer 404 for
    either: an avatar stored as HTML must never be served from the app's own
    origin, and saying which of the two happened tells a caller what is in
    somebody else's account (#702, #1035).
    """
    storage = get_file_storage()
    path = storage.get_full_path(storage_path)
    if path is not None:
        media_type = sniff_image_media_type(str(path))
        if media_type is None:
            return None
        return FileResponse(path=path, media_type=media_type, headers=dict(headers))
    data = await _load(storage_path)
    if data is None:
        return None
    media_type = sniff_image_header(data[:16])
    if media_type not in IMAGE_MIME_TYPES:
        return None
    return Response(content=data, media_type=media_type, headers=dict(headers))


async def _load(storage_path: str) -> bytes | None:
    """The bytes behind a storage path, or `None` for a path the backend cannot serve.

    `ValueError` is a path that escapes the storage root, which the local
    backend raises and the S3 backend copies: a caller that reaches here with one
    gets the same answer as for a file that is not there, rather than a 500
    naming the root.
    """
    try:
        return await get_file_storage().load(storage_path)
    except (FileNotFoundError, ValueError):
        return None
