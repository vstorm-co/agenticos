"""How a video provider's refusal reaches the caller, without the provider's words."""

from enum import StrEnum

from app.core.exceptions import ExternalServiceError


class VideoFailure(StrEnum):
    """What went wrong, as something a caller can branch on.

    The capability answers these differently: a refused key is the operator's to
    fix, a prompt the provider's policy refused is answered to the model as
    refused, and a provider that is down or slow is worth one more try later.
    """

    CREDENTIALS = "credentials"
    """The provider refused the key - missing, expired, or without access."""

    POLICY = "policy"
    """The provider's content policy refused the prompt, the image or the result."""

    REJECTED = "rejected"
    """The provider refused the request for another reason - a parameter, a model."""

    RATE_LIMITED = "rate_limited"
    """Too many requests, too many queued jobs, or the account's quota is spent."""

    UNAVAILABLE = "unavailable"
    """The provider failed, or answered with something that is not a video."""

    TIMED_OUT = "timed_out"
    """The job did not finish within the binding's time limit."""


_MESSAGES = {
    VideoFailure.CREDENTIALS: "The video provider refused the API key.",
    VideoFailure.POLICY: "The video provider's content policy refused this prompt or image.",
    VideoFailure.REJECTED: "The video provider refused this request.",
    VideoFailure.RATE_LIMITED: "The video provider is rate limiting this key, or its quota is spent.",
    VideoFailure.UNAVAILABLE: "The video provider did not return a video.",
    VideoFailure.TIMED_OUT: "The video was not ready within the time limit.",
}


class VideoProviderError(ExternalServiceError):
    """A provider call that produced no video.

    Only the error code the provider names is logged (`provider_error_code.py`);
    its body is never logged nor carried here: this message reaches a model and,
    through it, a chat.
    """

    code = "VIDEO_PROVIDER_ERROR"

    def __init__(self, failure: VideoFailure, *, provider: str, status: int | None = None) -> None:
        super().__init__(
            message=_MESSAGES[failure],
            details={"provider": provider, "failure": failure.value, "status": status},
        )
        self.failure = failure
