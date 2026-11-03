"""A `WindowStore` with no database, for tests of what the WhatsApp adapter sends (#2076)."""

from datetime import datetime

from app.services.channels.whatsapp_customers import WindowStore
from app.services.channels.whatsapp_templates import LateTemplate
from app.services.channels.whatsapp_window import UndeliveredReason, closure_is_news, window_open


class FakeWindowStore(WindowStore):
    """Answers from the values it is given and records what the adapter wrote.

    `record=False` is a customer with no record, which the adapter answers as it
    always did. `held` holds `(run_id, answer, files)`.
    """

    def __init__(
        self,
        last_inbound_at: datetime | None = None,
        closed_at: datetime | None = None,
        template: LateTemplate | None = None,
        record: bool = True,
    ) -> None:
        super().__init__()
        self.last_inbound_at = last_inbound_at
        self.closed_at = closed_at
        self.template = template
        self.record = record
        self.held: list[tuple[str, bool, bool]] = []
        self.closures: list[datetime] = []
        self.undelivered: list[tuple[str, UndeliveredReason | None]] = []

    def _open(self, now: datetime) -> bool:
        return window_open(last_inbound_at=self.last_inbound_at, closed_at=self.closed_at, now=now)

    async def window(self, bot_id: str, chat_id: str, *, now: datetime) -> bool | None:
        return self._open(now) if self.record else None

    async def late_template(self, bot_id: str) -> LateTemplate | None:
        return self.template

    async def hold_unless_open(
        self, bot_id: str, chat_id: str, *, run_id: str, answer: bool, files: bool, now: datetime
    ) -> bool:
        if self._open(now):
            return True
        self.held.append((run_id, answer, files))
        return False

    async def hold(
        self, bot_id: str, chat_id: str, *, run_id: str, answer: bool, files: bool
    ) -> None:
        self.held.append((run_id, answer, files))

    async def close(self, bot_id: str, chat_id: str, *, at: datetime) -> bool:
        self.closures.append(at)
        if closure_is_news(last_inbound_at=self.last_inbound_at, closed_at=self.closed_at, at=at):
            self.closed_at = at
            return True
        return False

    async def record_undelivered(
        self, bot_id: str, run_id: str, reason: UndeliveredReason | None
    ) -> None:
        self.undelivered.append((run_id, reason))


class OpenWindow(FakeWindowStore):
    """A window that is always open."""

    def _open(self, now: datetime) -> bool:
        return True
