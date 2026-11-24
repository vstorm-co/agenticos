"""A sticky output boundary: an unprovably safe page never resumes capture."""

import asyncio
from collections.abc import Awaitable, Callable

from app.agents.browser_events import BrowserEvent
from app.agents.capabilities.browser_use._elements import Snapshot
from app.core.browser_origins import browser_origin

PROTECTED_TITLE = "Protected browser session"
PROTECTED_TEXT = (
    "Page output is hidden after a credential fill. Close this tab to end protection; "
    "a navigation or form submission does not make the page safe to capture."
)


class BrowserOutputGuard:
    """Installed before any value is opened, and never reset on this page object."""

    def __init__(self) -> None:
        self._origin: str | None = None
        # Every live view of this page shares the fence. Announcing protection
        # must settle publications from an earlier browse before native delivery.
        self.publication_lock = asyncio.Lock()
        self._views: dict[object, Callable[[], Awaitable[None]]] = {}
        self._announced: set[object] = set()

    def bind_view(self, token: object, announce: Callable[[], Awaitable[None]]) -> None:
        """Keep every page-bound view until the page ends, including earlier calls."""
        self._views.setdefault(token, announce)

    async def announce(self) -> None:
        """Called under publication_lock; every cache must clear before delivery."""
        for token, publish in tuple(self._views.items()):
            if token not in self._announced:
                await publish()
                self._announced.add(token)

    @property
    def active(self) -> bool:
        return self._origin is not None

    def protect(self, origin: str) -> None:
        normalized = browser_origin(origin)
        if self._origin is None:
            self._origin = normalized

    def location(self) -> tuple[str, str]:
        return self._origin or "about:blank", PROTECTED_TITLE

    def snapshot(self) -> Snapshot:
        url, title = self.location()
        return Snapshot(url=url, title=title, elements=(), text=PROTECTED_TEXT)

    def event(self, event: BrowserEvent) -> BrowserEvent:
        """Rebuild from an allowlist, so future event fields cannot bypass protection."""
        url, title = self.location()
        return BrowserEvent(
            kind=event.kind,
            call_id=event.call_id,
            step=event.step,
            tab_id=event.tab_id,
            run_id=event.run_id,
            outcome=event.outcome,
            credential_plan_id=event.credential_plan_id,
            credential_operation=event.credential_operation,
            output_protected=True,
            url=url,
            title=title,
            reason=PROTECTED_TEXT,
        )
