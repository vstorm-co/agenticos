# http.request

Calls an HTTP API. It sends `GET`, `POST`, `PUT`, `PATCH` or `DELETE` to `url`
(which may be bound from an earlier step), with the bound `body` as JSON, and
returns the status, the headers and the body. A JSON response is parsed, and
anything else comes back as text.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `body` (and, optionally, `url`) is bound |
| `out` | output | `HttpRequestOutput` | `status_code`, `headers`, `body`; with paging, `items`, `pages`, `complete` |

## What it will not reach

Every request and every redirect followed goes through the deployment's SSRF
check and is sent to the address that check approved. A private, loopback,
link-local or cloud-metadata address is refused with `URL_REFUSED` before
anything is sent, and so is a name that resolves to one. Only a `GET` follows
redirects, at most five. Other methods return the `3xx` as their answer.

## Credentials

A credential is an **HTTP credential** from the vault: a token sealed together
with the origins it may be sent to, such as `https://api.example.com`. The
config names the secret, never a value. `auth.kind` decides how the token is
sent: `bearer`, `basic` (with the secret's username), `header` (in
`auth.header_name`) or `query` (in the URL parameter `auth.query_name`, added
only on a URL the secret allows).

The origin is checked on the URL the step is about to call, after binding, so
a URL taken from a run's input cannot aim the credential elsewhere. A URL
outside the secret's origins fails with `SECRET_ORIGIN_DENIED` and nothing is
sent. A redirect to an origin the secret does not allow is followed without the
credential. Publishing refuses a secret that is not an HTTP credential or that
the graph's author cannot use, and each run checks it again.

Nothing sent comes back out: `Set-Cookie` and the authentication headers are
dropped from the output, and the token is replaced with `[redacted]` wherever
the response echoes it.

## Paging

A `GET` with `pagination` fetches page after page: `next_url` follows the URL
`next_path` finds in each body, `cursor` sends back what `next_path` finds in
the `param` query parameter, and `page` counts `param` up from `first_page`.
What `items_path` finds on each page is collected into `items`; a page with none
ends it, and so does `max_pages` (at most 100), which leaves `complete` false.
Each page is dialled like the first - the SSRF check, redirects, the credential
only where its secret allows - and all of them together read at most
`max_response_bytes`. `items_path` finding something that is not a list fails
with `PAGE_ITEMS_NOT_A_LIST`.

## Limits

`timeout_seconds` (at most 60) and `max_response_bytes` (at most 10 MB). The
body is read as it streams, and a response larger than the limit fails with
`RESPONSE_TOO_LARGE`. It is never truncated quietly.

## Errors and retries

| What happened | Result |
|---|---|
| The connection never opened | `HTTP_UNREACHABLE`, retryable: nothing was sent |
| Sent, no response, `GET` or idempotency header set | `HTTP_NO_RESPONSE`, retryable |
| Sent, no response, any other write | **uncertain**: the run stops for a person, because the far side may have acted |
| Non-2xx status | `HTTP_ERROR_STATUS` with `status_code`, or the response as output with `on_error_status: complete` |

As a node kind, `http.request` is `at_least_once`. A `GET`, or a write with
`idempotency_key_header` set, is recorded as `idempotent` for that call. The
header carries the step's operation key, which stays the same across retries
of the same step and differs in each loop iteration, so a far side that honours
it acts once.
