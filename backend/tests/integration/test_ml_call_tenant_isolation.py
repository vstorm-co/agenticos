"""An ML service call belongs to the organization that made it, and to no other.

The unit suite mocks the repository, so it can only prove that the service passes
an organization id down. What a second tenant actually sees when it asks for the
row by id is a question for the database, and it is the one FA-069's acceptance
asks about: a service another Urban Stack component calls with a key must not let
one caller read another's usage.

So this writes real rows for two organizations and reads them back through the
service the routes use.
"""

from __future__ import annotations

import uuid

import pytest

from app.agents.spec import AgentSpec
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.channel_bot import ChannelBot
from app.db.models.ml_service_call import TranscriptionSurface
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import ml_service_call_repo
from app.services import transcription_usage
from app.services.ml import MLService
from app.services.transcription_usage import TranscriptionCall

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _org(db, *, name: str) -> tuple[Organization, User]:
    founder = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(founder)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization, founder


def _ctx(organization: Organization, member: User) -> AuthContext:
    return AuthContext(user_id=member.id, organization_id=organization.id, role=OrgRoleName.OWNER)


async def _call(db, organization: Organization, member: User, *, service: str = "ocr"):
    return await ml_service_call_repo.record(
        db,
        organization_id=organization.id,
        requested_by_user_id=member.id,
        service=service,
        status="succeeded",
        input_bytes=2048,
        units=4,
        unit="pages",
        duration_ms=1200,
    )


class TestOneTenantsCallsAreInvisibleToAnother:
    async def test_the_organization_that_made_the_call_reads_it_back(self, db) -> None:
        acme, founder = await _org(db, name="Acme")
        row = await _call(db, acme, founder)

        found = await MLService(db).call_record(_ctx(acme, founder), row.id)

        assert found.id == row.id
        assert found.units == 4

    async def test_another_organization_asking_by_id_is_told_it_does_not_exist(self, db) -> None:
        """Not found rather than forbidden, so ids stay unprobeable."""
        acme, founder = await _org(db, name="Acme")
        globex, other = await _org(db, name="Globex")
        row = await _call(db, acme, founder)

        with pytest.raises(NotFoundError):
            await MLService(db).call_record(_ctx(globex, other), row.id)

    async def test_the_listing_carries_only_the_callers_own_rows(self, db) -> None:
        acme, founder = await _org(db, name="Acme")
        globex, other = await _org(db, name="Globex")
        mine = await _call(db, acme, founder)
        await _call(db, globex, other)

        rows, total = await MLService(db).call_records(
            _ctx(acme, founder), service=None, skip=0, limit=50
        )

        assert [row.id for row in rows] == [mine.id]
        assert total == 1

    async def test_narrowing_to_a_service_still_answers_inside_the_organization(self, db) -> None:
        acme, founder = await _org(db, name="Acme")
        globex, other = await _org(db, name="Globex")
        await _call(db, acme, founder, service="ocr")
        await _call(db, acme, founder, service="pii_detection")
        await _call(db, globex, other, service="ocr")

        rows, total = await MLService(db).call_records(
            _ctx(acme, founder), service="ocr", skip=0, limit=50
        )

        assert total == 1
        assert rows[0].organization_id == acme.id


async def _agent(db, organization: Organization, owner: User, name: str) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=organization.id,
        owner_user_id=owner.id,
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        draft_spec=AgentSpec(name=name).model_dump(mode="json"),
        visibility=Visibility.PRIVATE.value,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _bot(db, organization: Organization, name: str) -> ChannelBot:
    bot = ChannelBot(
        id=uuid.uuid4(),
        organization_id=organization.id,
        platform="telegram",
        name=name,
        token_encrypted="sealed-elsewhere",
    )
    db.add(bot)
    await db.flush()
    return bot


async def _heard(
    db,
    organization: Organization,
    *,
    surface: TranscriptionSurface = "chat",
    seconds: float | None = 60.0,
    agent: Agent | None = None,
    bot: ChannelBot | None = None,
    failed: bool = False,
) -> None:
    """One transcription, written the way every surface writes it (#1797)."""
    await transcription_usage.record(
        db,
        TranscriptionCall(
            organization_id=organization.id,
            surface=surface,
            provider="openai",
            model="whisper-1",
            agent_id=agent.id if agent else None,
            channel_bot_id=bot.id if bot else None,
        ),
        input_bytes=1024,
        audio_seconds=seconds,
        duration_ms=300,
        failure=NotFoundError(message="refused") if failed else None,
    )


class TestTranscriptionUsageStaysInItsOrganization:
    """Every transcription is attributed, and nothing reaches another tenant."""

    async def test_the_summary_adds_up_one_organizations_transcriptions_only(self, db) -> None:
        acme, founder = await _org(db, name="Acme")
        globex, other = await _org(db, name="Globex")
        support = await _agent(db, acme, founder, "Support")
        desk = await _bot(db, acme, "Front desk")
        rival = await _agent(db, globex, other, "Rival")
        await _heard(db, acme, agent=support, seconds=90)
        await _heard(db, acme, surface="channel", agent=support, bot=desk, seconds=30)
        await _heard(db, acme, surface="channel", agent=support, bot=desk, seconds=None)
        await _heard(db, acme, surface="api", seconds=20)
        await _heard(db, acme, agent=support, seconds=500, failed=True)
        await _heard(db, globex, agent=rival, seconds=6000)

        summary = await MLService(db).usage_summary(
            _ctx(acme, founder), service="speech_to_text", days=30
        )

        assert (summary.seconds, summary.count, summary.count_unknown_length) == (140, 4, 1)
        assert [(group.name, group.seconds, group.count) for group in summary.by_agent] == [
            ("Support", 120, 3)
        ]
        assert [(group.name, group.count) for group in summary.by_channel] == [("Front desk", 2)]
        assert {group.surface: group.count for group in summary.by_surface} == {
            "chat": 1,
            "channel": 2,
            "api": 1,
        }

    async def test_the_summary_is_the_sum_of_what_the_listing_says(self, db) -> None:
        """Each row rounds its own length up to the second, and the summary adds
        those up - two 1.2-second notes are 4 seconds in both, not 4 in the
        listing and 2 in the summary."""
        acme, founder = await _org(db, name="Acme")
        await _heard(db, acme, seconds=1.2)
        await _heard(db, acme, seconds=1.2)

        summary = await MLService(db).usage_summary(
            _ctx(acme, founder), service="speech_to_text", days=30
        )
        rows, _ = await MLService(db).call_records(
            _ctx(acme, founder), service="speech_to_text", skip=0, limit=50
        )

        assert summary.seconds == sum(row.units for row in rows) == 4

    async def test_a_filter_on_another_tenants_agent_finds_nothing(self, db) -> None:
        acme, founder = await _org(db, name="Acme")
        globex, other = await _org(db, name="Globex")
        rival = await _agent(db, globex, other, "Rival")
        await _heard(db, globex, agent=rival)

        rows, total = await MLService(db).call_records(
            _ctx(acme, founder), service=None, agent_id=rival.id, skip=0, limit=50
        )

        assert (rows, total) == ([], 0)

    async def test_the_filters_narrow_to_one_bot_and_one_surface(self, db) -> None:
        acme, founder = await _org(db, name="Acme")
        support = await _agent(db, acme, founder, "Support")
        desk = await _bot(db, acme, "Front desk")
        await _heard(db, acme, agent=support)
        await _heard(db, acme, surface="channel", agent=support, bot=desk)

        by_bot, _ = await MLService(db).call_records(
            _ctx(acme, founder), service=None, channel_bot_id=desk.id, skip=0, limit=50
        )
        by_surface, total = await MLService(db).call_records(
            _ctx(acme, founder), service="speech_to_text", surface="chat", skip=0, limit=50
        )

        assert [row.surface for row in by_bot] == ["channel"]
        assert (total, by_surface[0].agent_id) == (1, support.id)

    async def test_deleting_the_agent_keeps_the_row_and_drops_the_link(self, db) -> None:
        acme, founder = await _org(db, name="Acme")
        support = await _agent(db, acme, founder, "Support")
        await _heard(db, acme, agent=support)

        await db.delete(support)
        await db.flush()
        rows, _ = await MLService(db).call_records(
            _ctx(acme, founder), service="speech_to_text", skip=0, limit=50
        )
        await db.refresh(rows[0])

        assert rows[0].agent_id is None
        assert rows[0].audio_ms == 60_000


class TestTheRowKeepsNoneOfWhatWasSubmitted:
    async def test_the_columns_are_the_shape_of_the_call_and_nothing_else(self, db) -> None:
        """A column added here that could hold content fails this test, on purpose."""
        acme, founder = await _org(db, name="Acme")
        row = await _call(db, acme, founder)

        assert set(row.__table__.columns.keys()) == {
            "id",
            "organization_id",
            "requested_by_user_id",
            "service",
            "status",
            "failure_stage",
            "failure_reason",
            "input_bytes",
            "units",
            "unit",
            "duration_ms",
            "provider",
            "model",
            "surface",
            "agent_id",
            "channel_bot_id",
            "secret_id",
            "audio_ms",
            "created_at",
            "updated_at",
        }
