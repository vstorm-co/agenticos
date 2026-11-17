"""IMAP credentials sealed as one connected-account vault envelope."""

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.core.secret_kinds import SealedStr


class ImapCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    host: str = Field(min_length=1, max_length=253, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9.-]*$")
    port: int = Field(default=993, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255, pattern=r"^[^\r\n\x00]+$")
    password: SealedStr = Field(min_length=1, max_length=4096)
    folder: str = Field(default="INBOX", min_length=1, max_length=255, pattern=r"^[^\r\n\x00]+$")

    @field_validator("password")
    @classmethod
    def _one_line_password(cls, value: SecretStr) -> SecretStr:
        if any(char in value.get_secret_value() for char in "\r\n\x00"):
            raise ValueError("An IMAP password must not contain line breaks or NUL")
        return value
