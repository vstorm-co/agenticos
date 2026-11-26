"""One deliberately selected vault key crossing to its owner's native runtime."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

PiKeyProvider = Literal["inception", "deepseek", "openrouter"]
NativeKeyProvider = PiKeyProvider | Literal["gemini"]
"""Pi providers through its isolated extension; Gemini as the Antigravity key template's key."""


class NativeRuntimeKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    provider: NativeKeyProvider
    api_key: SecretStr = Field(min_length=8, max_length=16384)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("api_key")
    @classmethod
    def header_value(cls, value: SecretStr) -> SecretStr:
        if any(not 33 <= ord(character) <= 126 for character in value.get_secret_value()):
            raise ValueError("A provider key must be a printable HTTP credential")
        return value

    @property
    def pi_provider(self) -> PiKeyProvider | None:
        """The Pi lane this key drives, or None for a non-Pi runtime's key."""
        return None if self.provider == "gemini" else self.provider

    def native_payload(self, model_id: str) -> dict[str, str]:
        """For the authenticated native launch only; never a transcript or report."""
        return {
            "provider": self.provider,
            "api_key": self.api_key.get_secret_value(),
            "model_id": model_id,
        }
