"""Provider credentials and model profiles - per organization.

Two tables because "which model" and "which key" are separate decisions that
change at different times. An organization rotates a key without touching the
agents that use it; it points an agent at a cheaper model without re-entering a
secret. Agent specs therefore reference a **model profile**, never a raw model
string or a global environment key.
"""

import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ModelProfile(Base, TimestampMixin):
    """A selectable "model" in the UI: a provider, a model id and a key.

    This is the unit an agent spec references. Naming it ("Claude Sonnet (prod)")
    rather than storing `anthropic:claude-sonnet-4-6` in every spec means the
    organization can repoint or rekey every agent at once, and that a spec
    exported to git carries no secret and no infrastructure detail.
    """

    __tablename__ = "model_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    # The vault secret this model is keyed by. The newer of two paths: a
    # `credential` is the template's own store, and a `secret` is the one
    # people actually manage - picking "OpenRouter" in the vault is what makes
    # OpenRouter's models selectable. Exactly one of the two is set; the
    # resolver reads whichever it finds.
    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization_secrets.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Where to send the request, when it is not the provider's public API: a
    # gateway, a LiteLLM proxy, or a model server on the deployment's own
    # network. On the profile rather than on the secret because a secret says
    # what authenticates and this says where it is sent - the same key in front
    # of a staging proxy and a production one is two profiles, one secret.
    #
    # Only stored for providers whose SDK names an endpoint parameter
    # (`ProviderSpec.base_url_param`); the service refuses one for the rest
    # rather than accepting a value it would silently drop.
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Model settings (temperature, max_tokens...) applied on every run.
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Whether a user may substitute their own key when running with this profile.
    allow_byo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Ordered profile ids tried when the primary fails - becomes a FallbackModel.
    fallback_profile_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "label", name="uq_model_profile_org_label"),
    )

    def __repr__(self) -> str:
        return f"<ModelProfile(org={self.organization_id}, {self.label} -> {self.model})>"
