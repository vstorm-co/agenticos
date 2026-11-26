"""Naming a keyed embedding connection needs `connections:view`.

A connection that carries a Vault key spends it on every call. A base exposes
its `embedding_endpoint_id` to anyone who can read it, so without this a Member
(who holds `collections:edit` but not `connections:view`) could name that id for
a new base, a move or a Test, and send requests on a key never shared with them.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.services.knowledge_base import KnowledgeBaseService
from app.services.rag import embedding_providers

pytestmark = pytest.mark.anyio


def _ctx(role: str) -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)


def _row(*, keyed: bool) -> SimpleNamespace:
    return SimpleNamespace(
        name="Gateway",
        kind="embedding",
        provider="openai_compatible",
        is_active=True,
        secret_id=uuid.uuid4() if keyed else None,
    )


async def _check(row: SimpleNamespace, role: str) -> None:
    provider = embedding_providers.get("openai_compatible")
    assert provider is not None
    with patch(
        "app.services.knowledge_base.service_connection_repo.get_visible",
        AsyncMock(return_value=row),
    ):
        await KnowledgeBaseService(MagicMock())._check_embedding_endpoint(
            uuid.uuid4(), organization_id=uuid.uuid4(), provider=provider, ctx=_ctx(role)
        )


@pytest.mark.security
async def test_a_member_cannot_name_a_keyed_connection() -> None:
    with pytest.raises(BadRequestError) as refused:
        await _check(_row(keyed=True), OrgRoleName.MEMBER.value)

    assert refused.value.details["fields"][0]["field"] == "embedding_endpoint_id"
    assert "connections permission" in refused.value.message


@pytest.mark.parametrize(
    ("keyed", "role"),
    [
        (True, OrgRoleName.OWNER.value),
        (False, OrgRoleName.MEMBER.value),
    ],
)
async def test_whoever_may_list_connections_or_a_keyless_one_is_accepted(
    keyed: bool, role: str
) -> None:
    await _check(_row(keyed=keyed), role)
