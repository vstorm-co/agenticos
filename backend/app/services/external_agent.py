"""Registering other vendors' agents so this organization's agents can delegate to them (#2092).

A registration is the remote agent's card, read and validated now, its endpoint,
and optionally a vault secret sent as its bearer token. Registering one is an
author's decision - it decides where an agent may send the organization's data -
so it takes `agents:edit`; reading the list takes `agents:view`, which is what
picking one as a delegate needs.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm, Scope
from app.core.secret_kinds import SecretKind
from app.db.models.external_agent import ExternalAgent
from app.repositories import external_agent_repo
from app.schemas.a2a import AgentCard
from app.schemas.external_agent import (
    ExternalAgentCreate,
    ExternalAgentList,
    ExternalAgentRead,
    ExternalAgentSkill,
)
from app.services.a2a_client import A2AClientError, fetch_card
from app.services.agent_registry import slugify
from app.services.organization_secret import OrganizationSecretService

MAX_DESCRIPTION_CHARS = 1000
"""How much of a card's description is kept. It is the remote host's text, read
by every agent delegating to it as part of its own tools; a card is not where a
prompt's worth of instructions gets in."""


def read(agent: ExternalAgent, *, can_manage: bool) -> ExternalAgentRead:
    skills = agent.card.get("skills", []) if isinstance(agent.card, dict) else []
    return ExternalAgentRead(
        id=agent.id,
        slug=agent.slug,
        name=agent.name,
        description=agent.description,
        card_url=_without_query(agent.card_url),
        endpoint_url=_without_query(agent.endpoint_url),
        secret_id=agent.secret_id,
        skills=[
            ExternalAgentSkill(
                id=str(skill.get("id", "")),
                name=str(skill.get("name", "")),
                description=str(skill.get("description", "")),
            )
            for skill in skills
            if isinstance(skill, dict)
        ],
        can_manage=can_manage,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _described(card: AgentCard) -> str:
    return (card.description or "")[:MAX_DESCRIPTION_CHARS]


def _may_change(ctx: AuthContext, agent: ExternalAgent) -> bool:
    return agent.created_by_user_id == ctx.subject_id or (
        ctx.scope_for(Perm.AGENTS_EDIT) is Scope.ALL
    )


class ExternalAgentService:
    """Remote A2A agents, registered per organization."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(self, ctx: AuthContext) -> ExternalAgentList:
        rows = await external_agent_repo.list_for_org(self.db, organization_id=ctx.organization_id)
        return ExternalAgentList(
            items=[read(row, can_manage=_may_change(ctx, row)) for row in rows]
        )

    async def register(self, ctx: AuthContext, data: ExternalAgentCreate) -> ExternalAgentRead:
        """Read the card, check the secret, and keep the registration.

        Raises:
            BadRequestError: The card could not be read or is not a card.
            AlreadyExistsError: The handle is taken in this organization.
            NotFoundError: The secret is not one the caller may name.
        """
        card = await self._card(data.card_url, typed=True)
        slug = slugify(data.slug or card.name)
        if await external_agent_repo.get_by_slug(
            self.db, slug, organization_id=ctx.organization_id
        ):
            raise AlreadyExistsError(
                message=f"A remote agent called {slug} is already registered",
                details={"slug": slug},
            )
        if data.secret_id is not None:
            await OrganizationSecretService(self.db).get_usable(
                ctx, data.secret_id, kind=SecretKind.API_KEY
            )
            _refuse_cleartext(card, field="card_url")
        agent = await external_agent_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            slug=slug,
            name=card.name[:128],
            description=_described(card),
            card_url=data.card_url.strip(),
            endpoint_url=card.url,
            card=_stored(card),
            secret_id=data.secret_id,
            created_by_user_id=ctx.subject_id,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="external_agent.registered",
            target_type="external_agent",
            target_id=str(agent.id),
            details={"endpoint_host": _host(card.url)},
        )
        return read(agent, can_manage=True)

    async def refresh(self, ctx: AuthContext, agent_id: UUID) -> ExternalAgentRead:
        """Read the card again - a remote agent changes on its own side.

        A card that moves the agent to another host is audited as registering
        was: that host now receives the organization's requests and its key.
        """
        agent = await self._changeable(ctx, agent_id)
        # A refresh decides where the bound key is sent next, so whoever does it
        # must still be able to use that key - as registering it required.
        if agent.secret_id is not None:
            await OrganizationSecretService(self.db).get_usable(
                ctx, agent.secret_id, kind=SecretKind.API_KEY
            )
        card = await self._card(agent.card_url, typed=False)
        if agent.secret_id is not None:
            _refuse_cleartext(card, field=None)
        moved_from = _host(agent.endpoint_url)
        updated = await external_agent_repo.update(
            self.db,
            agent=agent,
            update_data={
                "name": card.name[:128],
                "description": _described(card),
                "endpoint_url": card.url,
                "card": _stored(card),
            },
        )
        if _host(card.url) != moved_from:
            await record_audit(
                self.db,
                actor_user_id=ctx.subject_id,
                organization_id=ctx.organization_id,
                action="external_agent.moved",
                target_type="external_agent",
                target_id=str(agent_id),
                details={"from_host": moved_from, "endpoint_host": _host(card.url)},
            )
        return read(updated, can_manage=True)

    async def delete(self, ctx: AuthContext, agent_id: UUID) -> None:
        """Remove a registration. An agent still delegating to it is refused at its next run."""
        agent = await self._changeable(ctx, agent_id)
        await external_agent_repo.delete(self.db, agent)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="external_agent.removed",
            target_type="external_agent",
            target_id=str(agent_id),
        )

    async def _get(self, ctx: AuthContext, agent_id: UUID) -> ExternalAgent:
        agent = await external_agent_repo.get(
            self.db, agent_id, organization_id=ctx.organization_id
        )
        if agent is None:
            raise NotFoundError(
                message="Remote agent not found", details={"external_agent_id": str(agent_id)}
            )
        return agent

    async def _changeable(self, ctx: AuthContext, agent_id: UUID) -> ExternalAgent:
        """A registration this caller may refresh or remove: their own, or any for
        somebody who edits every agent - every agent delegating to it depends on it.

        Raises:
            NotFoundError: If the organization has no such registration.
            AuthorizationError: If it is somebody else's and the caller edits only
                their own agents.
        """
        agent = await self._get(ctx, agent_id)
        if not _may_change(ctx, agent):
            raise AuthorizationError(
                message="Only whoever registered this remote agent, or an admin, may change it",
                details={"external_agent_id": str(agent_id)},
            )
        return agent

    @staticmethod
    async def _card(url: str, *, typed: bool) -> AgentCard:
        """The card at `url`, or a refusal saying why it could not be read.

        The address is never repeated in the refusal: a signed card URL carries
        its credential in the query, and `details` is logged. Named as the
        `card_url` field only when the caller typed it in this request.
        """
        try:
            return await fetch_card(url)
        except A2AClientError as unreadable:
            if typed:
                raise refused_field("card_url", str(unreadable)) from unreadable
            raise BadRequestError(message=str(unreadable)) from unreadable


def _stored(card: AgentCard) -> dict[str, Any]:
    return card.model_dump(by_alias=True, exclude_none=True, mode="json")


def _refuse_cleartext(card: AgentCard, *, field: str | None) -> None:
    """A key is sent only to an HTTPS endpoint - over HTTP, anyone on the path reads it.

    Raises:
        BadRequestError: The card's endpoint is plain HTTP; named as `field` when
            the caller typed the address in this request.
    """
    if urlsplit(card.url).scheme == "https":
        return
    message = "This agent's endpoint is not HTTPS, so a key cannot be sent to it"
    if field is None:
        raise BadRequestError(message=message, details={"endpoint_host": _host(card.url)})
    raise refused_field(field, message)


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""


def _without_query(url: str) -> str:
    """An address as anyone who lists it sees it: a signed one keeps its credential
    in the query or the userinfo, which only the server that calls it needs."""
    parts = urlsplit(url)
    # The netloc without any `user:password@` in front of it.
    host = parts.netloc.rpartition("@")[2]
    return urlunsplit((parts.scheme, host, parts.path, "", ""))
