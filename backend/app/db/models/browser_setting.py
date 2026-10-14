"""How an organization's agents reach the web when they browse (#2130).

One row per organization, or none for the default: the browser the agent's own
`cdp_url` names, reaching sites from the deployment's address. Two things a
deployment's address cannot give - a residential or regional address, and a
browser a hosted service already keeps undetected - are what this row is for.

The credential is referenced, never held: `secret_id` names the vault entry with
the proxy's `username:password` or the hosted browser's API key, the same shape
`sandbox_connections` and `model_profiles` take.
"""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BrowserSetting(Base, TimestampMixin):
    """Where an organization's browses run, and how they say where they are."""

    __tablename__ = "browser_settings"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="built_in")
    """`built_in`, `proxy` or `remote` - see `BrowserMode`."""

    proxy_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    """`http://`, `https://` or `socks5://` host and port, never with credentials in it."""

    remote_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    """A hosted browser's CDP address, without its key."""

    remote_key_param: Mapped[str] = mapped_column(String(64), nullable=False, default="apiKey")
    """The query parameter a hosted browser reads its key from - `apiKey` for
    Browserbase and Steel."""

    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_secrets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """An IANA zone the browser says it is in, or none for the browser's own."""

    locale: Mapped[str | None] = mapped_column(String(35), nullable=True)
    """A language tag the browser says it reads, or none for the browser's own."""

    def __repr__(self) -> str:
        return f"<BrowserSetting(organization_id={self.organization_id}, mode={self.mode})>"
