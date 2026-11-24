"""Deployment availability never erases the permanent media node contract."""

from unittest.mock import Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.workflow_registry import WorkflowRegistryService

pytestmark = pytest.mark.anyio


async def test_media_definition_survives_disable_with_an_unavailable_add_state(monkeypatch):
    db = Mock(spec=AsyncSession)
    service = WorkflowRegistryService(db)
    monkeypatch.setattr(settings, "WORKFLOW_ASSET_INPUT_ENABLED", False)
    disabled = await service.node_catalog()
    asset = next(item for item in disabled.items if item.id == "asset.input")
    assert asset.available is False and asset.version == 1
    assert asset.output_schema["properties"]["file"]["$ref"].endswith("FileRef")
    assert next(item for item in disabled.items if item.id == "file.read").available is True
    monkeypatch.setattr(settings, "WORKFLOW_ASSET_INPUT_ENABLED", True)
    enabled = await service.node_catalog()
    active = next(item for item in enabled.items if item.id == "asset.input")
    assert active.available is True
    assert active.model_dump(exclude={"available"}) == asset.model_dump(exclude={"available"})
    db.execute.assert_not_called()
