"""Refusals a call meets before it starts, each with a reason the client can render (#54)."""

from app.core.exceptions import BadRequestError


class VoiceRefused(BadRequestError):
    """A call that will not start. `reason` is a stable code; `message` is safe to show."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message=message, details={"reason": reason})
        self.reason = reason
