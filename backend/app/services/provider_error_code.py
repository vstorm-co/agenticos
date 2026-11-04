"""What of a media provider's error is safe to log: its code, and nothing else.

A provider's error body may echo the words or the prompt sent, or a key in a
format the log redaction does not know (found reviewing #2264). Speech and video
clients log the code each provider names, and only a value shaped like a code.
"""

import json
import re

_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")

_CODE_PLACES = (("error", "code"), ("error", "status"), ("error", "type"), ("detail", "status"))
"""Where providers put it: OpenAI and BytePlus `error.code`, OpenAI `error.type`,
Gemini `error.status`, ElevenLabs `detail.status` - and xAI and Alibaba a
top-level `code`, read first."""


def safe_code(value: object) -> str | None:
    """`value` where it is shaped like an error code, or None."""
    return value if isinstance(value, str) and _CODE.fullmatch(value) else None


def error_code(body: str) -> str | None:
    """The provider's own error code from its JSON error body, or None."""
    try:
        payload = json.loads(body)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    if (top := safe_code(payload.get("code"))) is not None:
        return top
    for outer, inner in _CODE_PLACES:
        container = payload.get(outer)
        code = safe_code(container.get(inner)) if isinstance(container, dict) else None
        if code is not None:
            return code
    return None
