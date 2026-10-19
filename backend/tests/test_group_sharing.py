"""Every kind a department can be given, loaded and named the same way (#2072)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.permissions import AuthContext
from app.services.group_sharing import GroupSharingService, _name

pytestmark = pytest.mark.anyio

MODULE = "app.services.group_sharing"
ORG = uuid.uuid4()
CTX = AuthContext(user_id=uuid.uuid4(), organization_id=ORG, role="owner")


@pytest.mark.parametrize(
    ("kind", "repo", "function"),
    [
        ("agent", "agent_repo", "get_many"),
        ("skill", "skill_repo", "get_many"),
        ("context", "context_repo", "get_many"),
        ("artifact", "artifact_repo", "get_many"),
        ("mcp_connection", "mcp_connection_repo", "get_org_scoped_by_ids"),
    ],
)
async def test_each_kind_is_loaded_inside_the_organization(
    kind: str, repo: str, function: str
) -> None:
    row_id = uuid.uuid4()
    row = MagicMock()
    with patch(f"{MODULE}.{repo}.{function}", AsyncMock(return_value={row_id: row})) as load:
        found = await GroupSharingService(MagicMock())._load(CTX, kind, [row_id])

    assert found == {row_id: row}
    assert ORG in load.await_args.kwargs.values()


async def test_a_knowledge_base_from_another_organization_is_not_found() -> None:
    ours, theirs = uuid.uuid4(), uuid.uuid4()
    rows = {ours: MagicMock(organization_id=ORG), theirs: MagicMock(organization_id=uuid.uuid4())}
    with patch(f"{MODULE}.knowledge_base_repo.get_by_ids", AsyncMock(return_value=rows)):
        found = await GroupSharingService(MagicMock())._load(CTX, "collection", [ours, theirs])

    assert list(found) == [ours]


async def test_a_caller_with_no_person_behind_it_is_offered_nothing() -> None:
    nobody = AuthContext(user_id=None, organization_id=ORG, role="owner")
    assert await GroupSharingService(MagicMock())._candidates(nobody) == {}


def test_a_row_is_named_by_its_title_label_or_name_and_else_its_id() -> None:
    row_id = uuid.uuid4()
    assert _name(SimpleNamespace(id=row_id, title="Close checklist")) == "Close checklist"
    assert _name(SimpleNamespace(id=row_id, label="", name="ledger")) == "ledger"
    assert _name(SimpleNamespace(id=row_id)) == str(row_id)


def test_a_notice_names_an_app_by_title_and_anything_nameless_by_its_id() -> None:
    from app.services.sharing import _shown_name

    row_id = uuid.uuid4()
    assert _shown_name(SimpleNamespace(id=row_id, title="Close checklist", name="close")) == (
        "Close checklist"
    )
    assert _shown_name(SimpleNamespace(id=row_id, name="ledger")) == "ledger"
    assert _shown_name(SimpleNamespace(id=row_id)) == str(row_id)
