"""What this deployment calls itself, who may join it, and whether it is open.

One row, for the whole installation. Not a column on `organizations`: a favicon
is served above every tenant and a sign-in page is rendered before anybody has
chosen one, so the answer cannot be per-organization without asking a stranger
which tenant they meant. The deployment's own administrator (`is_app_admin`)
owns it, which is the same authority that already administers users across
tenants.

**A null column means "the built-in", not "empty".** An operator who has never
opened the page has no row at all, and one who clears a field is asking for the
default back rather than for a blank sign-in header. So every identity column is
nullable and nothing is backfilled; the effective value is resolved where it is
rendered, and `DeploymentSettingsService.effective` is the only place that
resolution happens on this side of the wire.

The singleton is enforced by the database rather than by a convention nobody can
see: `singleton` is unique and constrained to true, so a second row is an
`IntegrityError` instead of a deployment that quietly has two identities and
serves whichever one a query happened to order first.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.db.base import Base, TimestampMixin

SIGNUP_CONSTRAINT = "deployment_settings_singleton_key"
"""The unique constraint the singleton upsert conflicts on.

Named here rather than spelled in the repository: the name is minted by
`NAMING_CONVENTION`, so a literal in the query is a string that has to agree
with a rule it cannot see.
"""


class DeploymentSettings(Base, TimestampMixin):
    """The one row holding this installation's identity and access policy."""

    __tablename__ = "deployment_settings"
    __table_args__ = (CheckConstraint("singleton", name="singleton_true"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    singleton: Mapped[bool] = mapped_column(
        Boolean, nullable=False, unique=True, default=True, server_default=text("true")
    )
    """Always true. The unique constraint on it is what makes this table a singleton."""

    app_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tagline: Mapped[str | None] = mapped_column(String(160), nullable=True)
    description: Mapped[str | None] = mapped_column(String(320), nullable=True)

    logo_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    """Where an uploaded wordmark is stored, when there is one.

    A storage key, written only by `DeploymentSettingsService.set_image`, which
    puts the bytes there itself. Never taken from a request body: the path
    decides which file this deployment serves to anybody who loads a page, and a
    caller who could choose it could read whatever the storage backend holds.
    """

    favicon_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    """The same, for the browser-tab icon. `logo_path`'s reasoning applies whole."""

    footer_text: Mapped[str | None] = mapped_column(String(280), nullable=True)
    terms_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    privacy_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    """Where a client's own terms and policy live, when they are not ours.

    Null keeps the built-in `/legal/*` pages. Set, and every link that pointed at
    them points outward instead — which is what a deployment under somebody
    else's name needs, since our pages describe our terms and not theirs.
    """

    signup_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default=text("'open'")
    )
    """`open`, `invite_only` or `closed`. See `app/services/signup_policy.py`."""

    allowed_email_domains: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    """Lower-cased domains, without the `@`. Empty means every domain is allowed."""

    announcement: Mapped[str | None] = mapped_column(String(500), nullable=True)
    announcement_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="info", server_default=text("'info'")
    )
    """`info`, `warning` or `critical` — which of three styles the banner draws."""

    maintenance_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    maintenance_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<DeploymentSettings(app_name={self.app_name!r}, "
            f"signup={self.signup_mode}, maintenance={self.maintenance_mode})>"
        )
