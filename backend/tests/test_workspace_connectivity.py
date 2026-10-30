"""A stopped sandbox reports an external-service failure, not an opaque 500."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.agents.capabilities.sandbox._recording import RecordingWorkspace
from app.core.exceptions import ExternalServiceError
from tests.workspaces import document_workspace

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("operation", ["write_bytes", "working_dir"])
async def test_network_failure_is_explicit_without_forgetting_the_session(operation: str) -> None:
    wrapped = document_workspace()
    setattr(wrapped, operation, AsyncMock(side_effect=httpx.ConnectError("DNS unavailable")))
    recorder = RecordingWorkspace(
        wrapped, db=MagicMock(), organization_id=uuid.uuid4(), session_key="demo", agent_id=None
    )
    with pytest.raises(ExternalServiceError, match="sandbox service is unreachable"):
        if operation == "write_bytes":
            await recorder.write_bytes("/demo.txt", b"demo")
        else:
            await recorder.working_dir()
    assert not recorder.lost
    assert not recorder.mismatched
