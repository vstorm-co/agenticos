"""Template loader - reads pre-rendered HTML/text from `emails/compiled/`.

`EmailTemplateError` is an `AppException`, so everything it carries reaches a
caller as a 500 body. Where the templates were looked for is an operator's
question and is answered in the log; the refusal names the template, which is
the only part of this a reader can act on (agenticos#342).
"""

import logging
from pathlib import Path
from typing import Any

from app.services.email.exceptions import EmailTemplateError

logger = logging.getLogger(__name__)

# Where the compiled templates sit, relative to whichever ancestor holds them.
_COMPILED_RELATIVE = Path("emails") / "compiled"

# The starting point for the upward search. Module-level so a test can point the
# search somewhere else without reaching into the search itself.
_SEARCH_ORIGIN = Path(__file__).resolve()


def _compiled_dir() -> Path:
    """Locate `emails/compiled/`, which lives outside the Python package.

    Two layouts have to work, and a fixed number of `.parent` hops cannot
    satisfy both. Locally the directory is a sibling of `backend/` at the
    repository root, so it is four levels above this file. In the container it
    is `/app/emails` - a bind mount beside the `app` package, three levels up -
    because the image is built with `./backend` as its context and therefore
    cannot contain it.

    The previous fixed path resolved to `backend/emails/compiled`, which is
    neither: every email in local development failed with a template-not-found
    error that the callers log and swallow, while the same code worked under
    Docker. Walking up until the directory appears satisfies both layouts and
    stops guessing at the depth.
    """
    for parent in _SEARCH_ORIGIN.parents:
        candidate = parent / _COMPILED_RELATIVE
        if candidate.is_dir():
            return candidate
    logger.error(
        "Compiled email templates not found",
        extra={"searched_for": str(_COMPILED_RELATIVE), "searched_from": str(_SEARCH_ORIGIN)},
    )
    raise EmailTemplateError(
        message=f"Compiled email template directory '{_COMPILED_RELATIVE}' not found",
        details={"directory": str(_COMPILED_RELATIVE)},
    )


def _load_raw(key: str, ext: str) -> str:
    path = _compiled_dir() / f"{key}.{ext}"
    if not path.exists():
        logger.error("Email template not found", extra={"template": key, "path": str(path)})
        raise EmailTemplateError(
            message=f"Email template '{key}.{ext}' not found",
            details={"template": key, "format": ext},
        )
    return path.read_text(encoding="utf-8")


def _render(template: str, context: dict[str, Any]) -> str:
    """Replace [[variable]] placeholders with context values."""
    for k, v in context.items():
        template = template.replace(f"[[{k}]]", str(v) if v is not None else "")
    return template


def render_email(key: str, context: dict[str, Any]) -> tuple[str, str, str]:
    """Return (subject, html, text) for the given template key and context."""
    html_raw = _load_raw(key, "html")
    text_raw = _load_raw(key, "txt")

    # Subject is stored in the first line of .txt as "Subject: ..."
    lines = text_raw.splitlines()
    subject_line = lines[0] if lines else ""
    subject_raw = (
        subject_line.removeprefix("Subject:").strip()
        if subject_line.startswith("Subject:")
        else key
    )
    text_body = "\n".join(lines[1:]).strip()

    subject = _render(subject_raw, context)
    html = _render(html_raw, context)
    text = _render(text_body, context)
    return subject, html, text
