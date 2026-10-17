"""Registering other vendors' agents so this organization's agents can delegate to them (#2092).

A registration is the remote agent's card, read and validated now, its endpoint,
and optionally a vault secret sent as its bearer token. Registering one is an
author's decision - it decides where an agent may send the organization's data -
so it takes `agents:edit`; reading the list takes `agents:view`, which is what
picking one as a delegate needs.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
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


def read(agent: ExternalAgent) -> ExternalAgentRead:
    skills = agent.card.get("skills", []) if isinstance(agent.card, dict) else []
    return ExternalAgentRead(
        id=agent.id,
        slug=agent.slug,
        name=agent.name,
        description=agent.description,
        card_url=agent.card_url,
        endpoint_url=agent.endpoint_url,
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
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


class ExternalAgentService:
    """Remote A2A agents, registered per organization."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(self, ctx: AuthContext) -> ExternalAgentList:
        rows = await external_agent_repo.list_for_org(self.db, organization_id=ctx.organization_id)
        return ExternalAgentList(items=[read(row) for row in rows])

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
        agent = await external_agent_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            slug=slug,
            name=card.name[:128],
            description=card.description or "",
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
        return read(agent)

    async def refresh(self, ctx: AuthContext, agent_id: UUID) -> ExternalAgentRead:
        """Read the card again - a remote agent changes on its own side."""
        agent = await self._get(ctx, agent_id)
        card = await self._card(agent.card_url, typed=False)
        updated = await external_agent_repo.update(
            self.db,
            agent=agent,
            update_data={
                "name": card.name[:128],
                "description": card.description or "",
                "endpoint_url": card.url,
                "card": _stored(card),
            },
        )
        return read(updated)

    async def delete(self, ctx: AuthContext, agent_id: UUID) -> None:
        """Remove a registration. An agent still delegating to it is refused at its next run."""
        agent = await self._get(ctx, agent_id)
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


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).hostname or ""
