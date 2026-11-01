"""Logging utilities - the filter every handler carries: PII, and forged lines."""

import logging
import re
from typing import ClassVar, overload

#: Bytes that end a log line, or move a terminal reading one.
#:
#: A log entry is one line, and the reader of a text log splits on newlines - so
#: a value carrying one writes a second entry of the attacker's choosing, with
#: their own timestamp, level and message. `caller` in the rate limiter is the
#: clearest way in: it can be `id:<the address somebody submitted>`, stripped and
#: lower-cased and otherwise theirs, or an `X-Forwarded-For` header where a
#: deployment trusts one. Escaping is not sanitising the value away - the line
#: still says what arrived, as `\n`, which is the point: a forged entry is
#: unreadable *as* an entry, and the real one keeps its evidence.
_LINE_BREAKERS = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")

#: What `LogRecord.__dict__` holds before anything is added through `extra=`.
#:
#: Read once, from a throwaway record, rather than written out: the attribute set
#: is the standard library's and has grown between versions (`taskName` in 3.12),
#: and a list copied here would silently stop covering a new one.
_STANDARD_RECORD_KEYS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
}

#: What a secret path segment is written as, wherever an address is recorded.
SECRET_PATH_MARKER = "[REDACTED]"

#: The addresses whose next segment is itself the credential.
#:
#: Each opens something to whoever reads the line, with no account or with only
#: the account the address was sent to:
#:
#: - an artifact's signed view token (`/artifact-content/<token>`) opens the page
#:   for its lifetime, and a public link's key (`/public/artifacts/<key>`,
#:   `/artifact-embed/<key>`) until the link is rotated. `lib/` is the static
#:   library set under the content route and carries nothing secret;
#: - a conversation's share token (`/conversations/shared/<token>`) opens the
#:   conversation;
#: - a workflow form's token (`/public/workflow-forms/<token>`) reads and submits
#:   the form, starting a run as its publisher;
#: - a webhook test token (`/workflow-webhook-tests/<token>`, and the editor's
#:   `/workflows/<id>/webhook-test/<token>`, where the id before it is kept) takes
#:   the one call the test URL is open for;
#: - a channel link token (`/me/channel-link/<token>`) attaches a chat account to
#:   whoever confirms it. A UUID there is the id of an identity being unlinked,
#:   which no token can be (`secrets.token_urlsafe(32)`), so it is kept;
#: - an invitation token (`/invitations/<token>`, and `/invitations/<token>/accept`)
#:   joins the organization it is for, or revokes the invitation. The token is
#:   `secrets.token_urlsafe(32)`, 43 characters, so it can be neither a UUID - the
#:   invitation id an administrator revokes by, `/orgs/<id>/invitations/<id>` - nor
#:   one of the literal segments `stage`, `staged` (`/staged/accept`) and `link`,
#:   all of which are kept;
#: - a run's resume token (`/workflow-resume/<run_id>/<token>`, where the run id is
#:   kept) is the HMAC that wakes the run's Wait steps with whatever body is sent.
#:
#: Not here, on purpose: `/workflow-webhooks/<id>` and `/workflow-github/<id>` name
#: an exposure whose calls are signed, and `/embed/<key>/ws` carries an agent
#: widget's key, which is public by design - its query does not, and is
#: `_SECRET_QUERY`'s. A route template's `{placeholder}` is kept. Matched without
#: the `/api/v1` prefix so a full URL, a proxied path and a span attribute are all
#: caught.
_SEGMENT = r"[^/?#\s\"']+"
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_SECRET_PATH = re.compile(
    r"("
    r"/(?:artifact-content|artifact-embed|public/artifacts)/(?!lib/)"
    r"|/conversations/shared/"
    r"|/public/workflow-forms/"
    r"|/workflow-webhook-tests/"
    rf"|/workflows/{_SEGMENT}/webhook-test/"
    rf"|/me/channel-link/(?!{_UUID}(?!{_SEGMENT}))"
    rf"|/invitations/(?!(?:{_UUID}|stage|staged|link)(?!{_SEGMENT}))"
    rf"|/workflow-resume/{_SEGMENT}/"
    rf")(?!\{{){_SEGMENT}"
)

#: The query parameters whose value is itself a credential, on whatever address.
#:
#: A query string is in the same request line and the same span attributes as the
#: path, so it leaks the same way:
#:
#: - `visitor` and `token` on the agent widget's socket (`/embed/<key>/ws`): a
#:   hosted page's continuity key, which resumes the conversation it names, and
#:   the customer's signed visitor token, which a browser cannot send as a header
#:   on a WebSocket handshake;
#: - `code` and `state` on a sign-in provider's return (`/oauth/<provider>/callback`):
#:   the authorization code the callback trades for the provider's tokens, and the
#:   value the session's CSRF check is keyed on. The console's own `/auth/callback`
#:   gets the single-use code that is traded for this deployment's tokens, and the
#:   MCP OAuth return its provider's `code` and `state`, under the same names;
#: - `invitation_handle` on `/oauth/<provider>/login` and `/auth/kerberos/login`:
#:   the one-time handle that stands in for an invitation token and redeems it;
#: - `token` on the console's `/reset-password`, `/auth/magic-link` and
#:   `/auth/email-change`, the links an email carries - the API never sees those
#:   addresses, but a proxy's log does, and `token` is already on the list.
#:
#: Not here, on purpose: a desktop sign-in's `desktop_nonce`, which lets the shell
#: refuse a deep link it did not ask for and admits nothing, `organization_id` on a
#: socket, which membership is checked against, and every ordinary parameter -
#: `q`, `skip`, `limit`, ids, `version_id`. Matched after `?` or `&`, or at the
#: very start, which is how a span's `url.query` begins. The value stops at the
#: next `&` or `#`; a `%s` placeholder in a log message's format string is left
#: for its argument to fill, so the line still formats. `%d` counts as a
#: placeholder only when no hex digit follows it - `%d3` is a percent-encoded byte
#: of a value, and a value that starts with one is still a credential.
SECRET_QUERY_PARAMS = frozenset({"code", "invitation_handle", "state", "token", "visitor"})
_SECRET_QUERY = re.compile(
    rf"((?:^|[?&])(?:{'|'.join(sorted(SECRET_QUERY_PARAMS))})=)"
    r"(?!%(?:[sr(]|d(?![0-9a-fA-F])))[^&#\s\"']+"
)


def redact_secret_paths(value: str) -> str:
    """Replace every credential in an address in `value` with the marker.

    That is the credential segment of a secret-bearing path (`_SECRET_PATH`) and
    the value of a credential query parameter (`_SECRET_QUERY`). One helper for
    every place an address is recorded - the log filter below and the Logfire
    request spans (`app/core/logfire_setup.py`) - so the two cannot disagree about
    which part is the secret.
    """
    value = _SECRET_PATH.sub(rf"\1{SECRET_PATH_MARKER}", value)
    return _SECRET_QUERY.sub(rf"\1{SECRET_PATH_MARKER}", value)


class PiiRedactionFilter(logging.Filter):
    """Logging filter that redacts PII and neutralises forged log lines.

    Automatically scrubs email addresses, JWT tokens, API keys, bearer tokens,
    password-like values and the credential segment of a secret-bearing address
    (`redact_secret_paths`) from log messages to prevent PII leaks to
    log aggregators (Datadog, CloudWatch, Logfire, etc.).

    It also escapes the control characters that let a value **end the line it is
    written on** and start another (`py/log-injection`). That is the second half
    of the same bargain and lives here for the same reason the first does: this
    filter is already on every handler in every process, so a call site cannot
    forget it, and the alternative - sanitising at each of the dozen places a
    request value reaches a log - is the copy that ends up weaker.

    Values passed through `extra=` are escaped too. The default formatter does
    not render them, so they cannot forge a line today; a deployment that plugs
    in one that does - a JSON or key-value formatter, which is the ordinary
    production choice - must not acquire the hole by changing its formatter.

    Usage:
        logging.getLogger().addFilter(PiiRedactionFilter())
    """

    PATTERNS: ClassVar[list[tuple[re.Pattern[str], str]]] = [
        # First, so a secret-bearing address reads the same whatever its token looks like.
        (_SECRET_PATH, rf"\1{SECRET_PATH_MARKER}"),
        (_SECRET_QUERY, rf"\1{SECRET_PATH_MARKER}"),
        (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[EMAIL_REDACTED]"),
        # JWT tokens (header.payload.signature)
        (
            re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"),
            "[JWT_REDACTED]",
        ),
        (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "[API_KEY_REDACTED]"),
        (re.compile(r"sk-ant-[a-zA-Z0-9_-]{20,}"), "[API_KEY_REDACTED]"),
        # Generic long hex/base64 secrets (40+ chars, likely tokens)
        (
            re.compile(
                r"(?:token|key|secret|password|authorization)[=: ]+['\"]?([A-Za-z0-9_/+=.-]{40,})",
                re.IGNORECASE,
            ),
            "[SECRET_REDACTED]",
        ),
        (re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{10,}"), "Bearer [TOKEN_REDACTED]"),
        # A Discord interaction's token is the last segment of the URL that
        # answers it, and a failed call's error carries that URL. Whoever holds
        # the token may post and edit as the bot there for fifteen minutes.
        (
            re.compile(r"(/(?:interactions|webhooks)/\d+/)[A-Za-z0-9_.-]{20,}"),
            r"\1[TOKEN_REDACTED]",
        ),
        # Password/secret in key=value or key: value patterns
        (
            re.compile(
                r"(password|passwd|pwd|secret_key|api_key|apikey|auth_token|access_token|refresh_token)"
                r"[\s]*[=:]\s*['\"]?\S+['\"]?",
                re.IGNORECASE,
            ),
            r"\1=[REDACTED]",
        ),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact PII from a record's message, its args, and its rendered traceback."""
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._redact_arg(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._redact_arg(a) for a in record.args)
        # The traceback is the leak this filter exists for: `logger.exception` on a
        # provider SDK error carries the failing request - URL, bearer token and
        # all - and the formatter appends it from `exc_info` *after* the filter has
        # run, so scrubbing only `msg`/`args` lets it through. Render it here and
        # store the redacted text, which the formatter then reuses instead of
        # re-rendering the original (#440).
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self._redact(record.exc_text)
        if record.stack_info:
            record.stack_info = self._redact(record.stack_info)
        # Anything a call site added through `extra=`, which arrives as an
        # attribute on the record rather than in `msg` or `args`.
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_KEYS and isinstance(value, str):
                record.__dict__[key] = self._redact(value)
        return True

    def _redact(self, value: str) -> str:
        for pattern, replacement in self.PATTERNS:
            value = pattern.sub(replacement, value)
        return _escape_line_breakers(value)

    def _redact_arg(self, value: object) -> object:
        """A format argument, redacted the way it will be rendered.

        A string is redacted directly. Anything else that isn't a plain number or
        flag - an `httpx.URL`, a Starlette `URL`, an exception - is rendered by `%s`
        through `str()`, so that text is what is checked; the object is replaced by
        its redacted text only when redacting changed it, so a `%d` or `%r` of an
        ordinary argument still formats as it did.
        """
        if isinstance(value, str):
            return self._redact(value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        rendered = str(value)
        redacted = self._redact(rendered)
        return value if redacted == rendered else redacted


@overload
def one_line(value: str) -> str: ...
@overload
def one_line(value: None) -> None: ...
def one_line(value: str | None) -> str | None:
    """A request value written out on one line, at the call that logs it.

    `PiiRedactionFilter` already escapes every record, so this adds no protection
    a handler lacks. It exists for CodeQL's `py/log-injection`, which cannot see a
    filter installed at startup and recognises only a sanitiser at the call site.
    """
    return None if value is None else value.replace("\r", "\\r").replace("\n", "\\n")


def _escape_line_breakers(value: str) -> str:
    """Write a control character out rather than letting it end the line.

    Newline and carriage return become `\\n` and `\\r`; everything else in the
    C0 range and `DEL` becomes its `\\xNN` escape. Tab is left alone: it breaks
    no line and is ordinary in a message somebody wrote.
    """
    return _LINE_BREAKERS.sub(
        lambda match: {"\n": "\\n", "\r": "\\r"}.get(match.group(), f"\\x{ord(match.group()):02x}"),
        value,
    )


def setup_logging() -> None:
    """Redact PII from everything this application logs, in every process.

    The filter goes on the root logger's **handlers**, not on the root logger.
    A filter on a logger runs only for a record logged on *that* logger
    (`Logger.handle`); a record from a module logger - which is every log line in
    this codebase - reaches the ancestors' *handlers* through
    `Logger.callHandlers` and never touches their filters. Attached to the logger,
    as it was, the filter scrubbed nothing the application actually logs (#440).

    `logging.lastResort` is covered too, because a process that has configured no
    root handler at all - the CLI before anything sets logging up - emits
    `WARNING`+ records through it, and a credential in a `logger.exception` is
    exactly such a record.

    The worker and each of its ingest children call this on start, since none of
    them runs the API's startup; being idempotent is what makes calling it from
    every entrypoint safe.

    **uvicorn's own loggers are covered as well.** Its `LOGGING_CONFIG` gives
    `uvicorn.access` and `uvicorn.error` handlers of their own and stops them
    propagating, so no record of theirs reaches the root's handlers - and the
    access log writes every request line, query string included, which is where a
    signed link's `?token=` sits. The filter goes on those loggers *and* on their
    handlers: on the logger, because both log their records on themselves, so it
    holds whatever handler is configured after this runs; on the handlers, for a
    record a child logger propagates to them.

    Idempotent: safe to call from each entrypoint, and a second call covers a
    handler added since the first.
    """
    root = logging.getLogger()
    handlers: list[logging.Handler] = list(root.handlers)
    # A snapshot: `getLogger` in another thread adds to this dict, and iterating it
    # live would raise. `list()` copies it in one call; the lock that guards it is
    # private to `logging`.
    for logger in list(logging.Logger.manager.loggerDict.values()):
        if isinstance(logger, logging.Logger):
            handlers.extend(logger.handlers)
    if logging.lastResort is not None:
        handlers.append(logging.lastResort)
    for name in _SERVER_LOGGERS:
        server_logger = logging.getLogger(name)
        _add_redaction(server_logger)
        handlers.extend(server_logger.handlers)
    for handler in handlers:
        _add_redaction(handler)


_SERVER_LOGGERS = ("uvicorn.access", "uvicorn.error")
"""The loggers the ASGI server writes through, each with handlers of its own."""


def _add_redaction(filterer: logging.Filterer) -> None:
    """Put one redaction filter on a logger or a handler, unless it has one."""
    if not any(isinstance(f, PiiRedactionFilter) for f in filterer.filters):
        filterer.addFilter(PiiRedactionFilter())
