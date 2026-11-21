"""Operator refresh is explicit, scoped, queued, and does not call a model in the CLI."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from click.testing import CliRunner

from app.commands.refresh_inbox import _refresh, refresh_inbox


@pytest.mark.anyio
@pytest.mark.parametrize("queue", [False, True])
async def test_plan_and_explicit_queue_use_only_the_named_organization(queue, capsys):
    organization_id, person_id, job_id = uuid4(), uuid4(), uuid4()
    db = MagicMock()

    @asynccontextmanager
    async def session():
        yield db

    service = MagicMock(queue_open_refresh=AsyncMock(return_value=[job_id]))
    with (
        patch("app.commands.refresh_inbox.get_worker_db_context", new=session),
        patch(
            "app.commands.refresh_inbox.suggestion_repo.open_generated_people",
            new=AsyncMock(return_value={person_id: 3}),
        ) as candidates,
        patch("app.commands.refresh_inbox.ProactiveService", return_value=service),
    ):
        await _refresh(organization_id, queue=queue)
    candidates.assert_awaited_once_with(db, organization_id=organization_id)
    output = capsys.readouterr().out
    assert "3 open generated proposals for 1 people" in output
    if queue:
        service.queue_open_refresh.assert_awaited_once_with(organization_id)
        assert str(job_id) in output
    else:
        service.queue_open_refresh.assert_not_awaited()
        assert "Plan only" in output


@pytest.mark.parametrize("queue", [False, True])
def test_command_requires_an_organization_and_queues_only_when_explicit(queue):
    organization_id = uuid4()
    args = ["--organization-id", str(organization_id), *(["--queue"] if queue else [])]
    with patch("app.commands.refresh_inbox._refresh", new=AsyncMock()) as run:
        result = CliRunner().invoke(refresh_inbox, args)
    assert result.exit_code == 0, result.output
    run.assert_awaited_once_with(organization_id, queue=queue)
    assert CliRunner().invoke(refresh_inbox, []).exit_code != 0
