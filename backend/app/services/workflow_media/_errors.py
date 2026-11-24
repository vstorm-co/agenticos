"""Controlled workflow media failures; provider bodies and credentials never escape."""

from app.core.exceptions import AppException


class MediaOperationError(AppException):
    code = "MEDIA_OPERATION_REFUSED"
    status_code = 409
    message = "This media operation cannot continue safely."

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message=message)
        self.code = code
