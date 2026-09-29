"""`image.transform`: crop, resize, rotate or re-encode a PNG, JPEG, WebP or GIF image.

Bounded before it allocates. Opening an image reads only its header, so the
source's width times height is checked against `CHAT_IMAGE_MAX_PIXELS` before
a pixel is decoded - a small file declaring an enormous canvas fails with
`IMAGE_TOO_LARGE` - and so are the crop box and the requested size, since
each allocates a canvas of its own. A crop must lie inside the image.

The result carries none of the source's metadata: its orientation is applied
to the pixels, then EXIF and the colour profile are dropped, so a photo's
location does not travel with it. Operations run in a fixed order - crop,
then resize, then rotate - whatever order the config lists them in.
"""

from __future__ import annotations

import asyncio
import io
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed, NodeResult

_INPUT_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
_FORMAT = {
    "png": ("PNG", "image/png"),
    "jpeg": ("JPEG", "image/jpeg"),
    "webp": ("WEBP", "image/webp"),
}
_ROTATE = {
    90: Image.Transpose.ROTATE_270,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}
MAX_SIDE = 10_000


class ImageResize(BaseModel):
    """`fit` keeps the proportions inside the box, `fill` covers it and trims the
    overflow, `exact` stretches to it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    width: int = Field(ge=1, le=MAX_SIDE)
    height: int = Field(ge=1, le=MAX_SIDE)
    mode: Literal["fit", "fill", "exact"] = "fit"


class ImageCrop(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    left: int = Field(ge=0)
    top: int = Field(ge=0)
    width: int = Field(ge=1, le=MAX_SIDE)
    height: int = Field(ge=1, le=MAX_SIDE)


class ImageTransformConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    crop: ImageCrop | None = None
    resize: ImageResize | None = None
    rotate_degrees: Literal[0, 90, 180, 270] = Field(default=0, description="Clockwise")
    output_format: Literal["png", "jpeg", "webp"] = "png"
    quality: int = Field(default=85, ge=1, le=100, description="For JPEG and WebP")
    max_bytes: int = Field(default=25_000_000, ge=1, le=50_000_000)


class ImageTransformInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file: FileRef


class ImageTransformOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file: FileRef
    content_type: str
    width: int
    height: int


class _Refused(Exception):
    def __init__(self, result: Failed) -> None:
        self.result = result


def _too_large(what: str, pixels: int) -> _Refused:
    return _Refused(
        files.failed(
            "IMAGE_TOO_LARGE",
            f"The {what} would be {pixels} pixels, over the limit of "
            f"{settings.CHAT_IMAGE_MAX_PIXELS}",
            decoded_pixels=pixels,
            limit=settings.CHAT_IMAGE_MAX_PIXELS,
        )
    )


def _transform(data: bytes, config: ImageTransformConfig) -> tuple[bytes, int, int]:
    limit = settings.CHAT_IMAGE_MAX_PIXELS
    try:
        image = Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as exc:
        # Pillow's own ceiling, past which it will not even report the size.
        raise _Refused(
            files.failed(
                "IMAGE_TOO_LARGE",
                "This image is far larger than the image limit allows",
                limit=settings.CHAT_IMAGE_MAX_PIXELS,
            )
        ) from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise _Refused(files.failed("IMAGE_CORRUPT", "This image could not be opened")) from exc
    width, height = image.size
    if width * height > limit:
        raise _too_large("image", width * height)
    # The source is bounded, so decoding it to apply its orientation is too - and
    # the crop is measured on the picture as it is meant to be seen.
    try:
        image = ImageOps.exif_transpose(image)
    except (OSError, Image.DecompressionBombError) as exc:
        raise _Refused(files.failed("IMAGE_CORRUPT", "This image could not be decoded")) from exc
    width, height = image.size
    crop = config.crop
    if crop is not None and (crop.left + crop.width > width or crop.top + crop.height > height):
        raise _Refused(
            files.failed(
                "CROP_OUT_OF_BOUNDS",
                f"The crop reaches outside this {width}x{height} image",
                width=width,
                height=height,
            )
        )
    if config.resize is not None and config.resize.width * config.resize.height > limit:
        raise _too_large("resized image", config.resize.width * config.resize.height)
    if crop is not None:
        image = image.crop((crop.left, crop.top, crop.left + crop.width, crop.top + crop.height))
    if config.resize is not None:
        box = (config.resize.width, config.resize.height)
        if config.resize.mode == "fit":
            image = ImageOps.contain(image, box)
        elif config.resize.mode == "fill":
            image = ImageOps.fit(image, box)
        else:
            image = image.resize(box)
    if config.rotate_degrees:
        image = image.transpose(_ROTATE[config.rotate_degrees])
    pillow_format, _media_type = _FORMAT[config.output_format]
    if pillow_format == "JPEG" and image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    # Nothing of the source's metadata is written: the colour profile rides in
    # `info`, which a save would otherwise carry over.
    image.info = {}
    out = io.BytesIO()
    image.save(out, format=pillow_format, quality=config.quality)
    return out.getvalue(), image.width, image.height


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, ImageTransformConfig) or not isinstance(
        node_input, ImageTransformInput
    ):
        return files.failed("FILE_STEP_NOT_CONFIGURED", "This step has no image to transform")
    stored = await files.load(node_input.file, max_bytes=config.max_bytes)
    if isinstance(stored, Failed):
        return stored
    if stored.content_type not in _INPUT_TYPES:
        return files.failed(
            "UNSUPPORTED_FORMAT",
            f"Only PNG, JPEG, WebP and GIF images transform, not {stored.content_type}",
            content_type=stored.content_type,
        )
    try:
        data, width, height = await asyncio.to_thread(_transform, stored.data, config)
    except _Refused as refused:
        return refused.result
    _format, media_type = _FORMAT[config.output_format]
    stem = (stored.filename or "image").rsplit(".", 1)[0]
    image = await files.save(
        data, content_type=media_type, filename=f"{stem}.{config.output_format}"
    )
    return Completed[ImageTransformOutput](
        output=ImageTransformOutput(file=image, content_type=media_type, width=width, height=height)
    )
