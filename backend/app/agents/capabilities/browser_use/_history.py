"""Request-only removal of obsolete browser element numbers, retaining page evidence."""

from dataclasses import replace

from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart

from app.agents.capabilities.browser_use._direct import UNTRUSTED

_TABLE = f"\nELEMENTS ({UNTRUSTED}):\n"
_TEXT = f"\n\nPAGE TEXT ({UNTRUSTED}):\n"
_ACTION = "\n\nAct on an element by its number"
BROWSER_REPORT_TOOLS = frozenset(
    {
        "browser_open",
        "browser_new_tab",
        "browser_switch_tab",
        "browser_read",
        "browser_click",
        "browser_type",
        "browser_select",
        "browser_scroll",
        "browser_back",
    }
)


def _earlier_report(content: str) -> str | None:
    before, marker, after = content.partition(_TABLE)
    if not marker:
        return None
    ends = [position for end in (_TEXT, _ACTION) if (position := after.find(end)) >= 0]
    if not ends:
        return None
    return (
        before
        + "\nELEMENTS: Earlier table omitted; use the latest browser read for element numbers."
        + after[min(ends) :]
    )


def compact_browser_tables(
    messages: list[ModelMessage], names: frozenset[str] = BROWSER_REPORT_TOOLS
) -> list[ModelMessage]:
    """Keep the latest DOM table intact; copy older reports without their stale tables.

    Tool ids, action outcomes, page addresses and article text remain verbatim.
    Persistent history and provider continuation responses are never edited.
    """
    if not messages or not isinstance(messages[-1], ModelRequest):
        return messages
    latest = True
    copied = list(messages)
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, ModelRequest):
            continue
        parts = list(message.parts)
        changed = False
        for position in range(len(parts) - 1, -1, -1):
            part = parts[position]
            if not (
                isinstance(part, ToolReturnPart)
                and part.tool_name in names
                and isinstance(part.content, str)
            ):
                continue
            shorter = _earlier_report(part.content)
            if shorter is None:
                continue
            if latest:
                latest = False
                continue
            parts[position] = replace(part, content=shorter)
            changed = True
        if changed:
            copied[index] = replace(message, parts=parts)
    return copied
