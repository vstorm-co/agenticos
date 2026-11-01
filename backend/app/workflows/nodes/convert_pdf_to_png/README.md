# convert.pdf_to_png

Renders chosen `pages` of a PDF, counting from 1, as PNG images at `dpi`, and
returns each page's file and size - a page to hand an agent to look at.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | `ConvertFileInput` | `file` |
| `out` | output | `ConvertPdfToPngOutput` | `images`: `page`, `file`, `width`, `height` |

## What it refuses

Each page's size is read before it is drawn, and a page whose picture would pass
`CHAT_IMAGE_MAX_PIXELS` fails with `IMAGE_TOO_LARGE` before anything is
allocated. A page the document does not have is `PAGE_OUT_OF_RANGE`, a file that
is not a PDF `UNSUPPORTED_FORMAT`. It stores new files on every call, so it is
`at_least_once`.
