"""One deliberately selected key crossing to its owner's native Pi process."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

PiKeyProvider = Literal["inception", "deepseek", "openrouter"]


class PiRuntimeKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    provider: PiKeyProvider
    api_key: SecretStr = Field(min_length=8, max_length=16384)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("api_key")
    @classmethod
    def header_value(cls, value: SecretStr) -> SecretStr:
        if any(not 33 <= ord(character) <= 126 for character in value.get_secret_value()):
            raise ValueError("A Pi provider key must be a printable HTTP credential")
        return value

    def native_payload(self, model_id: str) -> dict[str, str]:
        """For the authenticated native launch only; never a transcript or report."""
        return {
            "provider": self.provider,
            "api_key": self.api_key.get_secret_value(),
            "model_id": model_id,
        }
