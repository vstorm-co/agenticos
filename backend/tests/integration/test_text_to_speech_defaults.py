"""Inherited voices retain their destination and current vault authority in PostgreSQL."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import BadRequestError
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.organization import Organization
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.user import User
from app.repositories import organization as organization_repo
from app.schemas.organization import OrganizationTextToSpeech
from app.services.text_to_speech_settings import TextToSpeechSettingsService

pytestmark = pytest.mark.anyio


async def setup_voice(db: AsyncSession) -> tuple[Organization, OrganizationSecret, AgentRun]:
    person = User(id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="x")
    db.add(person)
    await db.flush()
    org = Organization(id=uuid4(), name="Speech", slug=uuid4().hex, created_by_user_id=person.id)
    db.add(org)
    await db.flush()
    agent = Agent(id=uuid4(), organization_id=org.id, name="Voice", slug=uuid4().hex, draft_spec={})
    key = OrganizationSecret(
        id=uuid4(),
        organization_id=org.id,
        name="Speech key",
        kind="api_key",
        purpose="openai",
        visibility="org",
        sealed_secret="opaque-fixture-not-unsealed",
    )
    db.add_all([agent, key])
    await db.flush()
    run = AgentRun(
        id=uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        user_id=person.id,
        surface=RunSurface.WEB.value,
        status=RunStatus.RUNNING.value,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    defaults = OrganizationTextToSpeech(
        provider="openai", model="gpt-4o-mini-tts", voice="coral", secret_id=key.id
    )
    await organization_repo.set_text_to_speech(db, org, defaults=defaults.model_dump(mode="json"))
    return org, key, run


def spec() -> AgentSpec:
    return AgentSpec(
        name="Voice",
        capabilities=[
            CapabilityBindingSpec(id="text_to_speech", config={"use_organization_defaults": True})
        ],
    )


async def test_a_reload_keeps_the_original_voice_in_a_parked_run(db: AsyncSession) -> None:
    org, key, run = await setup_voice(db)
    service = TextToSpeechSettingsService(db)
    first = await service.for_run(org.id, spec(), run)
    assert org.text_to_speech is not None
    await organization_repo.set_text_to_speech(
        db, org, defaults={**org.text_to_speech, "voice": "alloy"}
    )
    await db.refresh(run)
    resumed = await service.for_run(org.id, spec(), run)
    assert (
        first.capabilities[0].config["voice"] == resumed.capabilities[0].config["voice"] == "coral"
    )
    assert resumed.capabilities[0].secret_id == key.id
    assert run.text_to_speech_defaults is not None
    assert run.text_to_speech_defaults["voice"] == "coral"


@pytest.mark.security
@pytest.mark.parametrize("change", ["private", "deleted", "disabled"])
async def test_a_saved_destination_cannot_keep_spending_after_authority_is_removed(
    db: AsyncSession, change: str
) -> None:
    org, key, run = await setup_voice(db)
    service = TextToSpeechSettingsService(db)
    await service.for_run(org.id, spec(), run)
    if change == "private":
        key.owner_user_id = run.user_id
        key.visibility = "private"
    elif change == "deleted":
        await db.delete(key)
    else:
        assert org.text_to_speech is not None
        org.text_to_speech = {**org.text_to_speech, "enabled": False}
    await db.flush()
    with pytest.raises(BadRequestError) as refused:
        await service.for_run(org.id, spec(), run)
    assert "opaque-fixture" not in str(refused.value)


@pytest.mark.security
async def test_an_organization_cannot_spend_another_tenants_voice_key(db: AsyncSession) -> None:
    first, key, _ = await setup_voice(db)
    other, _, _ = await setup_voice(db)
    value = OrganizationTextToSpeech(provider="openai", model="gpt-4o-mini-tts", secret_id=key.id)
    with pytest.raises(BadRequestError):
        await TextToSpeechSettingsService(db).validate_defaults(other.id, value)
    assert first.id != other.id
