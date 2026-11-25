"""An Improve card for the platform's accept says which agent, attempt and version it means."""

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.deps import AgentDeps
from app.agents.platform_describers import platform_describer
from app.core.permissions import AuthContext
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_improvement_pipeline import _ready_proposal

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


@contextmanager
def _reading(db: AsyncSession) -> Iterator[None]:
    """The describer's own session, as the test's, which sees what the test wrote."""

    @asynccontextmanager
    async def context() -> AsyncIterator[AsyncSession]:
        yield db

    with patch("app.agents.platform_describers.get_db_context", context):
        yield


def _deps(ctx: AuthContext) -> AgentDeps:
    return AgentDeps(organization_id=ctx.organization_id, run_person=ctx.user_id)


async def test_accepting_an_attempt_names_its_agent_verdict_and_the_version_it_publishes(
    db: AsyncSession,
) -> None:
    ctx, agent, ready = await _ready_proposal(db)
    chosen = next(item for item in ready.iterations if item.id == ready.best_iteration_id)
    assert chosen.verdict is not None and ready.next_version is not None
    describe = platform_describer("agenticos_accept_improvement")
    assert describe is not None
    call = {"agent_id": str(agent.id), "session_id": str(ready.id)}

    with _reading(db):
        published = await describe(_deps(ctx), {**call, "publish": True})
        drafted = await describe(_deps(ctx), {**call, "publish": False})

    assert published == {
        "agent": agent.name,
        "attempt": str(chosen.number),
        "verdict": chosen.verdict.value,
        "publish": "yes",
        "version": str(ready.next_version),
    }
    assert drafted is not None
    assert (drafted["publish"], drafted["version"]) == ("no", "")


@pytest.mark.security
async def test_a_session_the_person_cannot_read_leaves_the_card_to_its_arguments(
    db: AsyncSession,
) -> None:
    ctx, agent, _ready = await _ready_proposal(db)
    describe = platform_describer("agenticos_accept_improvement")
    assert describe is not None

    with _reading(db):
        missing = await describe(
            _deps(ctx), {"agent_id": str(agent.id), "session_id": str(uuid.uuid4())}
        )
        nobody = await describe(
            AgentDeps(organization_id=ctx.organization_id, run_person=None),
            {"agent_id": str(agent.id), "session_id": str(uuid.uuid4())},
        )

    assert (missing, nobody) == (None, None)
