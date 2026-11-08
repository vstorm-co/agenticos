"""Server-owned identity of a call, independent of its model-facing name."""

from dataclasses import dataclass
from typing import Literal

type PresentationKind = Literal["draft", "generic", "platform"]


@dataclass(frozen=True)
class ToolIdentity:
    tool_id: str | None = None
    presentation_kind: PresentationKind | None = None

    def wire(self) -> dict[str, str]:
        return {
            key: value
            for key, value in {
                "tool_id": self.tool_id,
                "presentation_kind": self.presentation_kind,
            }.items()
            if value is not None
        }


GENERIC_TOOL = ToolIdentity(presentation_kind="generic")
