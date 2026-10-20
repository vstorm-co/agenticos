"""How a speech provider's refusal reaches the caller, without the provider's words."""

from enum import StrEnum

from app.core.exceptions import ExternalServiceError


class SpeechFailure(StrEnum):
    """What went wrong, as something a caller can branch on.

    The capability answers these differently: a refused key is the operator's to
    fix and is said plainly, a voice the provider does not know is the agent
    author's, and a provider that is down is worth one more try later. A sentence
    alone would leave the caller matching on wording.
    """

    CREDENTIALS = "credentials"
    """The provider refused the key - missing, expired, or without access."""

    NOT_FOUND = "not_found"
    """The provider does not know the voice or the model."""

    REJECTED = "rejected"
    """The provider refused this text: too long, empty, or against its policy."""

    RATE_LIMITED = "rate_limited"
    """Too many requests, or the account's quota is spent."""

    UNAVAILABLE = "unavailable"
    """The provider failed, timed out, or answered with something that is not audio."""


_MESSAGES = {
    SpeechFailure.CREDENTIALS: "The speech provider refused the API key.",
    SpeechFailure.NOT_FOUND: "The speech provider does not know this voice or model.",
    SpeechFailure.REJECTED: "The speech provider refused this text.",
    SpeechFailure.RATE_LIMITED: "The speech provider is rate limiting this key, or its quota is spent.",
    SpeechFailure.UNAVAILABLE: "The speech provider did not return audio.",
}


class SpeechProviderError(ExternalServiceError):
    """A provider call that produced no audio.

    The provider's own response body is logged where it is received and never
    carried here: this message reaches a model and, through it, a chat, and a
    provider's error text is not a string this repository controls.
    """

    code = "SPEECH_PROVIDER_ERROR"

    def __init__(self, failure: SpeechFailure, *, provider: str, status: int | None = None) -> None:
        super().__init__(
            message=_MESSAGES[failure],
            details={"provider": provider, "failure": failure.value, "status": status},
        )
        self.failure = failure
        self.spoken_characters = 0
        """Characters spoken before this failed - billed by the provider all the same.

        Set by :func:`~app.services.text_to_speech.synthesize` when a long text
        fails partway, so the caller can book what the earlier pieces cost: the
        clip is discarded, the provider's charge for it is not.
        """
