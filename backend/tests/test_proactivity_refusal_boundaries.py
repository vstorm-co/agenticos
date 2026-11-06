"""Unattended authorities and missing credentials cannot borrow human consent."""

from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai.workspaces import WorkspaceUnavailableError

from app.core.permissions import AuthContext
from app.services.approvals import ApprovalService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_an_anonymous_context_cannot_remember_a_tool_consent() -> None:
    ctx = AuthContext(user_id=None, organization_id=uuid4(), role="owner")
    service = ApprovalService(AsyncMock())
    assert not await service._may_remember(ctx)
    assert await service.list_consents(ctx) == []
    assert await service.list_consents(replace(ctx, user_id=uuid4(), api_key_id=uuid4())) == []


async def test_a_malformed_person_scope_does_not_lock_an_invented_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.memory import _claims

    locked = AsyncMock()
    monkeypatch.setattr(_claims, "hold_subject", locked)
    await _claims._hold_person(AsyncMock(), "person:not-a-uuid")
    locked.assert_not_awaited()


async def test_a_remote_agent_without_its_credential_cannot_be_reviewed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models.external_agent import ExternalAgent
    from app.repositories import organization_secret_repo
    from app.services.routine_sources import RoutineSourcesRequired, external_fingerprint

    monkeypatch.setattr(
        organization_secret_repo, "authorization_generation", AsyncMock(return_value=None)
    )
    with pytest.raises(RoutineSourcesRequired, match="credential is unavailable"):
        await external_fingerprint(
            AsyncMock(), ExternalAgent(secret_id=uuid4(), organization_id=uuid4())
        )


async def test_machine_inbox_access_requires_an_explicit_private_conversation() -> None:
    from app.core.exceptions import AuthorizationError
    from app.services.outcome import OutcomeService

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner", key_scopes=())
    with pytest.raises(AuthorizationError, match="private chat"):
        await OutcomeService(AsyncMock())._require_private_chat(ctx)


@pytest.mark.parametrize("grant", ["computer", "routine"])
def test_native_folder_grants_require_their_original_conversation_or_scope(grant: str) -> None:
    from app.schemas.local_target import LocalOperations, LocalTarget
    from app.services.device_hub.workspace import DeviceWorkspace

    target = (
        LocalTarget(folder="/approved", mode="full_access", computer_grant=uuid4())
        if grant == "computer"
        else LocalTarget(
            folder="/approved",
            routine_grant=uuid4(),
            device_id=uuid4(),
            mode="read_only",
            operations=LocalOperations(),
        )
    )
    with pytest.raises(WorkspaceUnavailableError):
        DeviceWorkspace(uuid4(), uuid4(), target)


async def test_nonchat_notification_channel_is_an_explicit_programming_error() -> None:
    from app.schemas.notification import NotificationChannel, NotificationEventType
    from app.services.notification_center import NotificationCenterService

    with pytest.raises(ValueError, match="Not a chat"):
        await NotificationCenterService(AsyncMock()).chat_channel_enabled(
            uuid4(), NotificationEventType.RUN_COMPLETED, NotificationChannel.EMAIL
        )


@pytest.mark.parametrize(
    "change", ["target_device", "scope_device", "person", "grant", "operations"]
)
def test_a_routine_folder_scope_cannot_be_borrowed_by_another_native_session(change):
    from app.schemas.local_target import LocalOperations, LocalTarget, RoutineLocalScope
    from app.services.device_hub.workspace import DeviceWorkspace

    device, person, grant = uuid4(), uuid4(), uuid4()
    operations = LocalOperations()
    target = LocalTarget(
        folder="/approved",
        device_id=device,
        routine_grant=grant,
        mode="read_only",
        operations=operations,
    )
    scope = RoutineLocalScope(
        grant_id=grant,
        organization_id=uuid4(),
        routine_id=uuid4(),
        user_id=person,
        device_id=device,
        operations=operations,
    )
    if change == "target_device":
        target = target.model_copy(update={"device_id": uuid4()})
    elif change == "scope_device":
        scope.device_id = uuid4()
    elif change == "person":
        scope.user_id = uuid4()
    elif change == "grant":
        scope.grant_id = uuid4()
    else:
        scope.operations = operations.model_copy(update={"write": True})
    with pytest.raises(WorkspaceUnavailableError, match="does not match"):
        DeviceWorkspace(device, person, target, routine_scope=scope)


async def test_project_metadata_admission_requires_current_project_use_permission(monkeypatch):
    from unittest.mock import MagicMock

    from app.core.exceptions import AuthorizationError
    from app.services import project

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    service = project.ProjectService(AsyncMock())
    service.get = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(project, "resolve_access", AsyncMock(return_value=False))
    with pytest.raises(AuthorizationError, match="no longer work"):
        await service.source_for_routine(ctx, uuid4())
