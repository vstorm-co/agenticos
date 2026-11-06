"""The chat reads capabilities from the frozen version rather than the draft."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.agent import (
    published_capabilities,
    published_coding_agents,
    published_local_workspaces,
)
from app.schemas.agent import PublishedCodingAgent

pytestmark = pytest.mark.anyio


async def test_enabled_published_bindings_are_distinct_from_disabled_and_absent_ones() -> None:
    version, old = uuid4(), uuid4()
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.all.return_value = [
        (
            version,
            [
                {"id": "sandbox", "enabled": True},
                {"id": "browser_use", "enabled": False},
                {"id": "computer_use"},
            ],
        ),
        (old, None),
    ]
    db.execute.return_value = result
    assert await published_capabilities(db, version_ids=[version, old]) == {
        version: ["sandbox", "computer_use"],
        old: [],
    }


async def test_no_versions_does_not_query_the_database() -> None:
    db = AsyncMock(spec=AsyncSession)
    assert await published_capabilities(db, version_ids=[]) == {}
    db.execute.assert_not_awaited()


async def test_invalid_frozen_metadata_is_not_disguised_as_disabled_tools() -> None:
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.all.return_value = [(uuid4(), {"invalid": "shape"})]
    db.execute.return_value = result
    with pytest.raises(ValidationError):
        await published_capabilities(db, version_ids=[uuid4()])


async def test_each_enabled_coding_agent_is_reported_with_where_it_runs() -> None:
    local, sandbox, off, none, default = (uuid4() for _ in range(5))
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.all.return_value = [
        (
            local,
            [
                {"id": "sandbox"},
                {
                    "id": "coding_agent",
                    "config": {"runs_on": "this_computer", "harness": "codex", "access": "edit"},
                },
            ],
        ),
        (sandbox, [{"id": "coding_agent", "config": {"harness": "codex"}}]),
        (
            off,
            [{"id": "coding_agent", "enabled": False, "config": {"runs_on": "this_computer"}}],
        ),
        (none, None),
        (default, [{"id": "coding_agent", "config": {"runs_on": "this_computer"}}]),
    ]
    db.execute.return_value = result
    assert await published_coding_agents(db, version_ids=[local, sandbox, off, none, default]) == {
        local: PublishedCodingAgent(harness="codex", runs_on="this_computer", access="edit"),
        sandbox: PublishedCodingAgent(harness="codex"),
        default: PublishedCodingAgent(runs_on="this_computer"),
    }


async def test_no_versions_does_not_ask_which_run_a_coding_agent() -> None:
    db = AsyncMock(spec=AsyncSession)
    assert await published_coding_agents(db, version_ids=[]) == {}
    db.execute.assert_not_awaited()


async def test_only_a_published_sandbox_on_the_persons_computer_is_a_local_workspace() -> None:
    local, service, off, none = (uuid4() for _ in range(4))
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.all.return_value = [
        (local, [{"id": "sandbox", "config": {"backend": "local"}}]),
        (service, [{"id": "sandbox", "config": {"backend": "service"}}]),
        (off, [{"id": "sandbox", "enabled": False, "config": {"backend": "local"}}]),
        (none, None),
    ]
    db.execute.return_value = result
    assert await published_local_workspaces(db, version_ids=[local, service, off, none]) == {local}
    assert await published_local_workspaces(db, version_ids=[]) == set()
