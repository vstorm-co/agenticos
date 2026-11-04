"""A line that answers people who never linked an account.

A WhatsApp bot can answer a customer in a private chat with no account of
theirs. That is one key in the bot's access policy, read here so the router, the
bot service and the console agree on what it means, and it comes with a rule the
rest of the platform holds a run to: such a run spends under a ceiling or not at
all.

The ceiling is the same pair of caps the runner checks before it opens a run with
no member behind it - the served agent's own monthly budget and the
organization's monthly cap. Whichever is set is enough; with neither, nothing
stops the spend.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, OrgMcpServerRef
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.db.models.agent_exposure import AgentExposure
from app.db.models.channel_bot import ChannelBot
from app.repositories import (
    agent_environment_repo,
    agent_exposure_repo,
    agent_repo,
    context_repo,
    knowledge_base_repo,
    mcp_connection_repo,
    organization_repo,
    skill_repo,
    virtual_table_repo,
)
from app.schemas.channel_bot import (
    PublicLineKind,
    PublicLineReach,
    PublicLineRead,
    PublicLineRefused,
    PublicLineTableGrant,
    PublicLineVoice,
)
from app.services.channels.base import DEFAULT_ACCESS_POLICY

PLATFORMS_THAT_ANSWER_STRANGERS = frozenset({"whatsapp"})
"""Where a customer with no account can be answered at all.

A customer there is a number or a business-scoped id the platform vouches for, and the
platform's own terms are what make answering one reasonable. Everywhere else a chat
account with no linked person is asked to link.
"""


def parse_policy(stored: object) -> dict[str, Any]:
    """A bot's stored access policy as a dict, whether it was stored as one or as JSON text.

    Anything else - no policy, or a value that is not one - is no policy.
    """
    if isinstance(stored, str):
        return json.loads(stored) if stored else {}
    return dict(stored) if isinstance(stored, Mapping) else {}


def answers_unlinked_direct(policy: Mapping[str, Any]) -> bool:
    """Whether a private chat from somebody with no linked account is answered.

    True only when the switch is a real `True`, the mode is not `jwt_linked` and
    `require_link` is off. The second and third are the operator's way of saying a
    link is wanted, and they win: a policy that carries both is a policy that asks
    for a link. Read from the stored dict, so a string `"true"` or a policy saved
    before the key existed is a closed line.
    """
    return (
        policy.get("answer_unlinked_direct") is True
        and policy.get("mode") != "jwt_linked"
        and not bool(policy.get("require_link", False))
    )


def answers_unlinked_on(platform: str, stored_policy: object) -> bool:
    """Whether a bot of `platform` with this stored policy answers people with no account.

    The one reader the router and the bot service share: the policy as the row holds
    it, on a platform that can take it.
    """
    return platform in PLATFORMS_THAT_ANSWER_STRANGERS and answers_unlinked_direct(
        parse_policy(stored_policy)
    )


def bot_answers_unlinked_direct(bot: ChannelBot) -> bool:
    """Whether this bot answers a private chat from somebody with no linked account."""
    return answers_unlinked_on(bot.platform, bot.access_policy)


@dataclass(frozen=True)
class Ceiling:
    """What bounds the spend of a run with no member behind it."""

    agent_monthly_usd: Decimal | None
    organization_monthly_usd: Decimal | None

    @property
    def exists(self) -> bool:
        """Whether either cap is set."""
        return self.agent_monthly_usd is not None or self.organization_monthly_usd is not None


async def _served_version_id(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID, environment_id: UUID | None
) -> UUID | None:
    """The version a binding of this agent to this environment answers with, if any.

    The environment decides it, and with none named it is the agent's current one -
    the version a run on such a binding would be resolved to. `None` when there is
    nothing published to answer.
    """
    agent = await agent_repo.get(db, agent_id, organization_id=organization_id)
    if agent is None:
        return None
    if environment_id is None:
        return agent.current_version_id
    environment = await agent_environment_repo.get(
        db, environment_id, organization_id=organization_id
    )
    if environment is None or environment.agent_id != agent.id:
        return None
    return environment.version_id


async def _spec_of_version(
    db: AsyncSession, *, organization_id: UUID, version_id: UUID | None
) -> AgentSpec | None:
    if version_id is None:
        return None
    version = await agent_repo.get_version(db, version_id, organization_id=organization_id)
    return None if version is None else AgentSpec.model_validate(version.spec)


async def spec_served_by(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID, environment_id: UUID | None
) -> AgentSpec | None:
    """The spec a binding of this agent to this environment answers with.

    Read inside the organization and without a caller to check: this decides
    whether a line may be opened, not who may run the agent.
    """
    version_id = await _served_version_id(
        db, organization_id=organization_id, agent_id=agent_id, environment_id=environment_id
    )
    return await _spec_of_version(db, organization_id=organization_id, version_id=version_id)


async def served_spec(db: AsyncSession, exposure: AgentExposure) -> AgentSpec | None:
    """The spec an existing binding answers with, or `None` when nothing is published."""
    return await spec_served_by(
        db,
        organization_id=exposure.organization_id,
        agent_id=exposure.agent_id,
        environment_id=exposure.environment_id,
    )


async def bot_served_spec(db: AsyncSession, bot_id: UUID) -> AgentSpec | None:
    """The spec of the agent a bot is bound to, active or paused, or `None` with no binding.

    A paused binding still counts: resuming it is a click away, so a line that
    answers strangers is judged against the agent it will answer with then.
    """
    binding = await agent_exposure_repo.bound_to_bot(db, channel_bot_id=bot_id)
    return None if binding is None else await served_spec(db, binding)


async def ceiling_for(
    db: AsyncSession, *, organization_id: UUID, spec: AgentSpec | None
) -> Ceiling:
    """The caps that would bound a run of `spec` in the organization."""
    organization = await organization_repo.get_by_id(db, organization_id)
    budget = None if spec is None or spec.budget is None else spec.budget.monthly_usd
    return Ceiling(
        agent_monthly_usd=None if budget is None else Decimal(str(budget)),
        organization_monthly_usd=None if organization is None else organization.monthly_budget_usd,
    )


async def bot_ceiling(db: AsyncSession, bot: ChannelBot) -> Ceiling:
    """The caps that bound a run on this bot's line: its served agent's and the organization's."""
    return await ceiling_for(
        db, organization_id=bot.organization_id, spec=await bot_served_spec(db, bot.id)
    )


async def refuse_without_ceiling(
    db: AsyncSession,
    *,
    organization_id: UUID,
    spec: AgentSpec | None,
    channel_bot_id: UUID | None,
) -> None:
    """Refuse when a line that answers strangers would spend with no ceiling.

    Raises:
        BadRequestError: When neither the agent's monthly budget nor the
            organization's monthly cap is set.
    """
    if (await ceiling_for(db, organization_id=organization_id, spec=spec)).exists:
        return
    raise BadRequestError(
        message=(
            "A bot that answers people who have not linked an account needs a spending limit. "
            "Give the agent it serves a monthly budget, or give the organization a monthly cap."
        ),
        details={"channel_bot_id": None if channel_bot_id is None else str(channel_bot_id)},
    )


async def served_versions(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID
) -> dict[UUID, UUID | None]:
    """The version each public-line binding of this agent serves now, by binding id.

    Taken before a change to the agent, so `refuse_unbounded_bindings` can tell the
    bindings the change moves from the ones it leaves alone. Empty when the agent
    is on no bot that answers strangers.
    """
    return {
        exposure.id: await _served_version_id(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            environment_id=exposure.environment_id,
        )
        for exposure, bot in await agent_exposure_repo.list_with_bot_for_agent(
            db, agent_id=agent_id, organization_id=organization_id
        )
        if bot_answers_unlinked_direct(bot)
    }


async def refuse_unbounded_bindings(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    served_before: Mapping[UUID, UUID | None],
    excluding_environment_id: UUID | None = None,
) -> None:
    """Refuse a change to an agent that would leave a line answering strangers with no ceiling.

    `served_before` is `served_versions` taken before the change. Every binding of
    the agent on a bot whose line answers strangers, paused ones included, is
    judged by the version it serves once the change is in place - but only when
    that is not the version it served before. A binding the change does not move is
    left alone: whatever state it was already in, this change is not what put it
    there. Call it after the change is written, inside the transaction that a
    refusal rolls back. `excluding_environment_id` judges the bindings on that
    environment as if they named none: what they fall back to when it is deleted.

    Raises:
        BadRequestError: For the first moved binding with neither an agent budget
            nor an organization cap.
    """
    for exposure, bot in await agent_exposure_repo.list_with_bot_for_agent(
        db, agent_id=agent_id, organization_id=organization_id
    ):
        if not bot_answers_unlinked_direct(bot):
            continue
        version_id = await _served_version_id(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            environment_id=(
                None
                if exposure.environment_id == excluding_environment_id
                else exposure.environment_id
            ),
        )
        if served_before.get(exposure.id) == version_id:
            continue
        await refuse_without_ceiling(
            db,
            organization_id=organization_id,
            spec=await _spec_of_version(db, organization_id=organization_id, version_id=version_id),
            channel_bot_id=bot.id,
        )


STRANGER_RECORDING_MAX_BYTES = 2 * 1024 * 1024
"""The largest voice note taken from somebody with no account: about fifteen minutes of a WhatsApp voice note."""

_CAPABILITY_KINDS: dict[PublicLineKind, tuple[str, ...]] = {
    "web": ("web_fetch", "web_research"),
    "code": ("code_execution", "sandbox", "coding_agent"),
    "generation": ("image_generation", "video_generation", "text_to_speech", "visuals"),
}

_REFUSED: tuple[PublicLineRefused, ...] = (
    "memory",
    "conversation_search",
    "artifacts",
    "workflows",
    "background_tasks",
    "platform_mcp",
)


def _as_decimal(value: Decimal | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


async def _table_reach(
    db: AsyncSession, spec: AgentSpec, *, organization_id: UUID
) -> PublicLineReach | None:
    """The tables the spec grants, with what may be done in each, or `None` when it grants none."""
    from app.agents.capabilities.virtual_tables import VirtualTablesConfig

    names: list[str] = []
    grants: list[PublicLineTableGrant] = []
    creates = False
    for binding in spec.capabilities:
        if binding.id != "virtual_tables" or not binding.enabled:
            continue
        config = VirtualTablesConfig.model_validate(binding.config)
        creates = creates or config.allow_create
        for grant in config.tables:
            table = await virtual_table_repo.get_table(
                db, grant.table_id, organization_id=organization_id
            )
            if table is None:
                continue
            names.append(table.name)
            grants.append(
                PublicLineTableGrant(
                    name=table.name, operations=[str(op) for op in grant.operations]
                )
            )
    if not names and not creates:
        return None
    return PublicLineReach(kind="tables", names=names, grants=grants, may_create=creates)


def _capability_reaches(spec: AgentSpec) -> list[PublicLineReach]:
    enabled = {binding.id for binding in spec.capabilities if binding.enabled}
    reaches = []
    for kind, ids in _CAPABILITY_KINDS.items():
        found = [capability for capability in ids if capability in enabled]
        if found:
            reaches.append(
                PublicLineReach(
                    kind=kind,
                    names=found,
                    detail="outside_ledger" if kind in ("web", "code") else None,
                )
            )
    return reaches


async def _named_reaches(
    db: AsyncSession, spec: AgentSpec, *, organization_id: UUID
) -> list[PublicLineReach]:
    """The references a spec holds to rows in the organization, each as the names of what it reaches."""
    collections = await knowledge_base_repo.get_by_ids(db, spec.collection_ids)
    contexts = await context_repo.get_many(db, spec.context_ids, organization_id=organization_id)
    skills = await skill_repo.get_many(db, spec.skill_ids, organization_id=organization_id)
    delegates = await agent_repo.get_many(
        db, [ref.agent_id for ref in spec.subagents], organization_id=organization_id
    )
    connections = await mcp_connection_repo.get_org_scoped_by_ids(
        db,
        connection_ids=[
            ref.connection_id for ref in spec.mcp_servers if isinstance(ref, OrgMcpServerRef)
        ],
        organization_id=organization_id,
    )
    named: list[tuple[PublicLineKind, list[str]]] = [
        (
            "knowledge",
            [kb.name for kb in collections.values() if kb.organization_id == organization_id],
        ),
        ("context", [file.name for file in contexts.values()]),
        ("skills", [skill.name for skill in skills.values()]),
    ]
    tables = await _table_reach(db, spec, organization_id=organization_id)
    reaches = [PublicLineReach(kind=kind, names=names) for kind, names in named if names]
    if tables is not None:
        reaches.append(tables)
    reaches.extend(_capability_reaches(spec))
    if delegates:
        reaches.append(
            PublicLineReach(kind="delegates", names=[agent.name for agent in delegates.values()])
        )
    if connections:
        reaches.append(
            PublicLineReach(kind="mcp", names=[conn.name for conn in connections.values()])
        )
    return reaches


async def reach_of(db: AsyncSession, bot: ChannelBot) -> PublicLineRead:
    """What this bot would answer a customer with no account with, and what bounds it.

    Read from the agent the bot is bound to, active or paused, and from the policy
    as stored. A bot with no binding reaches nothing yet; only the organization's
    cap can bound it.
    """
    organization_id = bot.organization_id
    binding = await agent_exposure_repo.bound_to_bot(db, channel_bot_id=bot.id)
    spec: AgentSpec | None = None
    agent_version: int | None = None
    if binding is not None:
        version_id = await _served_version_id(
            db,
            organization_id=organization_id,
            agent_id=binding.agent_id,
            environment_id=binding.environment_id,
        )
        version = (
            None
            if version_id is None
            else await agent_repo.get_version(db, version_id, organization_id=organization_id)
        )
        if version is not None:
            spec = AgentSpec.model_validate(version.spec)
            agent_version = version.version
    ceiling = await ceiling_for(db, organization_id=organization_id, spec=spec)
    policy = parse_policy(bot.access_policy)
    accepts_files = policy.get("accept_customer_files") is True
    reaches = (
        [] if spec is None else await _named_reaches(db, spec, organization_id=organization_id)
    )
    if accepts_files:
        reaches.append(PublicLineReach(kind="files", names=[]))
    voice: PublicLineVoice
    if not bot.transcribe_voice_notes:
        voice = "off"
    elif ceiling.organization_monthly_usd is None:
        voice = "refused_no_org_cap"
    else:
        voice = "on"
    return PublicLineRead(
        answers_unlinked=bot_answers_unlinked_direct(bot),
        agent_name=None if spec is None else spec.name,
        agent_version=agent_version,
        agent_monthly_usd=_as_decimal(ceiling.agent_monthly_usd),
        organization_monthly_usd=_as_decimal(ceiling.organization_monthly_usd),
        can_turn_on=ceiling.exists,
        accept_customer_files=accepts_files,
        voice=voice,
        rate_limit_rpm=int(policy.get("rate_limit_rpm", DEFAULT_ACCESS_POLICY["rate_limit_rpm"])),
        approval_expiry_hours=settings.APPROVAL_EXPIRY_HOURS,
        recording_max_mb=STRANGER_RECORDING_MAX_BYTES // (1024 * 1024),
        file_max_mb=settings.EMBED_MAX_UPLOAD_SIZE_MB,
        reaches=reaches,
        refused=list(_REFUSED),
    )
