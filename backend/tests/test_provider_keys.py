"""The one check every level names a provider key through (#1797, #54)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.secret_kinds import SecretKind
from app.services.provider_keys import key_problem

pytestmark = pytest.mark.anyio
_MODULE = "app.services.provider_keys"
_ORG = uuid.uuid4()


def _secret(**overrides: object) -> SimpleNamespace:
    values = {"name": "Prod", "kind": "api_key", "purpose": "openai", "visibility": "org"}
    values.update(overrides)
    return SimpleNamespace(**values)


async def _problem(row: object, *, kind: SecretKind, provider: str, feature: str) -> str | None:
    with patch(f"{_MODULE}.organization_secret_repo.get", new=AsyncMock(return_value=row)):
        return await key_problem(
            MagicMock(),
            uuid.uuid4(),
            organization_id=_ORG,
            provider=provider,
            kind=kind,
            feature=feature,
            ctx=None,
        )


async def test_an_azure_key_is_accepted_where_azure_needs_one():
    row = _secret(kind="azure_openai", purpose="azure")
    assert (
        await _problem(
            row, kind=SecretKind.AZURE_OPENAI, provider="azure", feature="voice conversations"
        )
        is None
    )


async def test_an_api_key_is_refused_where_azure_needs_an_azure_key():
    problem = await _problem(
        _secret(purpose="azure"),
        kind=SecretKind.AZURE_OPENAI,
        provider="azure",
        feature="voice conversations",
    )
    assert problem == "'Prod' holds a api_key, and voice conversations need an Azure OpenAI key"


async def test_the_refusal_names_the_feature_and_the_provider():
    problem = await _problem(
        _secret(purpose="groq"),
        kind=SecretKind.API_KEY,
        provider="openai",
        feature="voice conversations",
    )
    assert problem == "'Prod' is a key for groq, and voice conversations run on openai"


async def test_a_private_key_is_refused_without_a_publisher():
    problem = await _problem(
        _secret(visibility="private"),
        kind=SecretKind.API_KEY,
        provider="openai",
        feature="speech to text",
    )
    assert problem is not None and "organization-wide" in problem
