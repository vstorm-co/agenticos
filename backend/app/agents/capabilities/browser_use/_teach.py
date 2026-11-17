"""The seam where browser teaching hears a person's input in a tab they hold.

`held` is the one place a person's commands reach a managed browser page, so it
is the only place capture is attached. The capture object is owned by the
teaching service; this module only names what the loop calls, so the loop has
no knowledge of storage, permissions or Redis.

Every method must swallow its own failures. Capture is never allowed to break,
slow beyond a bounded check, or change the person's control of the tab.
"""

from typing import Protocol

from app.agents.browser_events import BrowserCommand


class TeachCapture(Protocol):
    async def begin(self, call_id: str, by_user_id: str | None) -> None:
        """A person took the tab over in view `call_id`."""

    async def before_input(self, command: BrowserCommand) -> object | None:
        """Observe the input's target before it acts, or `None` to record nothing."""

    async def after_input(self, prepared: object | None) -> None:
        """The input was carried out; record what `before_input` observed."""

    async def end(self) -> None:
        """The person handed the tab back, lost it, or the hold timed out."""
