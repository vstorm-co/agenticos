"""Automatic MCP reporting is bound to the live run, not model-supplied identities."""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun
from app.schemas.routine_notifications import RoutineFindingPublish
from app.services.routine_delivery import RoutineFindingService

pytestmark = [pytest.mark.anyio, pytest.mark.security]
SERVICE = "app.services.routine_delivery"


def item() -> RoutineFindingPublish:
    return RoutineFindingPublish(
        key="thread", revision="message-1", title="Review", content="A complete useful draft."
    )


def caller() -> AuthContext:
    return AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="member",
        key_internal=True,
        source_run_id=uuid4(),
        key_scopes=frozenset(),
    )


@pytest.mark.parametrize("kind", ["session", "external", "no_run", "anonymous"])
async def test_a_regular_caller_cannot_impersonate_a_routine(kind: str) -> None:
    ctx = caller()
    ctx = replace(
        ctx,
        **{
            "session": {"key_internal": False},
            "external": {"key_internal": False, "api_key_id": uuid4()},
            "no_run": {"source_run_id": None},
            "anonymous": {"user_id": None},
        }[kind],
    )
    with pytest.raises(AuthorizationError):
        await RoutineFindingService(AsyncMock(spec=AsyncSession)).publish_for_run(ctx, item())


@pytest.mark.parametrize("kind", ["gone", "other_owner", "terminal", "child", "ordinary"])
async def test_run_provenance_is_required_before_any_write(kind: str) -> None:
    ctx = caller()
    run = AgentRun(
        id=ctx.source_run_id,
        user_id=ctx.user_id,
        organization_id=ctx.organization_id,
        agent_id=uuid4(),
        status="running",
        routine_origin_id=uuid4(),
    )
    if kind == "other_owner":
        run.user_id = uuid4()
    if kind == "terminal":
        run.status = "completed"
    if kind == "child":
        run.parent_run_id = uuid4()
    if kind == "ordinary":
        run.routine_origin_id = None
    with patch(
        "app.repositories.agent_run.get_run",
        new=AsyncMock(return_value=None if kind == "gone" else run),
    ) as read:
        with pytest.raises(AuthorizationError):
            await RoutineFindingService(AsyncMock(spec=AsyncSession)).publish_for_run(ctx, item())
        assert read.await_args.kwargs["organization_id"] == ctx.organization_id


@pytest.mark.parametrize(
    "kind, urgent, changed",
    [("trigger", True, True), ("watch", False, True), ("watch", True, False)],
)
async def test_publication_uses_live_owner_origin_and_watch_urgency(
    kind: str, urgent: bool, changed: bool
) -> None:
    ctx = caller()
    run = AgentRun(
        id=ctx.source_run_id,
        user_id=ctx.user_id,
        organization_id=ctx.organization_id,
        agent_id=uuid4(),
        status="running",
        routine_origin_id=uuid4(),
    )
    authority = MagicMock(user_id=ctx.user_id, routine_id=run.routine_origin_id, routine_kind=kind)
    target = uuid4() if changed else None
    service = RoutineFindingService(AsyncMock(spec=AsyncSession))
    with (
        patch("app.repositories.agent_run.get_run", new=AsyncMock(return_value=run)),
        patch(
            "app.services.routine_authority.RoutineAuthority.capture",
            new=AsyncMock(return_value=authority),
        ),
        patch(
            "app.repositories.watch.get_by_id", new=AsyncMock(return_value=MagicMock(urgent=urgent))
        ),
        patch.object(service, "publish", new=AsyncMock(return_value=target)) as publish,
        patch("app.repositories.outcome.count_run_findings", new=AsyncMock(return_value=0)),
    ):
        result = await service.publish_for_run(ctx, item().model_copy(update={"urgent": True}))
    assert result.conversation_id == target
    assert result.status == ("published" if changed else "unchanged_or_muted")
    assert publish.await_args.kwargs["user_id"] == ctx.user_id
    assert publish.await_args.kwargs["origin_id"] == run.routine_origin_id
    assert publish.await_args.kwargs["urgent"] == urgent
    assert publish.await_args.kwargs["notify"] == (kind == "trigger" or urgent)


async def test_revoked_authority_cannot_publish() -> None:
    ctx = caller()
    run = AgentRun(
        id=ctx.source_run_id,
        user_id=ctx.user_id,
        organization_id=ctx.organization_id,
        agent_id=uuid4(),
        status="running",
        routine_origin_id=uuid4(),
    )
    service = RoutineFindingService(AsyncMock(spec=AsyncSession))
    with (
        patch("app.repositories.agent_run.get_run", new=AsyncMock(return_value=run)),
        patch(
            "app.services.routine_authority.RoutineAuthority.capture",
            new=AsyncMock(side_effect=AuthorizationError(message="Stopped")),
        ),
        patch.object(service, "publish", new=AsyncMock()) as publish,
        pytest.raises(AuthorizationError),
    ):
        await service.publish_for_run(ctx, item())
    publish.assert_not_awaited()


@pytest.mark.parametrize("missing", ["authority", "watch"])
async def test_disappeared_routine_cannot_publish(missing: str) -> None:
    ctx = caller()
    run = AgentRun(
        id=ctx.source_run_id,
        user_id=ctx.user_id,
        organization_id=ctx.organization_id,
        agent_id=uuid4(),
        status="running",
        routine_origin_id=uuid4(),
    )
    authority = MagicMock(routine_kind="watch", routine_id=run.routine_origin_id)
    service = RoutineFindingService(AsyncMock(spec=AsyncSession))
    with (
        patch("app.repositories.agent_run.get_run", new=AsyncMock(return_value=run)),
        patch(
            "app.services.routine_authority.RoutineAuthority.capture",
            new=AsyncMock(return_value=None if missing == "authority" else authority),
        ),
        patch("app.repositories.watch.get_by_id", new=AsyncMock(return_value=None)),
        patch.object(service, "publish", new=AsyncMock()) as publish,
        pytest.raises(AuthorizationError),
    ):
        await service.publish_for_run(ctx, item())
    publish.assert_not_awaited()


def test_model_cannot_supply_recipient_and_source_links_cannot_leak_credentials() -> None:
    for extra in (
        {"user_id": str(uuid4())},
        {"run_id": str(uuid4())},
        {"url": "https://secret:password@example.com"},
    ):
        with pytest.raises(ValidationError):
            RoutineFindingPublish.model_validate({**item().model_dump(), **extra})


@pytest.mark.parametrize("bound", [False, True])
async def test_runtime_reporting_adds_only_one_tool_and_preserves_the_published_spec(
    bound: bool,
) -> None:
    from app.agents.spec import AgentSpec, PlatformMcpServerRef
    from app.services.agent_runner import _routine_mcp_refs

    spec = AgentSpec(
        name="Worker",
        mcp_servers=[
            PlatformMcpServerRef(
                account="platform",
                allowed_tools=["list_agents"],
                tool_approval={"list_agents": "required"},
            )
        ]
        if bound
        else [],
    )
    before = spec.model_dump()
    refs = _routine_mcp_refs(spec)
    assert spec.model_dump() == before
    assert len(refs) == 1 and isinstance(refs[0], PlatformMcpServerRef)
    assert refs[0].allowed_tools == (
        ["list_agents", "publish_inbox_finding"] if bound else ["publish_inbox_finding"]
    )
    repeated = _routine_mcp_refs(spec.model_copy(update={"mcp_servers": refs}))
    assert repeated == refs
    if bound:
        assert refs[0].tool_approval == {"list_agents": "required"}
    all_tools = AgentSpec(name="All", mcp_servers=[PlatformMcpServerRef(account="platform")])
    assert _routine_mcp_refs(all_tools) == all_tools.mcp_servers


async def test_implicit_reporting_key_has_no_general_platform_scopes() -> None:
    from app.db.models.api_key import ApiKey
    from app.services.api_key import ApiKeyService

    ctx = caller()
    row = ApiKey(id=uuid4())
    service = ApiKeyService(AsyncMock(spec=AsyncSession))
    with (
        patch.object(
            service, "_mint", new=AsyncMock(return_value=("opaque-local-key", row))
        ) as mint,
        patch("app.repositories.api_key.delete_expired_internal", new=AsyncMock()),
        patch("app.repositories.api_key.update", new=AsyncMock()) as update,
    ):
        assert (
            await service.issue_for_run(ctx, run_id=ctx.source_run_id, reporting_only=True)
            == "opaque-local-key"
        )
    assert mint.await_args.kwargs["scopes"] == []
    assert mint.await_args.kwargs["internal"] is True
    assert update.await_args.kwargs["update_data"] == {"source_run_id": ctx.source_run_id}


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("owner_present", [False, True])
async def test_identity_free_routines_receive_only_reporting_authority(
    bound: bool, fallback: bool, owner_present: bool
) -> None:
    from app.agents.spec import AgentSpec, PlatformMcpServerRef
    from app.services.agent_runner import AgentRunnerService

    ctx = replace(caller(), routine_id=uuid4(), subject_is_publisher_fallback=fallback)
    spec = AgentSpec(
        name="Worker",
        mcp_servers=[PlatformMcpServerRef(account="platform")] if bound else [],
    )
    service = AgentRunnerService(AsyncMock(spec=AsyncSession))
    with (
        patch.object(
            service,
            "_run_owner_context",
            new=AsyncMock(return_value=ctx if owner_present else None),
        ),
        patch(
            "app.services.agent_runner.mint_for_run", new=AsyncMock(return_value="report-key")
        ) as mint,
    ):
        result = await service._platform_credential(spec, ctx, run_id=ctx.source_run_id)
    if not owner_present:
        assert result is None
        mint.assert_not_awaited()
        return
    assert result == "report-key"
    assert mint.await_args.kwargs["reporting_only"] is (not bound or fallback)
    owner = mint.await_args.args[0]
    assert not owner.subject_is_publisher_fallback
    assert owner.key_scopes == frozenset()
