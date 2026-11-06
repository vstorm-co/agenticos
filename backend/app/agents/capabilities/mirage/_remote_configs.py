"""Remote-only service configs; never inherit host credentials or local storage."""

from typing import Annotated
from urllib.parse import urlsplit

from mirage.vfs.box.config import BoxConfig
from mirage.vfs.lancedb.config import LanceDBConfig
from pydantic import Field, SecretStr, field_validator


class BoxServiceConfig(BoxConfig):
    client_id: Annotated[str, Field(min_length=1)]
    client_secret: SecretStr = Field(..., min_length=1)
    enterprise_id: Annotated[str, Field(min_length=1)]
    access_token: None = None
    refresh_token: None = None
    endpoint: None = None
    refresh_fn: None = None
    on_refresh_token_rotated: None = None


class CloudLanceDBConfig(LanceDBConfig):
    uri: Annotated[
        str,
        Field(
            pattern=r"^db://[A-Za-z0-9][A-Za-z0-9_.-]*$",
            description="Cloud database URI: db://database-name.",
        ),
    ]
    api_key: SecretStr = Field(..., min_length=1)
    host_override: Annotated[
        str,
        Field(
            description="HTTPS cloud/enterprise endpoint, explicitly allowed in MIRAGE_ALLOWED_HOSTS."
        ),
    ]
    storage_options: None = None

    @field_validator("host_override")
    @classmethod
    def https_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Use an HTTPS endpoint without credentials, path, query or fragment")
        _ = parsed.port
        return value.rstrip("/")
