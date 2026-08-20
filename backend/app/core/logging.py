"""Logging utilities - PII redaction filter for GDPR/compliance safety."""

import logging
import re
from typing import ClassVar


class PiiRedactionFilter(logging.Filter):
    """Logging filter that redacts personally identifiable information.

    Automatically scrubs email addresses, JWT tokens, API keys, bearer tokens,
    and password-like values from log messages to prevent PII leaks to
    log aggregators (Datadog, CloudWatch, Logfire, etc.).

    Usage:
        logging.getLogger().addFilter(PiiRedactionFilter())
    """

    PATTERNS: ClassVar[list[tuple[re.Pattern[str], str]]] = [
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
                record.args = {
                    k: self._redact(v) if isinstance(v, str) else v for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self._redact(a) if isinstance(a, str) else a for a in record.args
                )
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
        return True

    def _redact(self, value: str) -> str:
        for pattern, replacement in self.PATTERNS:
            value = pattern.sub(replacement, value)
        return value


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

    A Prefect flow runs in a subprocess that imports the flow module but never ran
    this, and Prefect installs its own handlers there - so `lastResort` does not
    fire and the filter would be absent. The flows call this themselves for that
    reason; being idempotent is what makes that safe.

    Idempotent: safe to call from each entrypoint, and a second call covers a
    handler added since the first.
    """
    root = logging.getLogger()
    handlers: list[logging.Handler] = list(root.handlers)
    if logging.lastResort is not None:
        handlers.append(logging.lastResort)
    for handler in handlers:
        if not any(isinstance(f, PiiRedactionFilter) for f in handler.filters):
            handler.addFilter(PiiRedactionFilter())
