"""Bounded, data-free preview images; callers must authorize the version first."""

import base64
import time
from collections import OrderedDict
from uuid import UUID

from app.core.exceptions import ConfigurationError, ExternalServiceError
from app.schemas.artifact import ArtifactThumbnailRead
from app.services import artifact_render

_MAX_BYTES = 16 * 1024 * 1024
_MAX_ENTRIES = 32
_TTL_SECONDS = 30 * 60
_IMAGES: OrderedDict[UUID, tuple[float, bytes]] = OrderedDict()


async def render_thumbnail(
    version_id: UUID, request: artifact_render.RenderRequest
) -> ArtifactThumbnailRead:
    """Reuse an immutable version's preview, without running its JavaScript again.

    No record bindings or workflow actions may enter this cache. A fresh access
    decision belongs to the calling ArtifactService, even for a cached image.
    """
    if request.bindings or request.output != "image":
        raise ValueError("Thumbnail renders must contain no live data and request an image")
    now = time.monotonic()
    for key, (created, _) in list(_IMAGES.items()):
        if now - created >= _TTL_SECONDS:
            del _IMAGES[key]
    found = _IMAGES.get(version_id)
    if found is not None:
        _IMAGES.move_to_end(version_id)
        image = found[1]
    else:
        try:
            drawn = await artifact_render.render(request)
        except ConfigurationError:
            return ArtifactThumbnailRead(version_id=version_id, state="unavailable", image=None)
        except ExternalServiceError:
            return ArtifactThumbnailRead(version_id=version_id, state="unavailable", image=None)
        if drawn.image is None:
            return ArtifactThumbnailRead(version_id=version_id, state="unavailable", image=None)
        image = drawn.image
        if len(image) <= _MAX_BYTES:
            _IMAGES[version_id] = (now, image)
            while (
                len(_IMAGES) > _MAX_ENTRIES
                or sum(len(value[1]) for value in _IMAGES.values()) > _MAX_BYTES
            ):
                _IMAGES.popitem(last=False)
    return ArtifactThumbnailRead(
        version_id=version_id,
        state="ready",
        image="data:image/jpeg;base64," + base64.b64encode(image).decode("ascii"),
    )
