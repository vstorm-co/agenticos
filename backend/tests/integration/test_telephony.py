"""Real SQL admission and provider-intent state, with no live telephone traffic."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError, RateLimitError
from app.core.permissions import AuthContext
from app.db.models.background_job import BackgroundJob
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.telephony import PhoneCall
from app.repositories import channel_bot_repo
from app.repositories import telephony as repo
from app.schemas.telephony import PhoneCallCreate, PhoneContactConfig, PhoneEndpointConfig
from app.services.channel_bot import seal_bot_token
from app.services.channels.sms import twilio_signature
from app.services.telephony.calls import PhoneCallService
from app.services.telephony.policy import PhonePolicyService
from app.services.telephony.provider import AcceptanceUnknown, PhoneCredentials, url
from app.services.telephony.runtime import dial, end_media, live_contact, reap, transfer
from app.services.telephony.webhooks import PhoneWebhookService
from tests.integration.workflow_run_support import seed_member

pytestmark = [pytest.mark.anyio, pytest.mark.security]
ACCOUNT = "AC" + "a" * 32
TOKEN = "test-phone-auth"
NUMBER = "+15550000000"
PERSON_NUMBER = "+15551111111"
SID = "CA" + "b" * 32


class FakePhone:
    def __init__(self, *, unknown: bool = False) -> None:
        self.unknown = unknown
        self.dials: list[str] = []
        self.stops: list[str] = []
        self.transfers: list[tuple[str, int]] = []
        self.caps: list[tuple[str, int]] = []

    async def dial(
        self,
        credentials: PhoneCredentials,
        *,
        number: str,
        twiml: str,
        callback: str,
        cap_seconds: int,
    ) -> str:
        self.dials.append(number)
        assert credentials.account == ACCOUNT and "<Say" in twiml and "status" in callback
        if self.unknown:
            raise AcceptanceUnknown(message="Unknown acceptance")
        return SID

    async def cap(self, credentials: PhoneCredentials, sid: str, seconds: int) -> None:
        self.caps.append((sid, seconds))

    async def transfer(
        self, credentials: PhoneCredentials, sid: str, *, number: str, seconds: int
    ) -> None:
        self.transfers.append((number, seconds))

    async def hangup(self, credentials: PhoneCredentials, sid: str) -> None:
        self.stops.append(sid)


async def setup(db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://phone.example")
    user, org = await seed_member(db)
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    sealed = seal_bot_token(f"{ACCOUNT}:{TOKEN}:{NUMBER}", organization_id=org.id)
    bot = await channel_bot_repo.create(
        db,
        organization_id=org.id,
        platform="sms",
        name="Telephone",
        token_encrypted=sealed.ciphertext,
        secret_key_version=sealed.key_version,
    )
    identity = ChannelIdentity(
        platform="sms", platform_user_id=PERSON_NUMBER, user_id=user.id, is_active=True
    )
    db.add(identity)
    await db.flush()
    hour = datetime.now(UTC).hour
    policy = PhonePolicyService(db)
    contact = await policy.set_contact(
        ctx,
        PhoneContactConfig(
            identity_id=identity.id,
            allow_calls=True,
            allow_reports=True,
            allow_transfers=True,
            quiet_start_hour=(hour + 2) % 24,
            quiet_end_hour=(hour + 3) % 24,
        ),
    )
    endpoint = await policy.configure(
        ctx,
        bot.id,
        PhoneEndpointConfig(
            enabled=True, price_per_minute_usd=Decimal("0.10"), transfer_contact_ids=[]
        ),
    )
    return ctx, bot, identity, contact, endpoint


async def report(
    db: AsyncSession,
    ctx: AuthContext,
    endpoint: UUID,
    *,
    key: UUID | None = None,
    text: str = "The report",
):
    return await PhoneCallService(db).create(
        ctx,
        PhoneCallCreate(
            request_key=key or uuid4(), endpoint_id=endpoint, mode="report", report=text
        ),
    )


def sessions(db: AsyncSession):
    factory = async_sessionmaker(db.bind, expire_on_commit=False)

    @asynccontextmanager
    async def open_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session
            await session.commit()

    return open_session


async def test_call_retry_reuses_the_intent_and_job_and_never_exposes_phone_or_report(
    db: AsyncSession, monkeypatch
):
    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    key = uuid4()
    one = await report(db, ctx, endpoint.id, key=key)
    two = await report(db, ctx, endpoint.id, key=key)
    assert one.id == two.id and one.status == "queued"
    assert PERSON_NUMBER not in one.model_dump_json() and "The report" not in one.model_dump_json()
    assert (
        await db.scalar(
            select(func.count())
            .select_from(PhoneCall)
            .where(PhoneCall.organization_id == ctx.organization_id)
        )
        == 1
    )
    jobs = list(
        await db.scalars(
            select(BackgroundJob).where(
                BackgroundJob.organization_id == ctx.organization_id,
                BackgroundJob.kind == "dial-phone",
            )
        )
    )
    assert len(jobs) == 1
    with pytest.raises(ConflictError):
        await report(db, ctx, endpoint.id, key=key, text="Another report")
    other, other_org = await seed_member(db)
    with pytest.raises(NotFoundError):
        await report(
            db,
            AuthContext(user_id=other.id, organization_id=other_org.id, role="owner"),
            endpoint.id,
        )


async def test_explicit_consent_quiet_hours_and_generation_are_enforced(
    db: AsyncSession, monkeypatch
):
    ctx, _, identity, contact, endpoint = await setup(db, monkeypatch)
    policy = PhonePolicyService(db)
    data = PhoneContactConfig.model_validate(contact.model_dump(exclude={"id", "masked_number"}))
    await policy.set_contact(ctx, data.model_copy(update={"allow_reports": False}))
    with pytest.raises(AuthorizationError):
        await report(db, ctx, endpoint.id)
    await policy.set_contact(
        ctx,
        data.model_copy(
            update={
                "quiet_start_hour": datetime.now(UTC).hour,
                "quiet_end_hour": (datetime.now(UTC).hour + 1) % 24,
            }
        ),
    )
    with pytest.raises(AuthorizationError):
        await report(db, ctx, endpoint.id)
    await policy.set_contact(ctx, data)
    identity.authorization_generation = uuid4()
    await db.flush()
    with pytest.raises(AuthorizationError):
        await report(db, ctx, endpoint.id)


async def test_whole_minutes_and_rate_limits_reserve_before_any_provider_effect(
    db: AsyncSession, monkeypatch
):
    ctx, bot, _, _, endpoint = await setup(db, monkeypatch)
    policy = PhonePolicyService(db)
    await policy.configure(
        ctx,
        bot.id,
        PhoneEndpointConfig(
            enabled=True,
            max_call_seconds=61,
            price_per_minute_usd=Decimal("0.10"),
            daily_budget_usd=Decimal("0.19"),
        ),
    )
    with pytest.raises(RateLimitError):
        await report(db, ctx, endpoint.id)
    await policy.configure(
        ctx,
        bot.id,
        PhoneEndpointConfig(enabled=True, calls_per_hour=1, price_per_minute_usd=Decimal("0.10")),
    )
    await report(db, ctx, endpoint.id)
    with pytest.raises(RateLimitError):
        await report(db, ctx, endpoint.id)


async def test_unknown_submission_never_redials_and_a_signed_callback_resolves_it(
    db: AsyncSession, monkeypatch
):
    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    call = await report(db, ctx, endpoint.id)
    await db.commit()
    factory = sessions(db)
    provider = FakePhone(unknown=True)
    await dial(call.id, provider=provider, sessions=factory)
    await dial(call.id, provider=provider, sessions=factory)
    assert provider.dials == [PERSON_NUMBER]
    async with factory() as fresh:
        row = await repo.call(fresh, call.id)
        assert row is not None and row.status == "unknown" and row.estimated_cost_usd > 0
        params = {
            "AccountSid": ACCOUNT,
            "CallSid": SID,
            "To": PERSON_NUMBER,
            "From": NUMBER,
            "CallStatus": "completed",
            "CallDuration": "61",
        }
        signature = twilio_signature(url(f"/status/{call.id}"), params, TOKEN)
        await PhoneWebhookService(fresh).status(call.id, urlencode(params).encode(), signature)
    async with factory() as fresh:
        row = await repo.call(fresh, call.id)
        assert row is not None and row.status == "completed" and row.provider_sid == SID
        assert row.estimated_cost_usd == Decimal("0.20")


async def test_revoked_queued_consent_cancels_before_dial_and_lost_origin_never_borrows_authority(
    db: AsyncSession, monkeypatch
):
    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    call = await report(db, ctx, endpoint.id)
    row = await repo.call(db, call.id)
    assert row is not None
    row.source_required = True
    row.source_run_id = None
    await db.flush()
    with pytest.raises(AuthorizationError):
        await live_contact(db, row)
    await db.commit()
    provider = FakePhone()
    await dial(call.id, provider=provider, sessions=sessions(db))
    assert provider.dials == []
    async with sessions(db)() as fresh:
        row = await repo.call(fresh, call.id)
        assert row is not None and row.status == "cancelled" and row.estimated_cost_usd == 0


async def test_transfer_keeps_remaining_cap_and_teardown_does_not_hang_up_transferred_leg(
    db: AsyncSession, monkeypatch
):
    ctx, bot, _, contact, endpoint = await setup(db, monkeypatch)
    await PhonePolicyService(db).configure(
        ctx,
        bot.id,
        PhoneEndpointConfig(
            enabled=True, price_per_minute_usd=Decimal("0.10"), transfer_contact_ids=[contact.id]
        ),
    )
    call = await report(db, ctx, endpoint.id)
    row = await repo.call(db, call.id)
    assert row is not None
    row.mode = "conversation"
    row.destination = None
    row.status = "active"
    row.provider_sid = SID
    row.stream_claimed_at = datetime.now(UTC) - timedelta(seconds=200)
    await db.commit()
    provider = FakePhone()
    await transfer(db, call.id, contact.id, ctx=ctx, provider=provider)
    assert len(provider.transfers) == 1 and 1 <= provider.transfers[0][1] <= 100
    await end_media(call.id, provider=provider, sessions=sessions(db))
    assert provider.stops == []
    with pytest.raises(ConflictError):
        await transfer(db, call.id, contact.id, ctx=ctx, provider=provider)


async def test_reaper_ends_a_report_after_contact_opt_out_without_waiting_for_time_cap(
    db: AsyncSession, monkeypatch
):
    ctx, _, _, contact, endpoint = await setup(db, monkeypatch)
    call = await report(db, ctx, endpoint.id)
    row = await repo.call(db, call.id)
    assert row is not None
    row.status = "ringing"
    row.provider_sid = SID
    policy = PhoneContactConfig.model_validate(contact.model_dump(exclude={"id", "masked_number"}))
    await PhonePolicyService(db).set_contact(
        ctx, policy.model_copy(update={"allow_reports": False})
    )
    await db.commit()
    provider = FakePhone()
    assert await reap(provider=provider, sessions=sessions(db)) >= 1
    assert provider.stops == [SID]


async def test_foreign_and_duplicate_webhook_fields_never_settle_a_receipt(
    db: AsyncSession, monkeypatch
):
    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    call = await report(db, ctx, endpoint.id)
    with pytest.raises(AuthorizationError):
        await PhoneWebhookService(db).status(call.id, b"CallSid=wrong", "forged")
    assert (await repo.call(db, call.id)).status == "queued"
    with pytest.raises(AuthorizationError):
        await PhonePolicyService(db).set_contact(
            replace(ctx, user_id=uuid4()), PhoneContactConfig(identity_id=uuid4())
        )


async def test_phone_consent_and_report_are_in_the_personal_export_without_credentials(
    db: AsyncSession, monkeypatch
):
    from app.services.personal_data import PersonalDataService

    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    call = await report(db, ctx, endpoint.id, text="Personal status report")
    exported = await PersonalDataService(db).export(ctx.subject_id, actor_user_id=ctx.subject_id)
    assert len(exported.phone_contacts) == 1
    assert (
        exported.phone_calls[0].id == call.id
        and exported.phone_calls[0].report == "Personal status report"
    )
    serialized = exported.model_dump_json()
    assert TOKEN not in serialized and ACCOUNT not in serialized


@pytest.mark.parametrize("receipt_known", [True, False])
async def test_inbound_stream_is_anonymous_and_receipt_replays_do_not_restart_it(
    db: AsyncSession, monkeypatch, receipt_known: bool
):
    import json
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import WebSocket, WebSocketDisconnect

    from app.agents.spec import AgentSpec, VoiceSpec
    from app.db.models.agent_embed import AgentEmbed
    from app.db.models.credential import ModelProfile
    from app.services import realtime_models
    from app.services.agent_registry import AgentRegistryService
    from app.services.telephony import runtime
    from app.services.telephony.provider import stream_nonce
    from tests.integration.test_workflow_agent_node import _profile

    ctx, bot, _, _, endpoint = await setup(db, monkeypatch)
    # Use a real published voice spec; the live model session alone is replaced.
    from app.db.models.organization import Organization

    org = await db.get(Organization, ctx.organization_id)
    assert org is not None
    await db.commit()
    model_id = await _profile(db.bind, org)
    profile = await db.get(ModelProfile, model_id)
    available = realtime_models.by_provider("openai")
    assert available is not None and profile is not None
    registry = AgentRegistryService(db)
    agent = await registry.create(
        ctx,
        AgentSpec(
            name="Public phone agent",
            model_profile_id=model_id,
            voice=VoiceSpec(
                provider="openai", model=available.models[0].id, secret_id=profile.secret_id
            ),
        ),
    )
    await registry.publish(ctx, agent.id)
    embed = AgentEmbed(
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        owner_user_id=ctx.user_id,
        name="Public support",
        kind="widget",
        public_key=uuid4().hex,
        auth_mode="public",
        is_active=True,
        allowed_origins=[],
        config={"kind": "widget", "voice_conversation": True},
    )
    db.add(embed)
    await db.flush()
    await PhonePolicyService(db).configure(
        ctx,
        bot.id,
        PhoneEndpointConfig(
            enabled=True, inbound_embed_id=embed.id, price_per_minute_usd=Decimal("0.10")
        ),
    )
    params = {"AccountSid": ACCOUNT, "CallSid": SID, "To": NUMBER, "From": PERSON_NUMBER}
    provider = FakePhone()
    service = PhoneWebhookService(db, provider=provider)
    signature = twilio_signature(url(f"/inbound/{endpoint.id}"), params, TOKEN)
    xml = await service.inbound(endpoint.id, urlencode(params).encode(), signature)
    call = await repo.call_by_sid(db, endpoint.id, SID)
    assert call is not None and call.user_id is None and "Stream" in xml
    assert provider.caps and 1 <= provider.caps[0][1] <= 300
    _, _, auth = await PhonePolicyService(db).load_endpoint(endpoint.id)
    nonce = stream_nonce(auth, call)
    call_id = call.id
    if not receipt_known:
        call.provider_sid = None
        call.status = "unknown"
    await db.commit()
    raw = MagicMock(spec=WebSocket)
    raw.headers = {
        "x-twilio-signature": twilio_signature(url(f"/media/{call_id}", websocket=True), {}, TOKEN)
    }
    raw.accept = AsyncMock()
    raw.close = AsyncMock()
    raw.send_json = AsyncMock()
    raw.receive_text = AsyncMock(
        return_value=json.dumps(
            {
                "event": "start",
                "streamSid": "MZ" + "c" * 32,
                "start": {
                    "accountSid": ACCOUNT,
                    "callSid": SID,
                    "streamSid": "MZ" + "c" * 32,
                    "tracks": ["inbound"],
                    "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
                    "customParameters": {"nonce": nonce},
                },
            }
        )
    )
    callers = []

    class Session:
        def __init__(self, stream, caller, **kwargs):
            callers.append(caller)

        async def run(self):
            return None

    monkeypatch.setattr(runtime, "VoiceCallSession", Session)
    # A rejected competing claim must not tear down the accepted provider call.
    with monkeypatch.context() as competing:
        competing.setattr(
            runtime, "_claim_stream", AsyncMock(side_effect=WebSocketDisconnect(1008))
        )
        await runtime.media(raw, call_id, provider=provider, sessions=sessions(db))
        assert provider.stops == [] and callers == []
    await runtime.media(raw, call_id, provider=provider, sessions=sessions(db))
    assert len(callers) == 1 and callers[0].anonymous and callers[0].user_id is None
    assert callers[0].surface == "embed" and callers[0].ctx.subject_is_publisher_fallback
    assert provider.stops == [SID]
    await runtime.media(raw, call_id, provider=provider, sessions=sessions(db))
    assert len(callers) == 1


async def test_phone_capability_publishes_only_valid_routes_and_routines_freeze_route_identity(
    db: AsyncSession, monkeypatch
):
    from app.agents.spec import AgentSpec, CapabilityBindingSpec
    from app.core.exceptions import BadRequestError
    from app.db.models.organization import Organization
    from app.schemas.agent_trigger import TriggerCreate
    from app.services.agent_registry import AgentRegistryService
    from app.services.agent_trigger import AgentTriggerService
    from app.services.routine_authority import RoutineAuthority
    from app.services.routine_sources import RoutineSourcesRequired, read_policy
    from tests.integration.test_workflow_agent_node import _profile

    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    org = await db.get(Organization, ctx.organization_id)
    assert org is not None
    await db.commit()
    profile = await _profile(db.bind, org)
    registry = AgentRegistryService(db)
    spec = AgentSpec(
        name="Phone reporter",
        model_profile_id=profile,
        capabilities=[
            CapabilityBindingSpec(id="phone_calls", config={"endpoint_id": str(endpoint.id)})
        ],
    )
    agent = await registry.create(ctx, spec)
    version = await registry.publish(ctx, agent.id)
    trigger = await AgentTriggerService(db).create(
        ctx,
        agent.id,
        TriggerCreate(
            name="Report",
            prompt="Report verified changes",
            runs_as_creator=True,
            pinned_version_id=version.id,
            interval_seconds=300,
        ),
    )
    policy = read_policy(trigger.approved_sources)
    assert set(policy.phone_sources) == {endpoint.id}
    assert TOKEN not in str(trigger.approved_sources) and PERSON_NUMBER not in str(
        trigger.approved_sources
    )
    authority = await RoutineAuthority.capture(
        db,
        replace(
            ctx,
            routine_id=trigger.id,
            routine_source_policy_id=policy.id,
            fired_as_creator="schedule",
        ),
        agent_id=agent.id,
        run=None,
    )
    assert authority is not None
    await authority.check_in(db, agent.id)
    route = await repo.endpoint(db, endpoint.id)
    assert route is not None
    route.generation = uuid4()
    await db.flush()
    with pytest.raises(RoutineSourcesRequired):
        await authority.check_in(db, agent.id)
    bad = await registry.create(
        ctx,
        spec.model_copy(
            update={
                "name": "Broken phone route",
                "capabilities": [
                    CapabilityBindingSpec(id="phone_calls", config={"endpoint_id": str(uuid4())})
                ],
            }
        ),
    )
    with pytest.raises(BadRequestError):
        await registry.publish(ctx, bad.id)


@pytest.mark.parametrize("decision", ["acknowledge", "resolve", "mute", "read"])
@pytest.mark.parametrize("call_status", ["queued", "dialing", "active", "during_dial"])
async def test_delayed_case_call_is_one_delivery_and_settlement_cancels_it(
    db: AsyncSession, monkeypatch, decision, call_status
):
    from app.agents.spec import AgentSpec
    from app.db.models.notification import Notification
    from app.db.models.organization import Organization
    from app.repositories import agent_run_repo, outcome_repo
    from app.services.agent_registry import AgentRegistryService
    from app.services.outcome import OutcomeService
    from tests.integration.test_workflow_agent_node import _profile

    ctx, _, _, contact, endpoint = await setup(db, monkeypatch)
    org = await db.get(Organization, ctx.organization_id)
    assert org is not None
    await db.commit()
    profile = await _profile(db.bind, org)
    registry = AgentRegistryService(db)
    agent = await registry.create(
        ctx, AgentSpec(name="Important case agent", model_profile_id=profile)
    )
    version = await registry.publish(ctx, agent.id)
    run = await agent_run_repo.create_run(
        db,
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        agent_version_id=version.id,
        user_id=ctx.user_id,
        conversation_id=None,
        surface="web",
        model_label=None,
        started_at=datetime.now(UTC),
    )
    case = await outcome_repo.open_or_find(
        db,
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        kind="run_failed",
        dedupe_key=f"phone-test:{uuid4()}",
        summary="Production blocked",
        context_url=None,
        source_run_id=run.id,
        source_conversation_id=None,
    )
    assert [
        item.id
        for item in await repo.open_phone_cases(
            db,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            agent_id=agent.id,
            conversation_id=None,
        )
    ] == [case.id]
    assert (
        await repo.open_phone_cases(
            db,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            agent_id=uuid4(),
            conversation_id=None,
        )
        == []
    )
    assert (
        await repo.open_phone_cases(
            db,
            organization_id=uuid4(),
            user_id=ctx.user_id,
            agent_id=agent.id,
            conversation_id=None,
        )
        == []
    )
    data = PhoneCallCreate(
        request_key=uuid4(),
        endpoint_id=endpoint.id,
        mode="report",
        report="Production is blocked.",
        outcome_id=case.id,
        importance_reason="The member allows calls for production outages.",
    )
    service = PhoneCallService(db)
    with pytest.raises(AuthorizationError, match="Select this agent"):
        await service.create(ctx, data, source_run_id=run.id)
    config = PhoneContactConfig.model_validate(
        contact.model_dump(include=set(PhoneContactConfig.model_fields))
    ).model_copy(
        update={
            "agent_ids": [agent.id],
            "allow_important": True,
            "importance_instructions": "Production outages only",
            "escalation_delay_seconds": 600,
        }
    )
    await PhonePolicyService(db).set_contact(ctx, config)
    with pytest.raises(AuthorizationError, match="unacknowledged notification"):
        await service.create(ctx, data, source_run_id=run.id)
    notified = datetime.now(UTC)
    db.add(
        Notification(
            organization_id=ctx.organization_id,
            recipient_user_id=ctx.user_id,
            event_type="run_failed",
            occurrence_id=str(uuid4()),
            summary="Production blocked",
            outcome_id=case.id,
            created_at=notified,
        )
    )
    await db.flush()
    first = await service.create(ctx, data, source_run_id=run.id)
    repeated = await service.create(
        ctx, data.model_copy(update={"request_key": uuid4()}), source_run_id=run.id
    )
    assert first.id == repeated.id
    row = await repo.call(db, first.id)
    assert row is not None and row.agent_id == agent.id and row.purpose == "important"
    assert row.not_before == notified + timedelta(seconds=600)
    job = await db.scalar(
        select(BackgroundJob).where(BackgroundJob.dedupe_key == f"phone:{row.id}")
    )
    assert job is not None and job.run_after == row.not_before
    early = FakePhone()
    await db.commit()
    await dial(row.id, provider=early, sessions=sessions(db))
    assert early.dials == []
    await db.refresh(row)
    if call_status == "during_dial":
        row.not_before = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
        factory = sessions(db)

        class SettlingPhone(FakePhone):
            async def dial(
                self,
                credentials: PhoneCredentials,
                *,
                number: str,
                twiml: str,
                callback: str,
                cap_seconds: int,
            ) -> str:
                async with factory() as other:
                    if decision == "read":
                        from app.services.notification_center import NotificationCenterService

                        await NotificationCenterService(other).mark_all_read(ctx)
                    else:
                        await OutcomeService(other).settle(ctx, case.id, decision, via="inbox")
                    await other.commit()
                return await super().dial(
                    credentials,
                    number=number,
                    twiml=twiml,
                    callback=callback,
                    cap_seconds=cap_seconds,
                )

        racing_provider = SettlingPhone()
        await dial(row.id, provider=racing_provider, sessions=factory)
        assert racing_provider.dials == [PERSON_NUMBER]
        assert racing_provider.stops == [SID]
        await db.refresh(row)
        assert row.status == "completed" and row.finished_at is not None
        return
    row.status = call_status
    if call_status == "active":
        row.provider_sid = SID
    await db.flush()
    if decision == "read":
        from app.services.notification_center import NotificationCenterService

        await NotificationCenterService(db).mark_all_read(ctx)
    else:
        await OutcomeService(db).settle(ctx, case.id, decision, via="inbox")
    await db.refresh(row)
    if call_status == "queued":
        assert row.status == "cancelled" and row.estimated_cost_usd == 0
    else:
        assert row.status == "ending"
        cleanup = await db.scalar(
            select(BackgroundJob).where(BackgroundJob.dedupe_key == f"phone-end:{row.id}")
        )
        assert cleanup is not None and cleanup.kind == "end-phone"
    await db.commit()
    provider = FakePhone()
    await dial(row.id, provider=provider, sessions=sessions(db))
    assert provider.dials == []
    if call_status == "active":
        await end_media(row.id, provider=provider, sessions=sessions(db))
        assert provider.stops == [SID]
        await db.refresh(row)
        assert row.status == "completed"
    plain = PhoneCallCreate(
        request_key=uuid4(), endpoint_id=endpoint.id, mode="report", report="Scheduled report"
    )
    first_report = await service.create(ctx, plain, source_run_id=run.id)
    second_report = await service.create(
        ctx, plain.model_copy(update={"request_key": uuid4()}), source_run_id=run.id
    )
    assert first_report.id == second_report.id


async def test_agent_deletion_retains_provider_receipt_for_reaper_cleanup(
    db: AsyncSession, monkeypatch
):
    from app.db.models.agent import Agent

    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    agent = Agent(
        organization_id=ctx.organization_id,
        name="Deleted phone agent",
        slug=uuid4().hex,
        created_by_user_id=ctx.user_id,
    )
    db.add(agent)
    await db.flush()
    receipt = await report(db, ctx, endpoint.id)
    row = await repo.call(db, receipt.id)
    assert row is not None
    row.agent_id = agent.id
    row.mode = "conversation"
    row.status = "ringing"
    row.provider_sid = SID
    await db.commit()
    await db.delete(agent)
    await db.commit()
    await db.refresh(row)
    assert row.agent_id is None and row.provider_sid == SID
    provider = FakePhone()
    await reap(provider=provider, sessions=sessions(db))
    assert provider.stops == [SID]
    await db.refresh(row)
    assert row.status in {"failed", "completed"}


async def test_signed_completion_reconciles_cost_after_local_teardown_without_reopening(
    db: AsyncSession, monkeypatch
):
    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    receipt = await report(db, ctx, endpoint.id)
    await db.commit()
    provider = FakePhone()
    await dial(receipt.id, provider=provider, sessions=sessions(db))
    await end_media(receipt.id, provider=provider, sessions=sessions(db))
    row = await repo.call(db, receipt.id)
    assert (
        row is not None and row.status == "completed" and row.estimated_cost_usd == Decimal("0.5")
    )
    params = {
        "AccountSid": ACCOUNT,
        "CallSid": SID,
        "To": PERSON_NUMBER,
        "From": NUMBER,
        "CallStatus": "completed",
        "CallDuration": "5",
    }
    signature = twilio_signature(url(f"/status/{row.id}"), params, TOKEN)
    await PhoneWebhookService(db).status(row.id, urlencode(params).encode(), signature)
    await db.refresh(row)
    assert row.status == "completed" and row.estimated_cost_usd == Decimal("0.1")


@pytest.mark.parametrize("authority_change", ["none", "ended", "endpoint", "expired", "revoked"])
async def test_interactive_outbound_call_queues_without_a_report_conversation(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, authority_change: str
) -> None:
    from app.agents.spec import AgentSpec, VoiceSpec
    from app.db.models.credential import ModelProfile
    from app.db.models.organization import Organization
    from app.services import realtime_models
    from app.services.agent_registry import AgentRegistryService
    from tests.integration.test_workflow_agent_node import _profile

    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    org = await db.get(Organization, ctx.organization_id)
    assert org is not None
    await db.commit()
    model_id = await _profile(db.bind, org)
    profile = await db.get(ModelProfile, model_id)
    available = realtime_models.by_provider("openai")
    assert profile is not None and available is not None
    registry = AgentRegistryService(db)
    agent = await registry.create(
        ctx,
        AgentSpec(
            name="Outbound voice agent",
            model_profile_id=model_id,
            voice=VoiceSpec(
                provider="openai", model=available.models[0].id, secret_id=profile.secret_id
            ),
        ),
    )
    await registry.publish(ctx, agent.id)
    receipt = await PhoneCallService(db).create(
        ctx,
        PhoneCallCreate(request_key=uuid4(), endpoint_id=endpoint.id, agent_id=agent.id),
    )
    row = await repo.call(db, receipt.id)
    assert row is not None and row.mode == "conversation" and row.conversation_id is None
    assert row.status == "queued"
    jobs = list(
        await db.scalars(
            select(BackgroundJob).where(
                BackgroundJob.organization_id == ctx.organization_id,
                BackgroundJob.kind == "dial-phone",
            )
        )
    )
    assert len(jobs) == 1 and jobs[0].payload["call_id"] == str(row.id)

    import json
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import WebSocket

    from app.db.models.conversation import Conversation
    from app.services.telephony import runtime
    from app.services.telephony.provider import stream_nonce

    source = Conversation(
        organization_id=ctx.organization_id, user_id=ctx.user_id, title="Phone source"
    )
    db.add(source)
    await db.flush()
    row.source_conversation_id = source.id
    await db.commit()
    provider = FakePhone()
    factory = sessions(db)
    await dial(row.id, provider=provider, sessions=factory)
    await db.refresh(row)
    _, _, auth = await PhonePolicyService(db).load_endpoint(endpoint.id)
    socket = MagicMock(spec=WebSocket)
    socket.headers = {
        "x-twilio-signature": twilio_signature(url(f"/media/{row.id}", websocket=True), {}, TOKEN)
    }
    socket.accept = AsyncMock()
    socket.close = AsyncMock()
    socket.receive_text = AsyncMock(
        return_value=json.dumps(
            {
                "event": "start",
                "streamSid": "MZ" + "c" * 32,
                "start": {
                    "accountSid": ACCOUNT,
                    "callSid": SID,
                    "streamSid": "MZ" + "c" * 32,
                    "tracks": ["inbound"],
                    "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
                    "customParameters": {"nonce": stream_nonce(auth, row)},
                },
            }
        )
    )
    caller_seen = []

    class Session:
        def __init__(self, stream, caller, *, sessions, reauthorize):
            self.reauthorize = reauthorize
            caller_seen.append(caller)

        async def run(self):
            async with factory() as fresh:
                admitted = await repo.call(fresh, row.id)
                assert admitted is not None
                if authority_change == "ended":
                    admitted.status = "ending"
                elif authority_change == "endpoint":
                    route = await repo.endpoint(
                        fresh, endpoint.id, organization_id=ctx.organization_id
                    )
                    assert route is not None
                    route.generation = uuid4()
                elif authority_change == "expired":
                    admitted.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                elif authority_change == "revoked":
                    person = await repo.contact_by_id(
                        fresh, admitted.contact_id, organization_id=ctx.organization_id
                    )
                    assert person is not None
                    person.allow_calls = False
                await fresh.flush()
                current = await self.reauthorize(fresh)
                assert (current is not None) == (authority_change == "none")
                await fresh.commit()
            raise TimeoutError

    monkeypatch.setattr(runtime, "VoiceCallSession", Session)
    await runtime.media(socket, row.id, provider=provider, sessions=factory)
    assert len(caller_seen) == 1
    assert caller_seen[0].conversation_id == source.id and not caller_seen[0].anonymous
    assert caller_seen[0].phone_agent_version_id == row.agent_version_id
    assert provider.stops == [SID]
    await db.refresh(row)
    assert row.status == "completed" and row.end_reason == "disconnected"


async def test_bot_deletion_keeps_live_call_receipts_until_calls_end(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.channel_bot import ChannelBotService

    ctx, bot, _, _, endpoint = await setup(db, monkeypatch)
    receipt = await report(db, ctx, endpoint.id)
    service = ChannelBotService(db, ctx.organization_id)
    with pytest.raises(ConflictError, match="End all telephone calls"):
        await service.delete(bot.id, ctx)
    row = await repo.call(db, receipt.id)
    assert row is not None and row.status == "queued"
    row.status = "cancelled"
    row.finished_at = datetime.now(UTC)
    await db.flush()
    await service.delete(bot.id, ctx)
    assert (
        await channel_bot_repo.get_for_org(db, bot.id, organization_id=ctx.organization_id) is None
    )


@pytest.mark.parametrize("target", ["account", "organization"])
async def test_account_and_org_deletion_cannot_orphan_live_provider_calls(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    from app.db.models.organization import Organization
    from app.db.models.user import User
    from app.services.organization import OrganizationService
    from app.services.user import UserService

    ctx, bot, _, _, endpoint = await setup(db, monkeypatch)
    receipt = await report(db, ctx, endpoint.id)
    with pytest.raises(ConflictError, match="End all telephone calls"):
        if target == "account":
            await UserService(db).delete(ctx.user_id)
        else:
            org = await db.get(Organization, ctx.organization_id)
            assert org is not None
            await OrganizationService(db).purge(org)
    assert await repo.call(db, receipt.id) is not None
    assert await db.get(User, ctx.user_id) is not None
    assert (
        await channel_bot_repo.get_for_org(db, bot.id, organization_id=ctx.organization_id)
        is not None
    )


@pytest.mark.parametrize("completion", ["crash", "callback"])
async def test_reaper_commits_cleanup_intent_and_releases_lock_before_provider_io(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, completion: str
) -> None:
    import anyio

    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    receipt = await report(db, ctx, endpoint.id)
    row = await repo.call(db, receipt.id)
    assert row is not None
    row.status = "ringing"
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    row.provider_sid = SID
    await db.commit()
    factory = sessions(db)

    class InspectingPhone(FakePhone):
        async def hangup(self, credentials: PhoneCredentials, sid: str) -> None:
            # A callback uses another transaction and must not wait on provider IO.
            with anyio.fail_after(2):
                async with factory() as callback_db:
                    live = await repo.call(callback_db, receipt.id, lock=True)
                    assert live is not None and live.status == "ending"
                    if completion == "callback":
                        params = {
                            "AccountSid": ACCOUNT,
                            "CallSid": SID,
                            "To": PERSON_NUMBER,
                            "From": NUMBER,
                            "CallStatus": "completed",
                            "CallDuration": "61",
                        }
                        signature = twilio_signature(url(f"/status/{receipt.id}"), params, TOKEN)
                        await PhoneWebhookService(callback_db).status(
                            receipt.id, urlencode(params).encode(), signature
                        )
            if completion == "crash":
                raise RuntimeError("Worker stopped after provider acceptance")
            await super().hangup(credentials, sid)

    if completion == "crash":
        with pytest.raises(RuntimeError, match="Worker stopped"):
            await reap(provider=InspectingPhone(), sessions=factory)
        async with factory() as fresh:
            durable = await repo.call(fresh, receipt.id)
            assert durable is not None and durable.status == "ending"
        retry = FakePhone()
        assert await reap(provider=retry, sessions=factory) == 1
        assert retry.stops == [SID]
    else:
        provider = InspectingPhone()
        await reap(provider=provider, sessions=factory)
        assert provider.stops == [SID]
        async with factory() as fresh:
            settled = await repo.call(fresh, receipt.id)
            assert settled is not None and settled.status == "completed"
            assert settled.estimated_cost_usd == Decimal("0.20")


async def test_cancel_accepted_during_dial_is_finished_when_provider_sid_arrives(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    receipt = await report(db, ctx, endpoint.id)
    await db.commit()
    factory = sessions(db)

    class CancellingPhone(FakePhone):
        async def dial(
            self,
            credentials: PhoneCredentials,
            *,
            number: str,
            twiml: str,
            callback: str,
            cap_seconds: int,
        ) -> str:
            await end_media(receipt.id, provider=self, sessions=factory, end_reason="user")
            assert self.stops == []
            return await super().dial(
                credentials, number=number, twiml=twiml, callback=callback, cap_seconds=cap_seconds
            )

    provider = CancellingPhone()
    await dial(receipt.id, provider=provider, sessions=factory)
    assert provider.dials == [PERSON_NUMBER] and provider.stops == [SID]
    async with factory() as fresh:
        settled = await repo.call(fresh, receipt.id)
        assert settled is not None and settled.status == "completed"
        assert settled.finished_at is not None


async def test_sms_credential_rotation_preserves_unfinished_call_cleanup(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.schemas.channel_bot import ChannelBotUpdate
    from app.services.channel_bot import ChannelBotService, unseal_bot_token

    ctx, bot, _, _, endpoint = await setup(db, monkeypatch)
    receipt = await report(db, ctx, endpoint.id)
    row = await repo.call(db, receipt.id)
    assert row is not None
    row.status = "ringing"
    row.provider_sid = SID
    await db.flush()
    service = ChannelBotService(db, ctx.organization_id)
    before = bot.authorization_generation
    replacement = f"{ACCOUNT}:{'x' * 32}:{NUMBER}"
    data = ChannelBotUpdate(token=replacement)
    with pytest.raises(ConflictError, match="End all telephone calls"):
        await service.update(bot.id, data, ctx)
    assert bot.authorization_generation == before
    assert unseal_bot_token(bot) == f"{ACCOUNT}:{TOKEN}:{NUMBER}"
    # The old signature remains valid until its call is terminal.
    params = {
        "AccountSid": ACCOUNT,
        "CallSid": SID,
        "To": PERSON_NUMBER,
        "From": NUMBER,
        "CallStatus": "completed",
        "CallDuration": "61",
    }
    signature = twilio_signature(url(f"/status/{receipt.id}"), params, TOKEN)
    await PhoneWebhookService(db).status(receipt.id, urlencode(params).encode(), signature)
    updated = await service.update(bot.id, data, ctx)
    assert updated.authorization_generation != before
    assert unseal_bot_token(updated) == replacement


async def test_phone_settings_separate_personal_consent_from_operator_routes(
    db: AsyncSession, monkeypatch
) -> None:
    ctx, bot, identity, contact, endpoint = await setup(db, monkeypatch)
    policy = PhonePolicyService(db)
    admin = await policy.settings(ctx)
    assert admin.contact is not None and admin.contact.masked_number.endswith("1111")
    assert [row.id for row in admin.sms_identities] == [identity.id]
    assert [row.id for row in admin.endpoints] == [endpoint.id]
    assert [row.id for row in admin.sms_bots] == [bot.id]
    assert [row.id for row in admin.call_endpoints] == [endpoint.id]
    ordinary = await policy.settings(replace(ctx, role="member"))
    assert ordinary.endpoints == [] and ordinary.sms_bots == []
    assert ordinary.contact is not None
    bot.is_active = False
    await db.flush()
    assert (await policy.settings(ctx)).call_endpoints == []


async def test_anonymous_and_detached_calls_never_inherit_a_members_authority(
    db: AsyncSession, monkeypatch
) -> None:
    from app.services.telephony.runtime import end_from_agent, transfer_options

    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    call = await report(db, ctx, endpoint.id)
    row = await repo.call(db, call.id)
    assert row is not None
    with pytest.raises(AuthorizationError):
        await end_from_agent(db, call.id, source_run_id=uuid4(), endpoint_id=endpoint.id)
    with pytest.raises(AuthorizationError):
        await transfer_options(db, call.id)
    with pytest.raises(NotFoundError):
        await transfer_options(db, uuid4(), ctx=ctx)
    assert await transfer_options(db, call.id, ctx=ctx) == []
    row.contact_id = None
    await db.flush()
    with pytest.raises(AuthorizationError, match="consenting member"):
        await live_contact(db, row)


async def test_member_reinvitation_requires_fresh_phone_opt_in(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models.organization import OrganizationMember
    from app.repositories import member as members
    from app.services.member import end_membership

    ctx, _, _, _, _ = await setup(db, monkeypatch)
    membership = await members.get(db, organization_id=ctx.organization_id, user_id=ctx.user_id)
    assert membership is not None
    await end_membership(db, membership)
    db.add(
        OrganizationMember(organization_id=ctx.organization_id, user_id=ctx.user_id, role="owner")
    )
    await db.flush()
    assert await repo.contact(db, organization_id=ctx.organization_id, user_id=ctx.user_id) is None


async def test_telephone_history_is_tenant_scoped_and_inbound_callbacks_keep_their_signed_path(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    call = await report(db, ctx, endpoint.id)
    row = await repo.call(db, call.id)
    assert row is not None
    row.provider_sid = SID
    await db.flush()
    assert [
        item.id
        for item in await repo.recent_calls(
            db, organization_id=ctx.organization_id, user_id=ctx.user_id
        )
    ] == [call.id]
    assert len(await repo.recent_calls(db, organization_id=ctx.organization_id, user_id=None)) == 1
    assert await repo.recent_calls(db, organization_id=uuid4(), user_id=None) == []
    calls = PhoneCallService(db)
    with pytest.raises(NotFoundError):
        await calls.get(ctx, uuid4())
    assert (await calls.get(ctx, call.id)).id == call.id
    assert [item.id for item in await calls.recent(ctx)] == [call.id]
    service = PhoneWebhookService(db)
    for identifier, endpoint_filter in [(uuid4(), None), (call.id, uuid4())]:
        with pytest.raises(NotFoundError):
            await service.status(identifier, b"", "", endpoint_id=endpoint_filter)
    with pytest.raises(NotFoundError):
        await service.inbound_status(endpoint.id, b"CallSid=missing", "")
    with pytest.raises(AuthorizationError, match="signature"):
        await service.inbound(endpoint.id, b"CallSid=" + SID.encode(), "invalid")
    params = {
        "CallSid": SID,
        "AccountSid": ACCOUNT,
        "To": PERSON_NUMBER,
        "From": NUMBER,
        "CallStatus": "busy",
    }
    body = urlencode(params).encode()
    signed = twilio_signature(url(f"/inbound-status/{endpoint.id}"), params, TOKEN)
    await service.inbound_status(endpoint.id, body, signed)
    await db.refresh(row)
    assert row.status == "failed" and row.estimated_cost_usd == 0


async def test_an_existing_member_without_phone_opt_in_cannot_queue_a_call(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    await repo.delete_member_contact(db, organization_id=ctx.organization_id, user_id=ctx.user_id)
    with pytest.raises(AuthorizationError, match="Opt into phone"):
        await report(db, ctx, endpoint.id)
    assert (
        await repo.recent_calls(db, organization_id=ctx.organization_id, user_id=ctx.user_id) == []
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("AccountSid", "AC" + "c" * 32),
        ("CallSid", "invalid"),
        ("To", "+15552222222"),
        ("From", "+15553333333"),
    ],
)
async def test_callback_cannot_settle_another_provider_account_or_destination(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    from app.services.telephony.runtime import status_callback

    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    call = await report(db, ctx, endpoint.id)
    params = {
        "CallSid": SID,
        "AccountSid": ACCOUNT,
        "To": PERSON_NUMBER,
        "From": NUMBER,
        "CallStatus": "completed",
    }
    params[field] = value
    with pytest.raises(AuthorizationError):
        await status_callback(db, call.id, params)
    assert (await repo.call(db, call.id)).status == "queued"


@pytest.mark.parametrize("expired", [False, True])
async def test_dial_rejects_expired_or_rotated_intentions_before_any_provider_effect(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, expired: bool
) -> None:
    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    call = await report(db, ctx, endpoint.id)
    row = await repo.call(db, call.id)
    assert row is not None
    if expired:
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    else:
        current = await repo.endpoint(db, endpoint.id, organization_id=ctx.organization_id)
        assert current is not None
        current.generation = uuid4()
    await db.commit()
    provider = FakePhone()
    await dial(call.id, provider=provider, sessions=sessions(db))
    assert provider.dials == []
    await db.refresh(row)
    assert row.status == "cancelled" and row.estimated_cost_usd == 0


async def test_definitive_dial_refusal_finishes_once_and_retries_never_ring(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.exceptions import ExternalServiceError

    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    call = await report(db, ctx, endpoint.id)
    await db.commit()

    class RefusingPhone(FakePhone):
        async def dial(
            self,
            credentials: PhoneCredentials,
            *,
            number: str,
            twiml: str,
            callback: str,
            cap_seconds: int,
        ) -> str:
            self.dials.append("attempt")
            raise ExternalServiceError(message="Provider refused")

    provider = RefusingPhone()
    await dial(call.id, provider=provider, sessions=sessions(db))
    await dial(call.id, provider=provider, sessions=sessions(db))
    row = await repo.call(db, call.id)
    assert row is not None and row.status == "failed" and row.estimated_cost_usd == 0
    assert provider.dials == ["attempt"]


async def test_conflicting_provider_receipts_remain_unknown_instead_of_binding_another_call(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.telephony.runtime import _settle_submission

    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    call = await report(db, ctx, endpoint.id)
    row = await repo.call(db, call.id)
    assert row is not None
    row.status = "dialing"
    row.provider_sid = SID
    await db.commit()
    assert not await _settle_submission(
        sessions(db), call.id, status="ringing", sid="CA" + "d" * 32
    )
    await db.refresh(row)
    assert row.status == "unknown" and row.provider_sid == SID
    assert not await _settle_submission(sessions(db), uuid4(), status="failed")


async def test_sms_deactivation_preserves_unfinished_calls(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.channel_bot import ChannelBotService

    ctx, bot, _, _, endpoint = await setup(db, monkeypatch)
    receipt = await report(db, ctx, endpoint.id)
    row = await repo.call(db, receipt.id)
    assert row is not None
    service = ChannelBotService(db, ctx.organization_id)
    with pytest.raises(ConflictError, match="End all telephone calls"):
        await service.deactivate(bot.id)
    assert bot.is_active
    row.status = "completed"
    row.finished_at = datetime.now(UTC)
    await db.flush()
    assert not (await service.deactivate(bot.id)).is_active


async def test_operator_can_read_another_members_receipt_but_cannot_control_it(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.audit import set_impersonator
    from app.services.telephony.runtime import hangup

    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    receipt = await report(db, ctx, endpoint.id)
    service = PhoneCallService(db)
    assert (await service.controllable(ctx, receipt.id)).id == receipt.id
    other = replace(ctx, user_id=uuid4())
    assert (await service.readable(other, receipt.id)).id == receipt.id
    for authority in (other, replace(ctx, api_key_id=uuid4())):
        with pytest.raises(AuthorizationError, match="call owner"):
            await service.controllable(authority, receipt.id)
        with pytest.raises(AuthorizationError, match="call owner"):
            await hangup(db, authority, receipt.id)
    set_impersonator(uuid4())
    try:
        with pytest.raises(AuthorizationError, match="call owner"):
            await service.controllable(ctx, receipt.id)
    finally:
        set_impersonator(None)


async def test_spoken_source_run_retries_keep_the_original_owned_chat_receipt(db, monkeypatch):
    from app.db.models.agent import Agent, AgentVersion
    from app.db.models.conversation import Conversation, Message
    from app.repositories import agent_run_repo

    ctx, _, _, _, endpoint = await setup(db, monkeypatch)
    agent = Agent(
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name="Reporter",
        slug=f"reporter-{uuid4()}",
        status="published",
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        agent_id=agent.id, organization_id=ctx.organization_id, version=1, spec={"name": "Reporter"}
    )
    source = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id, title="Source")
    db.add_all([version, source])
    await db.flush()
    agent.current_version_id = version.id
    contact = await repo.contact(db, organization_id=ctx.organization_id, user_id=ctx.user_id)
    assert contact is not None
    contact.agent_ids = [str(agent.id)]
    run = await agent_run_repo.create_run(
        db,
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        agent_version_id=version.id,
        user_id=ctx.user_id,
        conversation_id=source.id,
        surface="web",
        model_label="test",
        started_at=datetime.now(UTC),
    )
    await db.flush()
    service = PhoneCallService(db)
    data = PhoneCallCreate(
        request_key=uuid4(),
        endpoint_id=endpoint.id,
        mode="report",
        report="Summary",
        source_conversation_id=source.id,
    )
    first = await service.create(ctx, data, source_run_id=run.id)
    second = await service.create(
        ctx, data.model_copy(update={"request_key": uuid4()}), source_run_id=run.id
    )
    assert second.id == first.id
    posted = list(await db.scalars(select(Message).where(Message.conversation_id == source.id)))
    assert len(posted) == 1 and posted[0].parts[0]["phone_call_id"] == str(first.id)
