"""Customer identity helpers for Shop widget conversation threads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

WIDGET_CONVERSATION_TITLE = "Shop widget"

_NAME_PATTERNS = (
    re.compile(
        r"(?:tên|ten)\s*(?:mình|minh|tôi|toi)\s*(?:là|la)\s*([^\s,.!?]{2,40})",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"(?:mình|minh|tôi|toi)\s*(?:tên|ten)\s*(?:là|la)\s*([^\s,.!?]{2,40})",
        re.IGNORECASE | re.UNICODE,
    ),
)


@dataclass(frozen=True, slots=True)
class WidgetCustomerIdentity:
    session_id: UUID | None
    shopper_user_id: UUID | None
    shopper_display_name: str | None
    shopper_email: str | None = None


def widget_conversation_title(
    session_id: UUID,
    *,
    shopper_user_id: UUID | None = None,
    shopper_display_name: str | None = None,
    shopper_email: str | None = None,
) -> str:
    base = f"{WIDGET_CONVERSATION_TITLE}|{session_id}"
    if shopper_user_id is None:
        return base
    safe_name = (shopper_display_name or "").replace("|", " ").strip()[:80]
    title = f"{base}|shopper:{shopper_user_id}|{safe_name}"
    email = (shopper_email or "").strip()
    if email and "@" in email:
        title = f"{title}|{email[:120]}"
    return title


def is_widget_conversation_title(title: str | None) -> bool:
    if not title:
        return False
    if title == WIDGET_CONVERSATION_TITLE:
        return True
    return title.startswith(f"{WIDGET_CONVERSATION_TITLE}|")


def parse_widget_session_id(title: str | None) -> UUID | None:
    return parse_widget_customer_identity(title).session_id


def parse_widget_customer_identity(title: str | None) -> WidgetCustomerIdentity:
    if not title or not is_widget_conversation_title(title):
        return WidgetCustomerIdentity(None, None, None, None)

    parts = title.split("|")
    session_id: UUID | None = None
    if len(parts) >= 2:
        try:
            session_id = UUID(parts[1].strip())
        except ValueError:
            session_id = None

    shopper_user_id: UUID | None = None
    shopper_display_name: str | None = None
    shopper_email: str | None = None
    if len(parts) >= 4 and parts[2].startswith("shopper:"):
        raw_id = parts[2].split(":", 1)[1].strip()
        try:
            shopper_user_id = UUID(raw_id)
        except ValueError:
            shopper_user_id = None
        shopper_display_name = parts[3].strip() or None
        if len(parts) >= 5 and "@" in parts[4]:
            shopper_email = parts[4].strip() or None

    return WidgetCustomerIdentity(
        session_id=session_id,
        shopper_user_id=shopper_user_id,
        shopper_display_name=shopper_display_name,
        shopper_email=shopper_email,
    )


def short_customer_ref(session_id: UUID | None, *, conversation_id: UUID) -> str:
    source = session_id or conversation_id
    return source.hex[:8].upper()


def infer_customer_label(first_user_messages: list[str]) -> str | None:
    for text in first_user_messages:
        cleaned = (text or "").strip()
        if not cleaned:
            continue
        for pattern in _NAME_PATTERNS:
            match = pattern.search(cleaned)
            if match:
                name = match.group(1).strip()
                if len(name) >= 2:
                    return name[:40]
    for text in first_user_messages:
        snippet = " ".join((text or "").split())
        if snippet:
            return snippet[:48]
    return None


def resolve_customer_label(
    *,
    identity: WidgetCustomerIdentity,
    first_user_messages: list[str],
) -> str | None:
    if identity.shopper_display_name:
        return identity.shopper_display_name[:80]
    return infer_customer_label(first_user_messages)


def resolve_customer_ref(
    *,
    identity: WidgetCustomerIdentity,
    conversation_id: UUID,
) -> str:
    if identity.shopper_user_id:
        return identity.shopper_user_id.hex[:8].upper()
    return short_customer_ref(identity.session_id, conversation_id=conversation_id)
