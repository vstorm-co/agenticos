"""An organization's browser setting: built in, through a proxy, or a hosted browser."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class BrowserMode(StrEnum):
    """Where an organization's browses run.

    `built_in` is the browser an agent's `cdp_url` names, reaching sites from the
    deployment's own address. `proxy` is the same browser reaching them through a
    proxy - a residential or regional address. `remote` is a hosted browser
    (Browserbase, Steel, a self-hosted one) reached over CDP instead.
    """

    BUILT_IN = "built_in"
    PROXY = "proxy"
    REMOTE = "remote"


class BrowserSettingUpdate(BaseSchema):
    """The whole setting, written at once - the form has one Save."""

    mode: BrowserMode = BrowserMode.BUILT_IN
    proxy_url: str | None = Field(
        default=None,
        max_length=512,
        description="`http://`, `https://` or `socks5://` host:port; credentials go in the vault",
    )
    remote_url: str | None = Field(
        default=None,
        max_length=512,
        description="A hosted browser's CDP address, `wss://`, without its key",
    )
    remote_key_param: str = Field(
        default="apiKey",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The query parameter the hosted browser reads its key from",
    )
    secret_id: UUID | None = Field(
        default=None,
        description="The vault entry: `username:password` for a proxy, the API key for a hosted browser",
    )
    timezone: str | None = Field(
        default=None, max_length=64, description="An IANA time zone the browser says it is in"
    )
    locale: str | None = Field(
        default=None,
        max_length=35,
        pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$",
        description="A language tag the browser says it reads, such as `pl-PL`",
    )


class BrowserSettingRead(BrowserSettingUpdate):
    """The setting as stored - never the credential, only which vault entry holds it."""

    updated_at: datetime | None = None
