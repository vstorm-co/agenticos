"""One Odoo database's API key, sealed with its exact deployment origin."""

from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.core.secret_kinds import SealedStr


class OdooCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    origin: str = Field(max_length=2048)
    database: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    api_key: SealedStr = Field(min_length=1, max_length=4096)

    @field_validator("origin")
    @classmethod
    def _origin(cls, value: str) -> str:
        if any(ord(char) <= 32 or ord(char) == 127 for char in value):
            raise ValueError("Use an Odoo origin without whitespace or control characters")
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
            or parts.port not in {None, 443}
        ):
            raise ValueError("Use the Odoo HTTPS origin without a path, credentials or query")
        return value.rstrip("/")

    @field_validator("api_key")
    @classmethod
    def _key(cls, value: SecretStr) -> SecretStr:
        if any(ord(char) < 33 or ord(char) > 126 for char in value.get_secret_value()):
            raise ValueError("Use a printable ASCII Odoo API key without whitespace")
        return value
