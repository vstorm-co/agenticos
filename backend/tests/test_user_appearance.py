"""Account appearance never follows an organization's shared agent identity."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.schemas.user_appearance import UserAppearance
from app.services.user_appearance import UserAppearanceService

pytestmark = pytest.mark.anyio


@pytest.fixture
def ctx():
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")


@pytest.fixture
def dependencies(ctx):
    account = SimpleNamespace(id=ctx.user_id, appearance=None)
    conversation = SimpleNamespace(
        id=uuid4(),
        user_id=ctx.user_id,
        organization_id=ctx.organization_id,
        project_id=None,
        workflow_id=None,
        origin=None,
    )
    with (
        patch("app.services.user_appearance.user_repo.get_by_id", new_callable=AsyncMock) as read,
        patch(
            "app.services.user_appearance.user_repo.get_by_id_for_update", new_callable=AsyncMock
        ) as lock,
        patch("app.services.user_appearance.user_repo.update", new_callable=AsyncMock) as write,
        patch(
            "app.services.user_appearance.conversation_repo.get_conversation_by_id",
            new_callable=AsyncMock,
        ) as source,
        patch(
            "app.services.user_appearance.conversation_repo.channel_thread_ids",
            new_callable=AsyncMock,
        ) as channels,
        patch(
            "app.services.user_appearance.conversation_share_repo.get_shares_for_conversation",
            new_callable=AsyncMock,
        ) as shares,
        patch("app.services.user_appearance.record_audit", new_callable=AsyncMock) as audit,
    ):
        read.return_value = account
        lock.return_value = account
        source.return_value = conversation
        channels.return_value = set()
        shares.return_value = []
        yield SimpleNamespace(
            account=account,
            conversation=conversation,
            read=read,
            lock=lock,
            write=write,
            source=source,
            channels=channels,
            shares=shares,
            audit=audit,
        )


async def test_defaults_and_saved_preferences_follow_the_account(ctx, dependencies):
    service = UserAppearanceService(AsyncMock())
    assert await service.get(ctx) == UserAppearance()
    dependencies.account.appearance = {"theme": "dark", "accent": "violet"}
    saved = await service.get(replace(ctx, organization_id=uuid4()))
    assert saved.theme == "dark" and saved.accent == "violet"
    assert saved.motion == "system"
    assert dependencies.read.await_args.args[1] == ctx.user_id


async def test_patch_keeps_omitted_values_and_audits_only_changed_names(ctx, dependencies):
    dependencies.account.appearance = {"theme": "dark", "motion": "reduce"}
    saved = await UserAppearanceService(AsyncMock()).update(
        ctx, UserAppearance(accent="blue", text_size="large")
    )
    assert saved.theme == "dark" and saved.motion == "reduce"
    assert saved.accent == "blue" and saved.text_size == "large"
    assert dependencies.write.await_args.kwargs["db_user"].id == ctx.user_id
    assert dependencies.write.await_args.kwargs["update_data"] == {"appearance": saved.model_dump()}
    assert dependencies.audit.await_args.kwargs["details"] == {"fields": ["accent", "text_size"]}
    assert dependencies.lock.await_args.args[1] == ctx.user_id


async def test_reset_removes_only_this_users_saved_appearance(ctx, dependencies):
    dependencies.account.appearance = {"look": "paper"}
    reset = await UserAppearanceService(AsyncMock()).reset(ctx)
    assert reset == UserAppearance()
    assert dependencies.write.await_args.kwargs["update_data"] == {"appearance": None}
    assert dependencies.write.await_args.kwargs["db_user"].id == ctx.user_id
    assert dependencies.audit.await_args.kwargs["action"] == "user.appearance_reset"


@pytest.mark.security
@pytest.mark.parametrize(
    "field,value",
    [
        ("user_id", None),
        ("subject_is_publisher_fallback", True),
        ("fired_as_creator", "schedule"),
        ("fired_as_creator", "event"),
        ("routine_id", "00000000-0000-4000-8000-000000000001"),
        ("is_workflow", True),
        ("channel_identity_id", "00000000-0000-4000-8000-000000000001"),
        ("is_impersonated", True),
        ("key_internal", True),
    ],
)
async def test_ambiguous_or_unattended_identity_cannot_read_or_write(
    ctx, dependencies, field, value
):
    denied = replace(ctx, **{field: value})
    service = UserAppearanceService(AsyncMock())
    for operation in (
        service.get(denied),
        service.update(denied, UserAppearance(theme="dark")),
        service.reset(denied),
    ):
        with pytest.raises(AuthorizationError):
            await operation
    dependencies.read.assert_not_awaited()
    dependencies.write.assert_not_awaited()


@pytest.mark.security
async def test_impersonation_context_cannot_change_preferences(ctx, dependencies):
    with (
        patch("app.services.user_appearance.current_impersonator", return_value=uuid4()),
        pytest.raises(AuthorizationError),
    ):
        await UserAppearanceService(AsyncMock()).update(ctx, UserAppearance(theme="dark"))
    dependencies.write.assert_not_awaited()


async def test_private_agent_and_personal_mcp_credentials_reach_the_same_account(ctx, dependencies):
    service = UserAppearanceService(AsyncMock())
    agent = replace(
        ctx,
        api_key_id=uuid4(),
        key_internal=True,
        source_conversation_id=dependencies.conversation.id,
        key_scopes=frozenset({Perm.AGENTS_RUN}),
    )
    assert await service.update(agent, UserAppearance(radius="rounded")) == UserAppearance(
        radius="rounded"
    )
    mcp = replace(ctx, api_key_id=uuid4(), key_scopes=frozenset({Perm.AGENTS_RUN}))
    assert await service.get(mcp) == UserAppearance()


@pytest.mark.security
@pytest.mark.parametrize(
    "field",
    [
        "user_id",
        "organization_id",
        "project_id",
        "workflow_id",
        "origin",
        "missing",
        "channel",
        "shared",
    ],
)
async def test_agent_source_must_be_owned_private_and_in_the_credential_tenant(
    ctx, dependencies, field
):
    if field == "missing":
        dependencies.source.return_value = None
    elif field == "channel":
        dependencies.channels.return_value = {dependencies.conversation.id}
    elif field == "shared":
        dependencies.shares.return_value = [SimpleNamespace(permission="read")]
    else:
        setattr(dependencies.conversation, field, "api" if field == "origin" else uuid4())
    agent = replace(ctx, key_internal=True, source_conversation_id=dependencies.conversation.id)
    with pytest.raises(AuthorizationError):
        await UserAppearanceService(AsyncMock()).update(agent, UserAppearance(theme="dark"))
    dependencies.write.assert_not_awaited()


@pytest.mark.security
async def test_deleted_account_is_not_recreated(ctx, dependencies):
    dependencies.read.return_value = None
    dependencies.lock.return_value = None
    service = UserAppearanceService(AsyncMock())
    with pytest.raises(NotFoundError):
        await service.get(ctx)
    with pytest.raises(NotFoundError):
        await service.reset(ctx)
    dependencies.write.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize(
    "payload",
    [
        {"user_id": "someone-else"},
        {"css": "body{display:none}"},
        {"accent": "url(https://example.com)"},
        {"radius": "999999px"},
        {"theme": None},
        {"look": "unknown"},
        {"text_size": "0px"},
    ],
)
async def test_only_closed_tokens_are_accepted(payload):
    with pytest.raises(ValidationError):
        UserAppearance.model_validate(payload)
