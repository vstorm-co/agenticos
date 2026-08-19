"""Serving the two images this deployment brands itself with.

Beside the endpoints rather than in them: a route module holds routers, and
`scripts/check_routes.py` is what says so. This is route-adjacent - it decides a
response's headers and its media type - so it is a `_`-prefixed neighbour rather
than a method on the service, which has no business knowing about `FileResponse`.
"""

import logging
import mimetypes

from fastapi import HTTPException
from fastapi.responses import FileResponse

from app.services.deployment_settings import DeploymentSettingsService, ImageKind
from app.services.file_storage import IMAGE_MIME_TYPES, get_file_storage

logger = logging.getLogger(__name__)


async def serve_branding_image(service: DeploymentSettingsService, kind: ImageKind) -> FileResponse:
    """Hand out one stored image, deciding its type here rather than on disk.

    A stored file keeps whatever extension the upload minted, and this is served
    from the origin the app's own pages run on - so `FileResponse` alone would let
    Starlette guess a type from the suffix, and a file that is not a picture would
    go out as whatever it looks like. Refused rather than corrected: this route
    hands out one image, and anything that is not one is not this deployment's
    mark. The reasoning is `embed.hosted_logo`'s, and so is `nosniff`.

    404 for "no image", which is the ordinary state of a deployment using the
    built-in mark, and what the frontend reads as "draw your own".
    """
    stored = await service.image_path(kind)
    if stored is None:
        raise HTTPException(status_code=404, detail="No image")
    path = get_file_storage().get_full_path(stored)
    if path is None:
        logger.warning("branding_image_missing", extra={"kind": kind, "stored_path": stored})
        raise HTTPException(status_code=404, detail="No image")
    media_type = mimetypes.guess_type(str(path))[0]
    if media_type not in IMAGE_MIME_TYPES:
        logger.warning(
            "branding_image_not_an_image", extra={"kind": kind, "media_type": media_type}
        )
        raise HTTPException(status_code=404, detail="No image")
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            # A year, because the address carries the row's write time: replacing
            # the image changes the `?v=` the branding response hands out, so a
            # long-lived copy is only ever reused for bytes that have not changed.
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )
