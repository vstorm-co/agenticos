"""Managing where an organization's sandboxes run, and reaching those places.

Two jobs that belong together because both need the vault: the operator-facing
half creates and edits connections, and the run-facing half resolves the one an
agent should use and unseals its credential.

The credential never leaves this module as anything but an argument to a client.
It is a service token - whoever holds it can open a session, and a session runs
commands on the host holding the Docker socket - so it must not reach a response,
a log line or a browser. `tests/api/test_no_secret_escapes.py` is the standing
check on that; the shape here is what keeps it true: read the sealed row, unseal
at the moment of use, hand the plaintext to the client and nothing else.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret
from app.db.models.sandbox_connection import SandboxConnection
from app.repositories import agent_workspace_repo, sandbox_connection_repo
from app.schemas.sandbox_connection import (
    SandboxConnectionCreate,
    SandboxConnectionRead,
    SandboxConnectionUpdate,
)
from app.services.organization_secret import OrganizationSecretService

logger = logging.getLogger(__name__)

CONNECTION_KINDS = ("docker", "daytona")


@dataclass(frozen=True)
class ResolvedConnection:
    """A connection with its credential unsealed, ready to open a sandbox with."""

    row: SandboxConnection
    token: str

    @property
    def kind(self) -> str:
        return self.row.kind

    def __repr__(self) -> str:
        # The token is the whole reason this dataclass exists; a default repr
        # would put it in every log line that touches one.
        return f"<ResolvedConnection(id={self.row.id}, kind={self.row.kind})>"


def to_read(row: SandboxConnection) -> SandboxConnectionRead:
    """What a client is told about a connection.

    Never the credential, and never a hint of it: `secret_id` is a reference the
    Builder can render as a name by asking the vault, which applies its own
    permission check on the way.
    """
    return SandboxConnectionRead(
        id=row.id,
        name=row.name,
        kind=row.kind,
        base_url=row.base_url,
        secret_id=row.secret_id,
        default_runtime=row.default_runtime,
        is_default=row.is_default,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SandboxConnectionService:
    """Create, edit and resolve the places sandboxes run."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.secrets = OrganizationSecretService(db)

    # -- operator-facing ------------------------------------------------

    async def list_connections(self, ctx: AuthContext) -> list[SandboxConnectionRead]:
        rows = await sandbox_connection_repo.list_for_organization(
            self.db, organization_id=ctx.organization_id
        )
        return [to_read(row) for row in rows]

    async def get(self, ctx: AuthContext, connection_id: UUID) -> SandboxConnection:
        row = await sandbox_connection_repo.get(
            self.db, connection_id, organization_id=ctx.organization_id
        )
        if row is None:
            raise NotFoundError(
                message="Sandbox connection not found",
                details={"connection_id": str(connection_id)},
            )
        return row

    async def create(
        self, ctx: AuthContext, data: SandboxConnectionCreate
    ) -> SandboxConnectionRead:
        """Register a place sandboxes run.

        Raises:
            AlreadyExistsError: If the organization already has one by that name.
            BadRequestError: If the connection could not be reached with what it
                was given. A connection that cannot answer is one every agent
                bound to it fails on, and the person who can fix it is the one
                filling in this form.
        """
        await self._refuse_duplicate_name(ctx, data.name)
        self._check_shape(kind=data.kind, base_url=data.base_url)

        first = not await sandbox_connection_repo.list_for_organization(
            self.db, organization_id=ctx.organization_id
        )
        row = await sandbox_connection_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            name=data.name,
            kind=data.kind,
            base_url=data.base_url,
            secret_id=data.secret_id,
            default_runtime=data.default_runtime,
            # The first connection an organization registers is its default,
            # because the alternative is a form that succeeds and an agent that
            # then cannot find a workspace.
            is_default=data.is_default or first,
        )
        if row.is_default:
            await sandbox_connection_repo.clear_default(
                self.db, organization_id=ctx.organization_id, except_id=row.id
            )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="sandbox_connection.created",
            target_type="sandbox_connection",
            target_id=str(row.id),
            details={"name": row.name, "kind": row.kind},
        )
        return to_read(row)

    async def update(
        self, ctx: AuthContext, connection_id: UUID, data: SandboxConnectionUpdate
    ) -> SandboxConnectionRead:
        row = await self.get(ctx, connection_id)
        changes = data.model_dump(exclude_unset=True)

        if "name" in changes and changes["name"] != row.name:
            await self._refuse_duplicate_name(ctx, changes["name"])
        self._check_shape(
            kind=changes.get("kind", row.kind),
            base_url=changes.get("base_url", row.base_url),
        )

        promoting = changes.get("is_default") is True
        row = await sandbox_connection_repo.update_connection(
            self.db, connection=row, update_data=changes
        )
        if promoting:
            await sandbox_connection_repo.clear_default(
                self.db, organization_id=ctx.organization_id, except_id=row.id
            )
        return to_read(row)

    async def delete(self, ctx: AuthContext, connection_id: UUID) -> None:
        """Remove a connection.

        The workspaces keyed to it are left alone: their rows record what an
        agent did and where, and deleting a host is not a statement about that
        history. A published agent naming it starts failing with a message that
        says the connection is gone, which is the truth.
        """
        row = await self.get(ctx, connection_id)
        await sandbox_connection_repo.delete(self.db, connection=row)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="sandbox_connection.deleted",
            target_type="sandbox_connection",
            target_id=str(connection_id),
            details={"name": row.name},
        )

    async def _refuse_duplicate_name(self, ctx: AuthContext, name: str) -> None:
        existing = await sandbox_connection_repo.get_by_name(
            self.db, organization_id=ctx.organization_id, name=name
        )
        if existing is not None:
            raise AlreadyExistsError(
                message="A sandbox connection by that name already exists",
                details={"name": name},
            )

    @staticmethod
    def _check_shape(*, kind: str, base_url: str | None) -> None:
        """Refuse a connection whose shape cannot work, while a form is open.

        Both of these otherwise surface on an agent's first tool call, where the
        reader is a user in a conversation rather than the operator who filled
        this in.
        """
        if kind not in CONNECTION_KINDS:
            raise BadRequestError(
                message=f"Unknown sandbox kind: {kind}",
                details={"kind": kind, "expected": list(CONNECTION_KINDS)},
            )
        if kind == "docker" and not base_url:
            raise BadRequestError(
                message="A container connection needs the address its sandbox service answers on",
                details={"field": "base_url"},
            )

    # -- run-facing ----------------------------------------------------

    async def resolve(self, ctx: AuthContext, connection_id: UUID | None) -> ResolvedConnection:
        """The connection an agent should use, with its credential unsealed.

        Args:
            connection_id: What the spec named, or `None` to take the
                organization's default.

        Raises:
            BadRequestError: If there is nothing to resolve to, the connection is
                switched off, or its credential is gone. All three are states a
                deployment can arrive at *after* an agent was published - a key
                rotated away, a host retired - so each says which, rather than
                failing as one generic error inside somebody's conversation.
        """
        row = await self._row_for(ctx, connection_id)
        if not row.is_active:
            raise BadRequestError(
                message=(
                    f"The sandbox connection '{row.name}' is switched off, so this "
                    "agent has nowhere to keep files."
                ),
                details={"connection_id": str(row.id)},
            )
        if row.secret_id is None:
            raise BadRequestError(
                message=(
                    f"The sandbox connection '{row.name}' has no credential. Its key "
                    "was removed from the vault; re-attach one."
                ),
                details={"connection_id": str(row.id)},
            )

        secrets = await self.secrets.resolve_for_bindings(ctx, [row.secret_id])
        secret = secrets.get(row.secret_id)
        if not isinstance(secret, ApiKeySecret):
            raise BadRequestError(
                message=(
                    f"The credential for '{row.name}' is not an API key, so it cannot "
                    "authenticate a sandbox service."
                ),
                details={"connection_id": str(row.id)},
            )
        return ResolvedConnection(row=row, token=secret.api_key.get_secret_value())

    async def _row_for(self, ctx: AuthContext, connection_id: UUID | None) -> SandboxConnection:
        if connection_id is not None:
            return await self._named(ctx, connection_id)
        row = await sandbox_connection_repo.get_default(
            self.db, organization_id=ctx.organization_id
        )
        if row is None:
            raise BadRequestError(
                message=(
                    "This organization has no sandbox connection, so an agent cannot be "
                    "given a container-backed workspace. Register one, or use the "
                    "'state' workspace, which needs nothing."
                ),
                details={"connection_id": None},
            )
        return row

    async def _named(self, ctx: AuthContext, connection_id: UUID) -> SandboxConnection:
        row = await sandbox_connection_repo.get(
            self.db, connection_id, organization_id=ctx.organization_id
        )
        if row is None:
            raise BadRequestError(
                message=(
                    "The sandbox connection this agent names no longer exists. Pick "
                    "another in the Builder, or republish against the default."
                ),
                details={"connection_id": str(connection_id)},
            )
        return row

    async def policy(self, ctx: AuthContext, connection_id: UUID) -> dict[str, Any]:
        """What the service allows, read from the service itself.

        Proxied rather than stored. The runtime allowlist and the ceilings behind
        each alias are `sandboxd`'s own configuration, read from its environment
        where it starts - so a copy here would be a second answer that disagrees
        the first time somebody restarts it with a different limit. The Builder
        needs the live one anyway: an alias this returns is an alias the service
        will accept, which is the point of asking.

        Raises:
            BadRequestError: If the service cannot be reached or refuses the
                token. Distinguished from an empty allowlist on purpose - "no
                runtimes" and "wrong credential" are different problems and only
                one of them is fixed in this form.
        """
        resolved = await self.resolve(ctx, connection_id)
        if resolved.kind != "docker":
            # Daytona publishes no policy of its own; what it allows is an
            # account setting on their side.
            return {"runtimes": [], "kind": resolved.kind}

        payload = await self._read(resolved, "/policy", connection_id)
        payload["kind"] = resolved.kind
        return payload

    async def sessions(
        self, ctx: AuthContext, connection_id: UUID, *, usage: bool = False
    ) -> dict[str, Any]:
        """The sandboxes open on this connection, filtered to this organization.

        The filter is the whole reason this is not a straight proxy. One
        `sandboxd` serves every organization that registered a connection at its
        address, and `GET /sessions` answers with all of them - so forwarding the
        response would show one tenant another tenant's containers, their runtimes
        and their idle times. Sessions are matched on the `tenant` label this
        platform sets to the organization id when it opens one.

        Attribution comes from `agent_workspaces` rather than by decoding the
        session id. The id encodes the scope key, and parsing it back would make
        that format a schema - the first change to it would mislabel every row.
        The row already carries the agent and the conversation, so it is joined.

        Args:
            usage: Also sample memory and CPU. Off by default because the service
                pays a daemon round trip per sandbox for it.

        Raises:
            BadRequestError: If the service cannot be reached or refuses the
                credential.
        """
        resolved = await self.resolve(ctx, connection_id)
        if resolved.kind != "docker":
            # Daytona holds no sessions of ours to enumerate; what runs there is
            # visible in their own dashboard, on the account being billed.
            return {"sessions": [], "kind": resolved.kind}

        payload = await self._read(
            resolved, f"/sessions?usage={'true' if usage else 'false'}", connection_id
        )
        tenant = str(ctx.organization_id)
        mine = [
            session for session in payload.get("sessions", []) if session.get("tenant") == tenant
        ]
        payload["sessions"] = await self._attributed(ctx, mine)
        payload["kind"] = resolved.kind
        return payload

    async def session_events(
        self, ctx: AuthContext, connection_id: UUID, session_id: str, *, after: int = 0
    ) -> dict[str, Any]:
        """What has been done to one sandbox, newest entries last.

        The session's tenant is checked against the caller's organization before
        the log is fetched. A session id is guessable in principle - it is derived
        from ids somebody may hold - and this log names every path an agent read
        and every command it ran, which is a description of another tenant's work
        even though it deliberately carries no file contents or command output.

        `after` is the sequence number a watcher already has, so polling does not
        re-read the whole log.
        """
        resolved = await self.resolve(ctx, connection_id)
        if resolved.kind != "docker":
            return {"events": [], "latest_seq": 0}

        described = await self._read(resolved, f"/sessions/{session_id}", connection_id)
        if described.get("tenant") != str(ctx.organization_id):
            # "Not found", not "forbidden": a probeable id is how somebody maps
            # which sessions exist in the organizations they are not in.
            raise NotFoundError(
                message="Sandbox session not found",
                details={"session_id": session_id},
            )
        return await self._read(
            resolved, f"/sessions/{session_id}/events?after={after}", connection_id
        )

    async def _attributed(
        self, ctx: AuthContext, sessions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Name the agent and conversation behind each session, where we know it.

        A `run`-scoped session has no row by design - it is deleted the moment
        the run ends - so an unmatched session is normal rather than missing, and
        it keeps its id and nothing else.
        """
        if not sessions:
            return sessions
        rows = await agent_workspace_repo.list_for_organization(
            self.db, organization_id=ctx.organization_id
        )
        by_session = {row.session_id: row for row in rows if row.session_id}
        for session in sessions:
            row = by_session.get(session.get("session_id"))
            if row is None:
                continue
            session["agent_id"] = str(row.agent_id)
            session["conversation_id"] = (
                None if row.conversation_id is None else str(row.conversation_id)
            )
            session["scope"] = row.scope
        return sessions

    async def _read(
        self, resolved: ResolvedConnection, path: str, connection_id: UUID
    ) -> dict[str, Any]:
        """One authenticated GET against a connection's service.

        Shared by every read here so the three failures a browser has to be able
        to tell apart - unreachable, wrong credential, and anything else - are
        described the same way once rather than three times differently.
        """
        import httpx

        base = (resolved.row.base_url or "").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{base}{path}", headers={"X-Sandbox-Token": resolved.token}
                )
        except Exception as exc:
            raise BadRequestError(
                message=f"The sandbox service at {base} did not answer",
                details={"connection_id": str(connection_id)},
            ) from exc

        if response.status_code == 401:
            raise BadRequestError(
                message="The sandbox service refused this connection's credential",
                details={"connection_id": str(connection_id)},
            )
        if response.status_code == 404:
            raise NotFoundError(
                message="Sandbox session not found",
                details={"connection_id": str(connection_id)},
            )
        if response.status_code != 200:
            raise BadRequestError(
                message=f"The sandbox service answered {response.status_code}",
                details={"connection_id": str(connection_id)},
            )
        payload: dict[str, Any] = response.json()
        return payload
