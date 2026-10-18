"""B64 — shop llm-generate."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BadRequestError
from app.schemas.shop_llm_generate import ShopLlmGenerateIn, ShopLlmGenerateLlmResult
from app.services.shop_llm_generate import ShopLlmGenerateService

pytestmark = pytest.mark.anyio


async def test_generate_returns_body() -> None:
    svc = ShopLlmGenerateService()
    mock_run = MagicMock()
    mock_run.output = ShopLlmGenerateLlmResult(body="Hello shopper", subject=None)

    with (
        patch.object(svc, "_agent") as mock_agent_factory,
        patch("app.services.shop_llm_generate.shop_llm_generate_configured", return_value=True),
    ):
        agent = MagicMock()
        agent.run = AsyncMock(return_value=mock_run)
        mock_agent_factory.return_value = agent
        out = await svc.generate(ShopLlmGenerateIn(prompt="Say hi", include_subject=False))

    assert out.body == "Hello shopper"
    assert out.subject is None


async def test_generate_rejects_forbidden_html() -> None:
    svc = ShopLlmGenerateService()
    mock_run = MagicMock()
    mock_run.output = ShopLlmGenerateLlmResult(body="<script>alert(1)</script>", subject=None)

    with (
        patch.object(svc, "_agent") as mock_agent_factory,
        patch("app.services.shop_llm_generate.shop_llm_generate_configured", return_value=True),
    ):
        agent = MagicMock()
        agent.run = AsyncMock(return_value=mock_run)
        mock_agent_factory.return_value = agent
        with pytest.raises(BadRequestError, match="forbidden"):
            await svc.generate(ShopLlmGenerateIn(prompt="bad", include_subject=False))


async def test_generate_requires_api_key() -> None:
    svc = ShopLlmGenerateService()
    with patch("app.services.shop_llm_generate.shop_llm_generate_configured", return_value=False):
        with pytest.raises(BadRequestError, match="not configured"):
            await svc.generate(ShopLlmGenerateIn(prompt="Hi there", include_subject=False))
