# http.download

Fetches a file over HTTP into the run. It sends a `GET` to `url` (which may be
bound from an earlier step), follows up to five redirects, and stores the body as
a file of this run, returned as a `FileRef` with the type its bytes turned out to
be.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `url` may be bound |
| `out` | output | `HttpDownloadOutput` | `file`, `content_type`, `filename`, `status_code` |

## What it refuses

Every hop goes through the deployment's SSRF check, as `http.request` does. The
body is counted as it arrives and refused with `RESPONSE_TOO_LARGE` past
`max_bytes`, whatever `Content-Length` said, and nothing partial is stored. The
type is sniffed from the bytes: with `expected_content_types` set, a file whose
bytes are something else fails with `CONTENT_TYPE_MISMATCH`, so a server calling
HTML an image cannot make it one.

## Retries

A `GET` repeats safely, but every attempt stores a new file, so the step is
`at_least_once`. A retry after a lost answer leaves a second copy.
