# image.transform

Crops, resizes, rotates or re-encodes a PNG, JPEG, WebP or GIF image, and stores
the result as PNG, JPEG or WebP. The operations run in a fixed order - crop, then
resize, then rotate - whatever order the config lists them in.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | `ImageTransformInput` | `file` |
| `out` | output | `ImageTransformOutput` | `file`, `content_type`, `width`, `height` |

## Bounded before it decodes

Opening an image reads only its header. The source's width times height is
checked against `CHAT_IMAGE_MAX_PIXELS` before a pixel is decoded, and so are the
crop box and the requested size, which each allocate a canvas of their own - a
small file declaring an enormous canvas fails with `IMAGE_TOO_LARGE`. A crop
outside the picture is `CROP_OUT_OF_BOUNDS`.

## Metadata

The source's orientation is applied to the pixels, then its EXIF data and colour
profile are dropped, so a photo's location does not travel with it. Every call
stores a new file, so the step is `at_least_once`.
