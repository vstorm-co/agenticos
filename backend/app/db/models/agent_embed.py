"""One agent, published as a widget somebody else can paste into their site.

The fourth place an agent can answer, after the dashboard, a channel bot and the
API. What makes it its own table rather than another `AgentExposure` is who is
on the other end: an exposure binds an agent to a bot the organization owns and
a person the organization can identify, and this binds it to *the public*.

That difference is the whole design:

*Auth is a choice, and both answers are legitimate.* A support widget on a
marketing page has no user to authenticate. A widget inside somebody's logged-in
product does, and the honest way to carry it is a token their backend signs —
we verify it, we never mint it, and we never see their password.

*Origin is the perimeter.* A key in a `<script>` tag is public by construction,
so the thing that stops anyone else running up the bill is which sites the
browser is allowed to call from.

*Theme and context are per embed, not per agent.* The same agent answers on the
pricing page and in the help centre, in different colours, told where it is.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# What a widget may be styled with. Anything not here is not configurable, which
# is deliberate: a free-form CSS blob in a JSONB column is a stylesheet nobody
# reviews running on somebody else's page.
DEFAULT_THEME: dict[str, Any] = {
    "title": "Ask us anything",
    "subtitle": "",
    "greeting": "Hi — what can I help you with?",
    "placeholder": "Type your message…",
    "accent": "#4f46e5",
    "position": "right",
    "launcher_label": "Chat",
}


class AgentEmbed(Base, TimestampMixin):
    """A public widget for one agent."""

    __tablename__ = "agent_embeds"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Who the run is attributed to. The visitor is anonymous, but a run still
    # needs a role to resolve what the agent may reach — so it runs as the
    # member who published the widget, and the cost lands on their organization.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # What the `<script>` tag carries. Public by construction — it identifies
    # the widget, it does not authenticate anybody.
    public_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    auth_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="public")
    # HS256 secret the customer's backend signs visitor tokens with, sealed by
    # the vault like every other credential. Null in `public` mode.
    jwt_secret_encrypted: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Which sites may open this widget. Empty means none: a widget that answers
    # from anywhere is somebody else's agent running on your bill.
    allowed_origins: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    theme: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=lambda: dict(DEFAULT_THEME), server_default="{}"
    )
    # Extra instructions for this placement — "you are on the pricing page",
    # "answer in German". Appended to the agent's own, never replacing them.
    context: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Per visitor, per minute. The one control between a public URL and an
    # afternoon's model budget.
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    __table_args__ = (
        CheckConstraint("auth_mode IN ('public', 'jwt')", name="ck_embed_auth_mode"),
        CheckConstraint("rate_limit_per_minute > 0", name="ck_embed_rate_limit_positive"),
        # A `jwt` embed with no secret cannot verify anything, and the failure
        # mode is the dangerous one: every token would be rejected, or worse, a
        # future refactor treats "no secret" as "no check".
        CheckConstraint(
            "auth_mode <> 'jwt' OR jwt_secret_encrypted IS NOT NULL",
            name="ck_embed_jwt_needs_secret",
        ),
    )

    def __repr__(self) -> str:
        return f"<AgentEmbed(id={self.id}, name={self.name}, agent={self.agent_id})>"
