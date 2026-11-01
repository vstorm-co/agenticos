# http.upload

Sends one of the run's files to an HTTP endpoint with `POST` or `PUT`, streamed
from storage into the request body and never held whole, with the type its row
recorded. It returns the status, the safe headers and the body, like
`http.request`.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | `HttpUploadInput` | `file`, bound from an earlier step |
| `out` | output | `HttpResponseOutput` | `status_code`, `headers`, `body` |

## What it will not do

It never follows a redirect: an upload is a write, and a far side that moved
answers with its `3xx`, which fails the step rather than sending the file
somewhere it was not pointed at. The file must be one this run made or was
started with; any other `FileRef` is `FILE_NOT_FOUND`.

## Retries

A request that went out with no answer is `Uncertain` unless
`idempotency_key_header` sends the step's stable key, which lets the far side
recognise the retry - then it is `idempotent`.
