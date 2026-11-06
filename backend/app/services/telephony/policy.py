"""Phone authority: endpoint generation, member opt-in, quiet hours and spend admission."""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import current_impersonator, record_audit
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError, RateLimitError
from app.core.permissions import AuthContext, Perm
from app.db.locks import LockScope, hold_subject
from app.db.models.agent_embed import AgentEmbed
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.telephony import PhoneContact, PhoneEndpoint
from app.repositories import agent_embed_repo, channel_bot_repo, channel_identity_repo, user_repo
from app.repositories import telephony as repo
from app.schemas.telephony import (
    PhoneChoice,
    PhoneContactConfig,
    PhoneContactRead,
    PhoneEndpointConfig,
    PhoneEndpointRead,
    PhoneSettingsRead,
)
from app.services.access import acting_member
from app.services.agent_registry import AgentRegistryService
from app.services.telephony.provider import NUMBER, PhoneCredentials, credentials, url


def quiet_now(contact: PhoneContact, now: datetime) -> bool:
    hour = now.astimezone(ZoneInfo(contact.timezone)).hour
    start, end = contact.quiet_start_hour, contact.quiet_end_hour
    return start <= hour < end if start < end else hour >= start or hour < end


def contact_fingerprint(contact: PhoneContact) -> str:
    values = PhoneContactConfig.model_validate(
        contact, from_attributes=True
    ).model_dump_json() + str(contact.identity_generation)
    return hashlib.sha256(values.encode()).hexdigest()


def endpoint_fingerprint(endpoint: PhoneEndpoint, bot: ChannelBot) -> str:
    return hashlib.sha256(
        f"{endpoint.generation}:{endpoint.bot_generation}:{bot.authorization_generation}:{bot.is_active}".encode()
    ).hexdigest()


def _human(ctx: AuthContext) -> None:
    if (
        ctx.user_id is None
        or ctx.api_key_id is not None
        or ctx.routine_id is not None
        or ctx.fired_as_creator is not None
        or ctx.subject_is_publisher_fallback
        or current_impersonator() is not None
    ):
        raise AuthorizationError(message="Change phone consent from your own console session")


def mask(number: str) -> str:
    return "••••" + number[-4:]


class PhonePolicyService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def identity(self, identity_id: UUID, user_id: UUID) -> ChannelIdentity:
        from app.services.channels.router import ChannelMessageRouter

        identity = await channel_identity_repo.get_by_id(self.db, identity_id, fresh=True)
        if (
            identity is None
            or identity.user_id != user_id
            or identity.platform != "sms"
            or not identity.is_active
            or not NUMBER.fullmatch(identity.platform_user_id)
            or ChannelMessageRouter._sms_link_lapsed("sms", identity)
        ):
            raise AuthorizationError(
                message="Link and verify your SMS number again before allowing phone calls"
            )
        return identity

    async def contact_number(self, contact: PhoneContact) -> str:
        if await acting_member(self.db, contact.organization_id, str(contact.user_id)) is None:
            raise AuthorizationError(message="The phone contact is no longer an active member")
        identity = await self.identity(contact.identity_id, contact.user_id)
        if identity.authorization_generation != contact.identity_generation:
            raise AuthorizationError(
                message="This phone number was linked again; review the call consent"
            )
        return identity.platform_user_id

    async def available_contact(
        self, contact: PhoneContact, *, mode: str, reserved_call_id: UUID | None = None
    ) -> str:
        number = await self.contact_number(contact)
        allowed = (
            contact.allow_reports
            if mode == "report"
            else contact.allow_transfers
            if mode == "transfer"
            else contact.allow_calls
        )
        if not allowed:
            raise AuthorizationError(
                message="The contact has not opted into this kind of phone call"
            )
        if quiet_now(contact, datetime.now(UTC)):
            raise AuthorizationError(message="The contact's quiet hours are active")
        if (
            await repo.contact_calls_today(self.db, contact.id, exclude=reserved_call_id)
            >= contact.calls_per_day
        ):
            raise RateLimitError(message="The contact's daily phone call limit is reached")
        return number

    async def set_contact(self, ctx: AuthContext, data: PhoneContactConfig) -> PhoneContactRead:
        _human(ctx)
        await hold_subject(self.db, LockScope.PERSONAL_DATA_PER_USER, ctx.subject_id)
        await hold_subject(self.db, LockScope.PHONE_CALLS_PER_ORG, ctx.organization_id)
        identity = await self.identity(data.identity_id, ctx.subject_id)
        row = await repo.contact(
            self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id
        )
        if row is None:
            row = PhoneContact(
                organization_id=ctx.organization_id,
                user_id=ctx.subject_id,
                identity_id=identity.id,
                identity_generation=identity.authorization_generation,
            )
        row.identity_generation = identity.authorization_generation
        row.identity_id = data.identity_id
        row.allow_calls = data.allow_calls
        row.allow_reports = data.allow_reports
        row.allow_transfers = data.allow_transfers
        for agent_id in data.agent_ids:
            await AgentRegistryService(self.db).get(ctx, agent_id, perm=Perm.AGENTS_RUN)
        row.agent_ids = [str(value) for value in data.agent_ids]
        row.allow_important = data.allow_important
        row.importance_instructions = data.importance_instructions.strip()
        row.escalation_delay_seconds = data.escalation_delay_seconds
        row.report_language = data.report_language
        row.timezone = data.timezone
        row.quiet_start_hour = data.quiet_start_hour
        row.quiet_end_hour = data.quiet_end_hour
        row.calls_per_day = data.calls_per_day
        await repo.save(self.db, row)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="phone.consent_updated",
            target_type="phone_contact",
            target_id=str(row.id),
            details={
                "calls": row.allow_calls,
                "reports": row.allow_reports,
                "transfers": row.allow_transfers,
            },
        )
        return PhoneContactRead(
            **data.model_dump(), id=row.id, masked_number=mask(identity.platform_user_id)
        )

    async def public_embed(
        self, ctx: AuthContext, embed_id: UUID, *, editing: bool = False
    ) -> AgentEmbed:
        embed = await agent_embed_repo.get(self.db, embed_id, organization_id=ctx.organization_id)
        if (
            embed is None
            or not embed.is_active
            or embed.auth_mode != "public"
            or embed.kind not in {"widget", "page"}
            or embed.config.get("voice_conversation") is not True
        ):
            raise BadRequestError(
                message="Choose an active public voice page or widget for inbound calls"
            )
        agent = await AgentRegistryService(self.db).get(
            ctx, embed.agent_id, perm=Perm.AGENTS_EDIT if editing else Perm.AGENTS_RUN
        )
        from app.services.voice.settings import VoiceSettingsService

        if not (
            await VoiceSettingsService(self.db).readiness(
                organization_id=ctx.organization_id, agent=agent
            )
        ).available:
            raise BadRequestError(
                message="The public exposure's published agent is not ready for voice calls"
            )
        return embed

    async def configure(
        self, ctx: AuthContext, bot_id: UUID, data: PhoneEndpointConfig
    ) -> PhoneEndpointRead:
        _human(ctx)
        if not ctx.has(Perm.CHANNELS_MANAGE):
            raise AuthorizationError(message="Managing telephone routing requires channels:manage")
        await hold_subject(self.db, LockScope.PHONE_CALLS_PER_ORG, ctx.organization_id)
        bot = await channel_bot_repo.get_for_org(
            self.db, bot_id, organization_id=ctx.organization_id, for_update=True
        )
        if bot is None or bot.platform != "sms":
            raise NotFoundError(message="Twilio SMS bot not found")
        credentials(bot)
        if data.enabled:
            url("/")
        if data.inbound_embed_id is not None:
            await self.public_embed(ctx, data.inbound_embed_id, editing=True)
        for identifier in data.transfer_contact_ids:
            contact = await repo.contact_by_id(
                self.db, identifier, organization_id=ctx.organization_id
            )
            if contact is None or not contact.allow_transfers:
                raise BadRequestError(
                    message="Each transfer target must explicitly opt into phone transfers"
                )
            await self.contact_number(contact)
        row = await repo.endpoint_for_bot(self.db, bot.id, organization_id=ctx.organization_id)
        if row is None:
            row = PhoneEndpoint(
                organization_id=ctx.organization_id,
                bot_id=bot.id,
                bot_generation=bot.authorization_generation,
            )
        row.bot_generation = bot.authorization_generation
        row.generation = uuid4()
        row.enabled = data.enabled
        row.inbound_embed_id = data.inbound_embed_id
        row.max_call_seconds = data.max_call_seconds
        row.calls_per_hour = data.calls_per_hour
        row.calls_per_day = data.calls_per_day
        row.max_concurrent = data.max_concurrent
        row.daily_budget_usd = data.daily_budget_usd
        row.price_per_minute_usd = data.price_per_minute_usd
        row.transfer_contact_ids = [str(identifier) for identifier in data.transfer_contact_ids]
        await repo.save(self.db, row)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="phone.endpoint_configured",
            target_type="phone_endpoint",
            target_id=str(row.id),
            details={
                "enabled": row.enabled,
                "inbound_embed_id": str(row.inbound_embed_id) if row.inbound_embed_id else None,
            },
        )
        return self.read_endpoint(row, bot)

    @staticmethod
    def read_endpoint(row: PhoneEndpoint, bot: ChannelBot) -> PhoneEndpointRead:
        return PhoneEndpointRead(
            **PhoneEndpointConfig.model_validate(row, from_attributes=True).model_dump(),
            id=row.id,
            bot_id=bot.id,
            bot_name=bot.name,
            inbound_url=url(f"/inbound/{row.id}"),
            status_url=url(f"/inbound-status/{row.id}"),
        )

    async def load_endpoint(
        self, endpoint_id: UUID, *, organization_id: UUID | None = None, lock: bool = False
    ) -> tuple[PhoneEndpoint, ChannelBot, PhoneCredentials]:
        row = await repo.endpoint(self.db, endpoint_id, organization_id=organization_id, lock=lock)
        if row is None or not row.enabled:
            raise NotFoundError(message="Telephone routing is unavailable")
        bot = await channel_bot_repo.get_for_org(
            self.db, row.bot_id, organization_id=row.organization_id
        )
        if (
            bot is None
            or not bot.is_active
            or bot.platform != "sms"
            or row.bot_generation != bot.authorization_generation
        ):
            raise AuthorizationError(
                message="The telephone account changed; review its routing configuration"
            )
        return row, bot, credentials(bot)

    async def admit_budget(self, endpoint: PhoneEndpoint) -> Decimal:
        hourly, daily, active, cost = await repo.allowance(self.db, endpoint.id)
        legs = 2 if endpoint.transfer_contact_ids else 1
        worst = (
            endpoint.price_per_minute_usd * Decimal((endpoint.max_call_seconds + 59) // 60) * legs
        ).quantize(Decimal("0.000001"))
        if (
            hourly >= endpoint.calls_per_hour
            or daily >= endpoint.calls_per_day
            or active >= endpoint.max_concurrent
        ):
            raise RateLimitError(message="The telephone rate or concurrent call limit is reached")
        if cost + worst > endpoint.daily_budget_usd:
            raise RateLimitError(message="The telephone budget cannot cover this call's worst case")
        return worst

    async def settings(self, ctx: AuthContext) -> PhoneSettingsRead:
        _human(ctx)
        identities = []
        for identity in await channel_identity_repo.list_for_user(self.db, user_id=ctx.subject_id):
            if identity.platform == "sms" and identity.is_active:
                identities.append(
                    PhoneChoice(id=identity.id, label=mask(identity.platform_user_id))
                )
        own = await repo.contact(
            self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id
        )
        contact = None
        if own is not None:
            identity = await channel_identity_repo.get_by_id(self.db, own.identity_id)
            if identity is not None:
                contact = PhoneContactRead(
                    **PhoneContactConfig.model_validate(own, from_attributes=True).model_dump(),
                    id=own.id,
                    masked_number=mask(identity.platform_user_id),
                )
        call_endpoints = []
        for route in await repo.endpoints(self.db, ctx.organization_id):
            bot = await channel_bot_repo.get_for_org(
                self.db, route.bot_id, organization_id=ctx.organization_id
            )
            if (
                route.enabled
                and bot is not None
                and bot.is_active
                and bot.authorization_generation == route.bot_generation
            ):
                call_endpoints.append(PhoneChoice(id=route.id, label=bot.name))
        endpoints = []
        bots = []
        embeds = []
        targets = []
        if ctx.has(Perm.CHANNELS_MANAGE):
            for bot in await channel_bot_repo.list_for_org(
                self.db, organization_id=ctx.organization_id, limit=100
            ):
                if bot.platform == "sms":
                    bots.append(PhoneChoice(id=bot.id, label=bot.name))
            for row in await repo.endpoints(self.db, ctx.organization_id):
                bot = await channel_bot_repo.get_for_org(
                    self.db, row.bot_id, organization_id=ctx.organization_id
                )
                if bot is not None:
                    endpoints.append(self.read_endpoint(row, bot))
            for embed in await repo.public_embeds(self.db, ctx.organization_id):
                if embed.config.get("voice_conversation") is not True:
                    continue
                try:
                    await AgentRegistryService(self.db).get(
                        ctx, embed.agent_id, perm=Perm.AGENTS_EDIT
                    )
                except AuthorizationError, NotFoundError:
                    continue
                embeds.append(PhoneChoice(id=embed.id, label=embed.name))
            for target in await repo.transfer_contacts(self.db, ctx.organization_id):
                member = await acting_member(self.db, ctx.organization_id, str(target.user_id))
                person = await user_repo.get_by_id(self.db, target.user_id)
                if member is not None and person is not None:
                    targets.append(
                        PhoneChoice(id=target.id, label=person.full_name or "Phone contact")
                    )
        return PhoneSettingsRead(
            endpoints=endpoints,
            contact=contact,
            sms_identities=identities,
            sms_bots=bots,
            public_voice_embeds=embeds,
            transfer_contacts=targets,
            call_endpoints=call_endpoints,
        )
