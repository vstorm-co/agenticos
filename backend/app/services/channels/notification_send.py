"""Confirmed non-acceptance is the only safe retry contract for chat notifications."""

from app.core.exceptions import ExternalServiceError


class NotificationRateLimited(ExternalServiceError):
    """The provider explicitly refused the submission; no message was accepted."""

    def __init__(self, *, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, min(retry_after_seconds, 86400))
        super().__init__(
            message="The chat provider declined this notification because of its rate limit",
            details={"retry_after_seconds": self.retry_after_seconds},
        )


def retry_after_seconds(value: object) -> int:
    """Bound a provider's delay; missing/malformed headers use one minute."""
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, str):
        value = value.strip()
        if value.isascii() and value.isdecimal() and len(value) <= 6:
            return max(1, min(int(value), 86400))
    return 60
