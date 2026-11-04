"""The operator can inspect or refresh one organization or all of them."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from click.testing import CliRunner

from app.commands.refresh_assistant import _run, refresh_assistant
from app.core.exceptions import NotFoundError
from app.services.assistant import AssistantRefresh
from app.services.skills import LibraryRefresh

pytestmark = pytest.mark.anyio
PATH = "app.commands.refresh_assistant"


@asynccontextmanager
async def session():
    yield object()


@pytest.mark.parametrize("one", [True, False])
@pytest.mark.parametrize("dry_run", [True, False])
async def test_command_reports_refresh_results_and_passes_options(one, dry_run, capsys):
    org = SimpleNamespace(id=uuid4(), name="Acme")
    result = AssistantRefresh(
        instructions=LibraryRefresh.UPDATE,
        guide=LibraryRefresh.EDITED,
        published_version=2,
        detail="guide edited here",
    )
    with (
        patch(f"{PATH}.get_db_context", session),
        patch(f"{PATH}.organization_repo.get_by_id", AsyncMock(return_value=org)),
        patch(f"{PATH}.organization_repo.list_all", AsyncMock(return_value=[org])),
        patch(f"{PATH}.member_repo.first_owner_id", AsyncMock(return_value=uuid4())),
        patch(f"{PATH}.AssistantService.refresh", AsyncMock(return_value=result)) as refresh,
    ):
        await _run(org.id if one else None, dry_run=dry_run, replace_edited=True)
    assert refresh.call_args.kwargs == {"dry_run": dry_run, "replace_edited": True}
    output = capsys.readouterr().out
    assert "Acme" in output and "instructions=update" in output and "guide=edited" in output
    assert "published version 2" in output and "guide edited here" in output
    assert ("Dry run:" in output) == dry_run


async def test_unknown_organization_fails_explicitly():
    with (
        patch(f"{PATH}.get_db_context", session),
        patch(f"{PATH}.organization_repo.get_by_id", AsyncMock(return_value=None)),
        pytest.raises(NotFoundError, match="Organization not found"),
    ):
        await _run(uuid4(), dry_run=False, replace_edited=False)


async def test_missing_owner_fails_explicitly_for_targeted_refresh() -> None:
    org = SimpleNamespace(id=uuid4(), name="Ownerless")
    with (
        patch(f"{PATH}.get_db_context", session),
        patch(f"{PATH}.organization_repo.get_by_id", AsyncMock(return_value=org)),
        patch(f"{PATH}.member_repo.first_owner_id", AsyncMock(return_value=None)),
        pytest.raises(NotFoundError, match="no owner"),
    ):
        await _run(org.id, dry_run=False, replace_edited=False)


@pytest.mark.parametrize("dry_run", [True, False])
async def test_bulk_refresh_skips_ownerless_organizations_and_continues(
    dry_run: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    before = SimpleNamespace(id=uuid4(), name="Before")
    ownerless = SimpleNamespace(id=uuid4(), name="Ownerless")
    after = SimpleNamespace(id=uuid4(), name="After")
    first_owner, last_owner = uuid4(), uuid4()
    with (
        patch(f"{PATH}.get_db_context", session),
        patch(
            f"{PATH}.organization_repo.list_all", AsyncMock(return_value=[before, ownerless, after])
        ),
        patch(
            f"{PATH}.member_repo.first_owner_id",
            AsyncMock(side_effect=[first_owner, None, last_owner]),
        ),
        patch(
            f"{PATH}.AssistantService.refresh", AsyncMock(return_value=AssistantRefresh())
        ) as refresh,
    ):
        await _run(None, dry_run=dry_run, replace_edited=True)
    assert [call.args[0].organization_id for call in refresh.await_args_list] == [
        before.id,
        after.id,
    ]
    assert [call.args[0].user_id for call in refresh.await_args_list] == [first_owner, last_owner]
    assert all(
        call.kwargs == {"dry_run": dry_run, "replace_edited": True}
        for call in refresh.await_args_list
    )
    output = capsys.readouterr().out
    assert f"Ownerless ({ownerless.id}): skipped (organization has no owner)" in output
    assert f"After ({after.id})" in output


async def test_empty_deployment_has_nothing_to_refresh():
    with (
        patch(f"{PATH}.get_db_context", session),
        patch(f"{PATH}.organization_repo.list_all", AsyncMock(return_value=[])),
    ):
        await _run(None, dry_run=False, replace_edited=False)


def test_click_validates_uuid_and_runs_command():
    with patch(f"{PATH}._run", AsyncMock()) as run:
        result = CliRunner().invoke(refresh_assistant, ["--dry-run", "--replace-edited"])
        assert result.exit_code == 0
        run.assert_awaited_once_with(None, dry_run=True, replace_edited=True)
    assert CliRunner().invoke(refresh_assistant, ["--org", "bad"]).exit_code == 2


async def test_missing_assistant_is_reported_as_skipped(capsys):
    org = SimpleNamespace(id=uuid4(), name="Acme")
    with (
        patch(f"{PATH}.get_db_context", session),
        patch(f"{PATH}.organization_repo.list_all", AsyncMock(return_value=[org])),
        patch(f"{PATH}.member_repo.first_owner_id", AsyncMock(return_value=uuid4())),
        patch(f"{PATH}.AssistantService.refresh", AsyncMock(return_value=AssistantRefresh())),
    ):
        await _run(None, dry_run=False, replace_edited=False)
    assert "instructions=skipped, guide=skipped" in capsys.readouterr().out
