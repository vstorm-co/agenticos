"""Where an organization's sandboxes actually run.

This started as two environment variables. That was wrong in two ways that only
showed up once somebody used it.

*A deployment can have more than one host.* `SANDBOXD_URL` is one address, so an
organization with two Docker hosts - a big one for data work, a small one for
everything else - could reach exactly one of them. And Daytona was a third
mechanism again: a key hanging off a capability binding rather than a place
sandboxes run.

*The token belongs in the vault.* It authorises opening a session, and a session
runs commands on the host holding the Docker socket. Every other credential at
rest in this platform goes through `app/core/vault.py`; a file beside the
database password was the one exception, and there was no reason for it.

So: a row, per organization, named and pointed at a service, with its credential
referenced rather than embedded. `model_profiles` and `mcp_connections` are the
same shape, and an agent spec names one the same way it names a model profile -
by id, or not at all to take the organization's default.

What is deliberately *not* here: the service's own ceilings. `mem_limit`, the
network mode, the runtime allowlist and the rest are `sandboxd`'s boot
configuration, read from its environment where it starts. There is no endpoint to
write them and there should not be - a browser that could reconfigure the process
holding the Docker socket is a browser that owns the host. The operator screen
*reads* them from `GET /policy` so that what is in force is visible; changing
them stays where it can be done safely.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SandboxConnection(Base, TimestampMixin):
    """One place an organization's agents may be given a workspace."""

    __tablename__ = "sandbox_connections"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_sandbox_connection_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    """What an operator calls this host. Shown wherever an agent picks one."""

    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    """`docker` for a `sandboxd` service, `daytona` for the cloud.

    The *kind* decides what `base_url` and the credential mean, which is why an
    agent spec does not carry it: naming the connection is naming the kind.
    """

    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    """Where the service answers. Null for Daytona, which has one address of its own."""

    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization_secrets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """The vault entry holding the service token, or the Daytona API key.

    `SET NULL` rather than `CASCADE`: deleting a key should not silently delete
    the record of a host and every workspace keyed to it. The connection becomes
    unusable and says so - which is a state somebody can fix - instead of
    disappearing along with the reason.
    """

    default_runtime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """The alias an agent gets when its spec names none. Null takes the service's own."""

    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Which connection a spec with no `connection_id` resolves to.

    One per organization, enforced by the service rather than by a constraint: a
    partial unique index would make "promote this one" two statements that can
    fail between each other.
    """

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """Turned off rather than deleted, so the rows keyed to it keep their meaning."""

    def __repr__(self) -> str:
        return (
            f"<SandboxConnection(id={self.id}, name={self.name}, "
            f"kind={self.kind}, default={self.is_default})>"
        )
