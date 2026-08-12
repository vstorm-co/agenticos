"""One agent, published somewhere the public can reach it.

Three surfaces share this table - a widget pasted into somebody else's site, a
raw socket somebody writes their own client against, and a page we serve at a
link - because who is on the other end of all three is the same answer, and it
is what makes this its own table rather than another `AgentExposure`: an
exposure binds an agent to a bot the organization owns and a person the
organization can identify, and this binds it to *the public*.

That difference is the whole design:

*Auth is a choice, and both answers are legitimate.* A support widget on a
marketing page has no user to authenticate. A widget inside somebody's logged-in
product does, and the honest way to carry it is a token their backend signs -
we verify it, we never mint it, and we never see their password.

*Origin is the perimeter.* A key in a `<script>` tag is public by construction,
so the thing that stops anyone else running up the bill is which sites the
browser is allowed to call from. A page of our own has no such list, because an
allow-list is a rule about other people's sites.

*Config and context are per embed, not per agent.* The same agent answers on the
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


class AgentEmbed(Base, TimestampMixin):
    """One agent on one public surface."""

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
    # needs a role to resolve what the agent may reach - so it runs as the
    # member who published the widget, and the cost lands on their organization.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)

    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    """Which surface this is: `widget`, `socket` or `page`.

    Fixed at creation. A tag already pasted, a client already written and a link
    already sent all name this row, so changing the kind would change what all
    three do without touching any of them.

    Stored here as well as inside `config`, whose discriminator it is, because a
    `CHECK` cannot usefully read a JSONB key and neither can an index - and the
    two rules that differ per surface are both constraints.
    """

    # What the `<script>` tag, the client or the link carries. Public by
    # construction - it identifies the embed, it does not authenticate anybody.
    public_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    auth_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="public")
    # HS256 secret the customer's backend signs visitor tokens with, sealed by
    # the vault like every other credential. Null in `public` mode.
    jwt_secret_encrypted: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Which sites may open this widget, or open this socket. Empty means none: an
    # embed that answers from anywhere is somebody else's agent running on your
    # bill. Empty on a `page` for the opposite reason - it is served from our own
    # origin, and a list of other people's sites has nothing to say about it.
    allowed_origins: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """What this surface looks like - see `WidgetConfig`, `SocketConfig`, `PageConfig`.

    One column holding a discriminated union rather than one per kind. The
    alternative was a `theme` and a `hosted_config`, of which every row had one
    filled and one inert, plus a boolean saying which - three columns encoding
    what `kind` says once, and three places for them to disagree.
    """
    # Extra instructions for this placement - "you are on the pricing page",
    # "answer in German". Appended to the agent's own, never replacing them.
    context: Mapped[str | None] = mapped_column(Text, nullable=True)

    context_variables: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    """What the page must tell this widget about the visitor in front of it.

    `context` is one sentence, the same for every visitor. This is the part only
    the integrator knows - which plan they are on, which order they are looking
    at - declared here as a name, a `required` flag and a line saying what it is
    for, and supplied by the page at integration time.

    Declared rather than accepted freely: without a declaration, any key the
    page sent would become a line in an agent's instructions, and the page is
    something a visitor can edit. Anything not named here is dropped.

    The flag is documentation and a warning, not a gate - a missing required
    value omits its line and logs, rather than costing the visitor an answer.
    """

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Per visitor, per minute. The one control between a public URL and an
    # afternoon's model budget.
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    __table_args__ = (
        CheckConstraint("auth_mode IN ('public', 'jwt')", name="ck_embed_auth_mode"),
        CheckConstraint("kind IN ('widget', 'socket', 'page')", name="ck_embed_kind"),
        # A page puts its link in chat clients, browser history and `Referer`
        # headers, so `jwt` mode would mean a token travelling through all three.
        # The service refuses the combination at creation with a message; this is
        # the half a future refactor cannot talk its way past.
        CheckConstraint("kind <> 'page' OR auth_mode = 'public'", name="ck_embed_page_is_public"),
        # An allow-list is a rule about other people's sites. A page is ours, so
        # a list on one is either dead configuration or somebody's belief that it
        # is what protects the link - and the link is protected by its key being
        # unguessable, the rate bucket, the budget and the pause switch.
        CheckConstraint(
            "kind <> 'page' OR allowed_origins = '[]'::jsonb",
            name="ck_embed_page_has_no_origins",
        ),
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
