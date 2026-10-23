"""Text to speech: turning text into a clip through the provider a binding chose.

The facade is :func:`synthesize`; the provider clients behind it are package
internals. Which providers, models and voices exist is not decided here - that is
:mod:`app.services.text_to_speech_models` - only how each one is called (#2259).
"""

from app.services.text_to_speech.exceptions import SpeechFailure, SpeechProviderError
from app.services.text_to_speech.synthesis import (
    ACCOUNT_VOICE_ID,
    Speech,
    SpokenPiece,
    synthesize,
)

__all__ = [
    "ACCOUNT_VOICE_ID",
    "Speech",
    "SpeechFailure",
    "SpeechProviderError",
    "SpokenPiece",
    "synthesize",
]
