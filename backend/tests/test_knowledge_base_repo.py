"""Resolving a collection name to the right organization's knowledge base.

`collection_name` is not unique across tenants, so resolving one by name alone
can return another organization's row - and then unseal and bill that
organization's key (#913). `get_for_collection` narrows by organization in two
passes: the caller's own row wins, and an `app`-scoped row (owned by no
organization) is the shared fallback.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.repositories import knowledge_base as kb_repo

pytestmark = pytest.mark.anyio


def _kb(organization_id: uuid.UUID | None) -> MagicMock:
    kb = MagicMock()
    kb.organization_id = organization_id
    return kb


async def _resolve(candidates: list[MagicMock], organization_id: uuid.UUID | None) -> MagicMock:
    with patch.object(kb_repo, "list_by_collection_name", new=AsyncMock(return_value=candidates)):
        return await kb_repo.get_for_collection(MagicMock(), "shared", organization_id)


async def test_a_shared_name_resolves_to_the_callers_own_organization() -> None:
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    a, b = _kb(org_a), _kb(org_b)

    assert await _resolve([a, b], org_a) is a
    assert await _resolve([a, b], org_b) is b


async def test_an_organization_without_its_own_row_never_gets_anothers() -> None:
    """The security property: org B resolving a name only org A holds gets
    nothing, not org A's key."""
    only_a = _kb(uuid.uuid4())

    assert await _resolve([only_a], uuid.uuid4()) is None


async def test_an_app_scoped_row_is_the_shared_fallback() -> None:
    """A collection owned by no organization is matched on the second pass, so an
    organization with no row of its own still resolves the deployment-wide one."""
    app_kb = _kb(None)

    assert await _resolve([app_kb], uuid.uuid4()) is app_kb


async def test_an_organizations_own_row_wins_over_an_app_scoped_one() -> None:
    org = uuid.uuid4()
    app_kb, own = _kb(None), _kb(org)

    assert await _resolve([app_kb, own], org) is own


async def test_no_tenant_takes_the_first_candidate() -> None:
    """`organization_id=None` is a CLI ingest with no tenant to scope to, where
    the old name-only behaviour stands."""
    first, second = _kb(uuid.uuid4()), _kb(uuid.uuid4())

    assert await _resolve([first, second], None) is first
