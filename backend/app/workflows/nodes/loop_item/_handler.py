"""`loop.item`: the element one `control.foreach` iteration works on.

Permanently without a handler: nothing ever dispatches it. When an iteration
starts, the dispatcher writes this node's row already succeeded with the
element, its index and the list's length as its output, so every body node binds
to them through the ordinary output lookup.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


class LoopItemOutput(BaseModel):
    """The current element, where it sits in the list, and how long the list is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item: Any = None
    index: int
    count: int
