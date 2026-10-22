"""A usage row that cannot be written must not take the channel turn down with it (#1797).

`transcription_usage.record` writes into the caller's transaction - for a
channel voice note, the router's turn, which goes on to store the identity,
the session and the chat files and is committed by the run. An agent deleted
mid-turn breaks the row's foreign key, and on a real database a failed flush
aborts the whole transaction: the next statement raises
`InFailedSqlTransaction` however carefully the error was caught. The SAVEPOINT
`record` opens is what confines the failure to the row.

A mocked session cannot be put into an aborted transaction, so the unit tests in
`tests/test_transcription_usage.py` prove what is written and this proves the
session survives what is not.
"""

import uuid

import pytest
from sqlalchemy import select

from app.db.models.ml_service_call import MLServiceCall
from app.db.models.organization import Organization
from app.db.models.user import User
from app.services import transcription_usage
from app.services.transcription_usage import TranscriptionCall

pytestmark = pytest.mark.anyio


async def _organization(db) -> Organization:
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
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


def _call(organization: Organization, *, agent_id: uuid.UUID | None) -> TranscriptionCall:
    return TranscriptionCall(
        organization_id=organization.id,
        surface="channel",
        provider="openai",
        model="whisper-1",
        agent_id=agent_id,
    )


async def test_a_row_for_a_vanished_agent_fails_alone_and_the_turn_still_commits(db) -> None:
    organization = await _organization(db)

    lost = await transcription_usage.record(
        db,
        _call(organization, agent_id=uuid.uuid4()),
        input_bytes=1024,
        audio_seconds=2.0,
        duration_ms=300,
    )
    # The statement that raises without the savepoint: the turn's own next
    # write, and the commit the run would make.
    kept = await transcription_usage.record(
        db,
        _call(organization, agent_id=None),
        input_bytes=2048,
        audio_seconds=3.0,
        duration_ms=400,
    )
    await db.commit()

    assert lost is None
    assert kept is not None
    rows = (
        (
            await db.execute(
                select(MLServiceCall).where(MLServiceCall.organization_id == organization.id)
            )
        )
        .scalars()
        .all()
    )
    assert [(row.input_bytes, row.audio_ms) for row in rows] == [(2048, 3000)]
