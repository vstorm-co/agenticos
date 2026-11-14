"""Opt-in channel participation owns its scope, cadence and native delivery receipts."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError
from app.db.models.agent import Agent
from app.db.models.agent_exposure import AgentExposure
from app.db.models.background_job import BackgroundJob
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_observation import ChannelObservation
from app.repositories import channel_observation as repo
from app.schemas.channel_observer import ChannelObservationConfig, ObservedChannelMessage
from app.services.channels.base import IncomingMessage
from app.services.channels.observation import (
    _authority,
    admission_fingerprint,
    analyze,
    classifier_spec,
    observe,
    sweep,
)
from app.worker.jobs import AnalyzeChannel
from tests.integration.workflow_run_support import seed_member

pytestmark = [pytest.mark.anyio, pytest.mark.security]
NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)


async def world(db: AsyncSession) -> tuple[AgentExposure, ChannelBot]:
    user, org = await seed_member(db)
    agent = Agent(
        organization_id=org.id,
        owner_user_id=user.id,
        name="Helper",
        slug=f"helper-{uuid4()}",
        status="published",
    )
    bot = ChannelBot(
        organization_id=org.id,
        platform="mattermost",
        name="Test",
        token_encrypted="unused",
        is_active=True,
    )
    db.add_all([agent, bot])
    await db.flush()
    exposure = AgentExposure(
        organization_id=org.id,
        agent_id=agent.id,
        channel_bot_id=bot.id,
        surface=bot.platform,
        is_active=True,
        observation_user_id=user.id,
        observation=ChannelObservationConfig(
            enabled=True,
            model_profile_id=uuid4(),
        ).model_dump(mode="json"),
    )
    db.add(exposure)
    await db.flush()
    return exposure, bot


async def append(
    db: AsyncSession,
    exposure: AgentExposure,
    identifier: str = "m1",
    *,
    addressed: bool = False,
    now: datetime = NOW,
) -> None:
    bot = await db.get(ChannelBot, exposure.channel_bot_id)
    assert bot is not None
    await repo.append(
        db,
        exposure=exposure,
        platform_chat_id="room:thread",
        message=ObservedChannelMessage(
            message_id=identifier, author_id="human", text="Question", received_at=now
        ),
        addressed=addressed,
        unmentioned_minutes=20,
        mentioned_minutes=1,
        admission_hash=admission_fingerprint(bot),
    )


async def payload_for(db: AsyncSession, exposure: AgentExposure) -> AnalyzeChannel:
    await sweep(db, now=NOW + timedelta(minutes=20))
    window = (await db.scalars(select(ChannelObservation))).one()
    return AnalyzeChannel(
        organization_id=exposure.organization_id,
        observation_id=window.id,
        generation=window.generation,
        admission_hash=window.admission_hash,
        revision=window.checked_revision,
        messages=window.messages,
    )


async def test_receipt_and_window_are_bounded_and_duplicate_safe(db: AsyncSession):
    exposure, _ = await world(db)
    for index in range(25):
        await append(db, exposure, f"m{index}")
    await append(db, exposure, "m24")
    window = (await db.scalars(select(ChannelObservation))).one()
    assert window.revision == 25 and len(window.messages) == 20
    assert window.messages[0]["message_id"] == "m5"
    assert await repo.get(db, observation_id=window.id, organization_id=uuid4()) is None
    assert await sweep(db, now=NOW + timedelta(minutes=19)) == 0
    assert await sweep(db, now=NOW + timedelta(minutes=20)) == 1
    assert await sweep(db, now=NOW + timedelta(minutes=40)) == 0
    job = (await db.scalars(select(BackgroundJob))).one()
    assert job.max_attempts == 1 and job.organization_id == exposure.organization_id


async def test_mentioned_thread_uses_shorter_interval_and_supersedes_queued_reply(db: AsyncSession):
    exposure, _ = await world(db)
    await append(db, exposure)
    payload = await payload_for(db, exposure)
    await append(db, exposure, "mention", addressed=True, now=NOW + timedelta(minutes=20))
    with pytest.raises(AuthorizationError):
        await _authority(db, payload)
    assert await sweep(db, now=NOW + timedelta(minutes=21)) == 0
    await append(db, exposure, "followup", now=NOW + timedelta(minutes=20, seconds=30))
    assert await sweep(db, now=NOW + timedelta(minutes=21)) == 1


@pytest.mark.parametrize("change", ["generation", "disable", "bot", "account", "binding"])
async def test_revocation_is_live_before_model_or_delivery(db: AsyncSession, change: str):
    exposure, bot = await world(db)
    await append(db, exposure)
    payload = await payload_for(db, exposure)
    if change == "generation":
        exposure.observation_generation = uuid4()
    elif change == "disable":
        exposure.observation = {}
    elif change == "bot":
        bot.is_active = False
    elif change == "account":
        exposure.observation_user_id = None
    elif change == "binding":
        exposure.is_active = False
    await db.flush()
    with pytest.raises(AuthorizationError):
        await _authority(db, payload)


@pytest.mark.parametrize("case", ["disabled", "private", "empty", "no_id", "email"])
async def test_collection_is_opt_in_and_scoped(db: AsyncSession, case: str):
    exposure, bot = await world(db)
    incoming = IncomingMessage(
        platform="mattermost",
        bot_id=str(bot.id),
        platform_user_id="human",
        platform_chat_id="room:thread",
        chat_type="group",
        text="A useful question",
        message_id="m1",
    )
    if case == "disabled":
        exposure.observation = {}
    elif case == "private":
        incoming.chat_type = "private"
    elif case == "empty":
        incoming.text = " "
    elif case == "email":
        incoming.platform = "email"
    else:
        incoming.message_id = None
    await db.flush()
    await observe(db, bot, incoming, addressed=False)
    assert list((await db.scalars(select(ChannelObservation))).all()) == []


async def test_classifier_can_stay_silent_without_running_full_agent(db: AsyncSession):
    exposure, _ = await world(db)
    await append(db, exposure)
    payload = await payload_for(db, exposure)

    async def execute(ctx, agent_id, prompt, **kwargs: object):
        structured = kwargs["structured"]
        assert isinstance(structured, list)
        structured.append({"score": 0, "reason": "Already answered"})
        assert ctx.subject_is_publisher_fallback
        return "", SimpleNamespace(id=uuid4(), status="completed")

    with (
        patch(
            "app.services.channels.observation.AgentRunnerService.execute",
            new=AsyncMock(side_effect=execute),
        ) as run,
        patch(
            "app.services.channels.observation.AgentRegistryService.get_runnable_spec",
            new=AsyncMock(return_value=(None, AgentSpec(name="Helper"), uuid4())),
        ),
    ):
        assert await analyze(db, payload) is False
    assert run.await_count == 1


@pytest.mark.parametrize(
    "mode,assessment,threshold,joins",
    [
        ("llm", 100, 80, True),
        ("llm", 80, 80, True),
        ("llm", 79, 80, False),
        ("llm", 0, 0, True),
        ("native", 0.8, 80, True),
        ("native", 0.79, 80, False),
        ("native", 1.0, 100, True),
    ],
)
async def test_positive_decision_uses_main_model_and_replies_once(
    db: AsyncSession, mode: str, assessment: float, threshold: int, joins: bool
):
    exposure, _ = await world(db)
    exposure.observation = {
        **exposure.observation,
        "decision_mode": mode,
        "threshold_percent": threshold,
    }
    await db.flush()
    await append(db, exposure)
    payload = await payload_for(db, exposure)
    main_model = uuid4()
    spec = AgentSpec(name="Helper", instructions="Be concrete", model_profile_id=main_model)
    calls = []

    async def execute(ctx, agent_id, prompt, **kwargs: object):
        candidate = kwargs["candidate"]
        calls.append(candidate)
        assert ctx.subject_is_publisher_fallback
        structured = kwargs.get("structured")
        if isinstance(structured, list):
            structured.append(
                {"probability": assessment}
                if mode == "native"
                else {"score": assessment, "reason": "Useful unanswered question"}
            )
        return "Here is a useful answer", SimpleNamespace(id=uuid4(), status="completed")

    adapter = SimpleNamespace(send_message=AsyncMock())
    with (
        patch(
            "app.services.channels.observation.AgentRunnerService.execute",
            new=AsyncMock(side_effect=execute),
        ),
        patch(
            "app.services.channels.observation.AgentRegistryService.get_runnable_spec",
            new=AsyncMock(return_value=(None, spec, uuid4())),
        ),
        patch("app.services.channels.observation.get_adapter", return_value=adapter),
        patch("app.services.channels.observation.unseal_bot_token", return_value="unused"),
    ):
        assert await analyze(db, payload) is joins
    assert len(calls) == (2 if joins else 1)
    assert all(not call.spec.capabilities and not call.spec.mcp_servers for call in calls)
    if joins:
        assert calls[-1].spec.model_profile_id == main_model
        adapter.send_message.assert_awaited_once()
        assert adapter.send_message.call_args.args[1].reply_to_message_id == "m1"
    else:
        adapter.send_message.assert_not_awaited()


async def test_expiry_removes_reference_windows(db: AsyncSession):
    exposure, _ = await world(db)
    await append(db, exposure)
    await repo.expire(db, now=NOW + timedelta(days=8))
    assert list((await db.scalars(select(ChannelObservation))).all()) == []


def test_configuration_and_tool_free_decision_contract():
    config = ChannelObservationConfig()
    assert not config.enabled and config.unmentioned_interval_minutes == 20
    assert config.mentioned_interval_minutes == 1
    for values in (
        {"enabled": True},
        {"mentioned_interval_minutes": 0},
    ):
        with pytest.raises(ValidationError):
            ChannelObservationConfig.model_validate(values)
    assert not classifier_spec(config).capabilities
    assert not classifier_spec(config).mcp_servers


async def test_configuration_changes_reset_old_reference_window(db: AsyncSession):
    exposure, bot = await world(db)
    await append(db, exposure)
    exposure.observation_generation = uuid4()
    await db.flush()
    await append(db, exposure, "after-edit")
    window = (await db.scalars(select(ChannelObservation))).one()
    assert [item["message_id"] for item in window.messages] == ["after-edit"]
    assert window.generation == exposure.observation_generation


async def test_a_paid_window_cannot_be_claimed_twice(db: AsyncSession):
    exposure, _ = await world(db)
    await append(db, exposure)
    payload = await payload_for(db, exposure)
    args = {
        "observation_id": payload.observation_id,
        "organization_id": payload.organization_id,
        "generation": payload.generation,
        "revision": payload.revision,
    }
    assert await repo.claim_analysis(db, **args)
    assert not await repo.claim_analysis(db, **args)
    with patch(
        "app.services.channels.observation.AgentRunnerService.execute", new=AsyncMock()
    ) as run:
        assert not await analyze(db, payload)
    run.assert_not_awaited()


async def test_successful_collection_and_disabled_sweep_do_not_queue_work(db: AsyncSession):
    exposure, bot = await world(db)
    incoming = IncomingMessage(
        platform="mattermost",
        bot_id=str(bot.id),
        platform_user_id="human",
        platform_chat_id="room:thread",
        chat_type="group",
        text="Question",
        message_id="m1",
    )
    await observe(db, bot, incoming, addressed=False)
    window = (await db.scalars(select(ChannelObservation))).one()
    assert window.messages[0]["text"] == "Question"
    exposure.observation = {}
    await db.flush()
    assert await sweep(db, now=window.next_check_at) == 0
    assert not window.messages


async def test_deleted_binding_after_sweep_selection_is_skipped(db: AsyncSession):
    exposure, _ = await world(db)
    await append(db, exposure)
    with patch(
        "app.services.channels.observation.agent_exposure_repo.get",
        new=AsyncMock(return_value=None),
    ):
        assert await sweep(db, now=NOW + timedelta(minutes=20)) == 0


async def test_foreign_job_cannot_observe_another_organization(db: AsyncSession):
    exposure, _ = await world(db)
    await append(db, exposure)
    payload = await payload_for(db, exposure)
    with pytest.raises(AuthorizationError):
        await _authority(db, payload.model_copy(update={"organization_id": uuid4()}))


async def test_bot_policy_and_member_role_changes_revoke_pending_participation(db: AsyncSession):
    from app.db.models.organization import OrganizationMember

    exposure, bot = await world(db)
    await append(db, exposure)
    payload = await payload_for(db, exposure)
    bot.access_policy = {"mode": "whitelist", "whitelist": []}
    await db.flush()
    with pytest.raises(AuthorizationError, match="access policy"):
        await _authority(db, payload)
    bot.access_policy = {}
    await db.flush()
    # A new window reviews the new policy before a second job can proceed.
    await append(db, exposure, "new-policy", now=NOW + timedelta(minutes=21))
    await sweep(db, now=NOW + timedelta(minutes=41))
    window = (await db.scalars(select(ChannelObservation))).one()
    payload = payload.model_copy(
        update={"admission_hash": window.admission_hash, "revision": window.checked_revision}
    )
    membership = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == exposure.organization_id,
            OrganizationMember.user_id == exposure.observation_user_id,
        )
    )
    assert membership is not None
    membership.role = "viewer"
    await db.flush()
    with pytest.raises(AuthorizationError, match="manage channels"):
        await _authority(db, payload)


@pytest.mark.parametrize(
    "state", ["failed_decision", "empty_decision", "failed_answer", "empty_answer"]
)
async def test_incomplete_models_never_send_a_reply(db: AsyncSession, state: str):
    exposure, _ = await world(db)
    await append(db, exposure)
    payload = await payload_for(db, exposure)
    count = 0

    async def execute(ctx, agent_id, prompt, **kwargs: object):
        nonlocal count
        count += 1
        check = kwargs["check_model_request"]
        assert callable(check)
        await check(db)
        mark = kwargs.get("on_run_open")
        if callable(mark):
            row = SimpleNamespace(system_role=None)
            await mark(row)
            assert row.system_role == "channel_decision"
        structured = kwargs.get("structured")
        if isinstance(structured, list) and state != "empty_decision":
            structured.append({"score": 100, "reason": "Useful"})
        status = (
            "failed"
            if (count == 1 and state == "failed_decision")
            or (count == 2 and state == "failed_answer")
            else "completed"
        )
        return ("" if state == "empty_answer" else "Answer"), SimpleNamespace(
            id=uuid4(), status=status
        )

    adapter = SimpleNamespace(send_message=AsyncMock())
    with (
        patch(
            "app.services.channels.observation.AgentRunnerService.execute",
            new=AsyncMock(side_effect=execute),
        ),
        patch(
            "app.services.channels.observation.AgentRegistryService.get_runnable_spec",
            new=AsyncMock(return_value=(None, AgentSpec(name="Helper"), uuid4())),
        ),
        patch("app.services.channels.observation.get_adapter", return_value=adapter),
    ):
        assert not await analyze(db, payload)
    adapter.send_message.assert_not_awaited()


async def test_configuration_requires_a_human_channel_manager_and_valid_model(db: AsyncSession):
    from app.core.exceptions import BadRequestError
    from app.core.permissions import AuthContext
    from app.services.channels.observation import validate_configuration

    exposure, _ = await world(db)
    owner = AuthContext(
        user_id=exposure.observation_user_id, organization_id=exposure.organization_id, role="owner"
    )
    disabled = ChannelObservationConfig()
    enabled = ChannelObservationConfig.model_validate(exposure.observation)
    for ctx in (
        AuthContext(user_id=owner.user_id, organization_id=owner.organization_id, role="viewer"),
        AuthContext(user_id=None, organization_id=owner.organization_id, role="owner"),
    ):
        with pytest.raises(AuthorizationError):
            await validate_configuration(db, ctx, exposure, enabled)
    await validate_configuration(db, owner, exposure, disabled)
    exposure.surface = "email"
    with pytest.raises(BadRequestError):
        await validate_configuration(db, owner, exposure, enabled)
    exposure.surface = "mattermost"
    with (
        patch(
            "app.services.channels.observation.AgentRegistryService.get_runnable_spec",
            new=AsyncMock(),
        ),
        patch(
            "app.services.channels.observation.AgentRegistryService.validate_spec", new=AsyncMock()
        ) as validate,
        patch(
            "app.services.channels.observation.ModelProfileService.profile_for_organization",
            new=AsyncMock(return_value=SimpleNamespace(provider="openai", api=None)),
        ),
    ):
        with pytest.raises(BadRequestError, match="native decision profile"):
            await validate_configuration(
                db, owner, exposure, enabled.model_copy(update={"decision_mode": "native"})
            )
        await validate_configuration(db, owner, exposure, enabled)
    assert validate.call_args.args[1].model_profile_id == enabled.model_profile_id


@pytest.mark.parametrize("mcp_mode", ["none", "organization", "approval_required"])
async def test_real_runner_uses_only_organization_mcp_and_records_the_agent_reply(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    mcp_mode: str,
):
    from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from app.agents.model_resolver import ModelRequestSpec
    from app.db.models.agent import AgentVersion
    from app.db.models.agent_run import AgentRun
    from app.db.models.conversation import Message
    from app.db.models.credential import ModelProfile
    from app.repositories import agent_repo

    exposure, _ = await world(db)
    from tests.integration._keys import provider_key

    key_id = await provider_key(db, exposure.organization_id)
    profiles = [
        ModelProfile(
            organization_id=exposure.organization_id,
            label=label,
            provider="openai",
            model="gpt-4.1",
            secret_id=key_id,
        )
        for label in ("decision-model", "main-model")
    ]
    db.add_all(profiles)
    await db.flush()
    exposure.observation = ChannelObservationConfig(
        enabled=True, model_profile_id=profiles[0].id, instructions="Help with unresolved questions"
    ).model_dump(mode="json")
    exposure.tools = ["react_to_chat_message", "send_chat_message"]
    spec = AgentSpec(name="Helper", instructions="Be helpful", model_profile_id=profiles[1].id)
    version = AgentVersion(
        agent_id=exposure.agent_id,
        organization_id=exposure.organization_id,
        version=1,
        spec=spec.model_dump(mode="json"),
    )
    db.add(version)
    await db.flush()
    agent = await db.get(Agent, exposure.agent_id)
    assert agent is not None
    agent.current_version_id = version.id
    await db.flush()
    assert [
        row.id
        for row in await agent_repo.naming_model_profile(
            db, organization_id=exposure.organization_id, profile_id=profiles[0].id
        )
    ] == [agent.id]
    await append(db, exposure)
    payload = await payload_for(db, exposure)
    from pydantic_ai import RunContext
    from pydantic_ai.toolsets import FunctionToolset

    from app.agents.deps import AgentDeps
    from app.agents.mcp import ApprovalMarked
    from app.agents.spec import OrgMcpServerRef, PersonalMcpServerRef, PlatformMcpServerRef
    from app.db.models.mcp_connection import McpConnection
    from app.services.mcp_connection import ResolvedMcpToolsets

    organization_tool = AsyncMock(return_value="Verified organization result")
    server = McpConnection(
        scope="org",
        organization_id=exposure.organization_id,
        name="team-docs",
        url="https://mcp.example.com/mcp",
        secret_key_version=1,
    )
    db.add(server)
    await db.flush()
    if mcp_mode != "none":
        spec.mcp_servers = [
            OrgMcpServerRef(
                connection_id=server.id,
                approval="all" if mcp_mode == "approval_required" else "none",
            ),
            PersonalMcpServerRef(account="personal", catalog_key="github"),
            PlatformMcpServerRef(account="platform"),
        ]
        version.spec = spec.model_dump(mode="json")
        await db.flush()

    tools = FunctionToolset()

    @tools.tool
    async def team_docs_search(_ctx: RunContext[AgentDeps]) -> str:
        return await organization_tool()

    async def resolve(_db, *, refs, sender_user_id=None, **kwargs):
        assert sender_user_id is None
        assert all(isinstance(ref, OrgMcpServerRef) for ref in refs)
        if not refs:
            return ResolvedMcpToolsets(toolsets=[], unavailable=[])
        assert [ref.connection_id for ref in refs] == [server.id]
        return ResolvedMcpToolsets(
            toolsets=[ApprovalMarked(tools, policy=refs[0].approval)], unavailable=[]
        )

    monkeypatch.setattr("app.services.agent_runner.build_toolsets_for_agent", resolve)
    calls = []

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(info)
        if info.output_tools:
            assert not info.function_tools
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {"score": 100, "reason": "An unanswered useful question"},
                    )
                ]
            )
        if mcp_mode != "none":
            assert [tool.name for tool in info.function_tools] == ["team_docs_search"]
            if len(calls) == 2:
                return ModelResponse(parts=[ToolCallPart("team_docs_search", {})])
            from pydantic_ai.messages import ModelRequest, ToolReturnPart

            results = [
                part.content
                for message in messages
                if isinstance(message, ModelRequest)
                for part in message.parts
                if isinstance(part, ToolReturnPart)
            ]
            if mcp_mode == "approval_required":
                assert any("cannot ask anyone to approve" in str(result) for result in results)
            else:
                assert "Verified organization result" in results
        else:
            assert not info.function_tools
        return ModelResponse(
            parts=[TextPart("I can help. Mention me here if this needs a connected source.")]
        )

    monkeypatch.setattr(ModelRequestSpec, "build", lambda self: FunctionModel(respond))
    adapter = SimpleNamespace(send_message=AsyncMock())
    with (
        patch("app.services.channels.observation.get_adapter", return_value=adapter),
        patch("app.services.channels.observation.unseal_bot_token", return_value="unused"),
    ):
        assert await analyze(db, payload)
        assert not await analyze(db, payload)
    assert len(calls) == (2 if mcp_mode == "none" else 3)
    if mcp_mode == "organization":
        organization_tool.assert_awaited_once()
    else:
        organization_tool.assert_not_awaited()
    runs = list((await db.scalars(select(AgentRun).where(AgentRun.agent_id == agent.id))).all())
    assert len(runs) == 2 and all(run.status == "completed" for run in runs)
    assert {run.model_label for run in runs} == {row.label for row in profiles}
    messages = list((await db.scalars(select(Message))).all())
    assert len(messages) == 1 and messages[0].role == "assistant"
    assert messages[0].content.startswith("I can help")
    adapter.send_message.assert_awaited_once()
    window = (await db.scalars(select(ChannelObservation))).one()
    assert window.messages[-1]["author_id"].startswith("bot:")


async def test_an_edited_mention_supersedes_the_already_collected_message(db: AsyncSession):
    exposure, _ = await world(db)
    await append(db, exposure)
    payload = await payload_for(db, exposure)
    await append(db, exposure, addressed=True)
    with pytest.raises(AuthorizationError):
        await _authority(db, payload)
    window = (await db.scalars(select(ChannelObservation))).one()
    assert len(window.messages) == 1 and window.mentioned
    assert "Question" not in repr(window)
    from app.db.models.channel_observation import ChannelObservationReceipt

    receipt = (await db.scalars(select(ChannelObservationReceipt))).one()
    assert "human" not in repr(receipt)


async def test_a_disabled_binding_and_an_edited_expired_receipt_cannot_recollect_messages(
    db: AsyncSession,
):
    exposure, bot = await world(db)
    await append(db, exposure)
    window = (await db.scalars(select(ChannelObservation))).one()
    await db.delete(window)
    await db.flush()
    await append(db, exposure, addressed=True)
    exposure.observation = {}
    with patch(
        "app.services.channels.observation.agent_exposure_repo.list_observers_for_bot",
        new=AsyncMock(return_value=[(exposure, "helper")]),
    ):
        await observe(
            db,
            bot,
            IncomingMessage(
                platform="mattermost",
                bot_id=str(bot.id),
                platform_user_id="human",
                platform_chat_id="room:thread",
                chat_type="group",
                text="Question",
                message_id="m2",
            ),
            addressed=False,
        )
    assert (await db.scalars(select(ChannelObservation))).all() == []


@pytest.mark.parametrize("source", ["session", "observation", "removed", "deleted_after_send"])
async def test_automatic_answers_reuse_threads_and_respect_removed_windows(
    db: AsyncSession, source: str
):
    from app.db.models.conversation import Conversation

    exposure, bot = await world(db)
    await append(db, exposure)
    payload = await payload_for(db, exposure)
    window = (await db.scalars(select(ChannelObservation))).one()
    conversation = Conversation(organization_id=exposure.organization_id, title="Existing thread")
    db.add(conversation)
    await db.flush()
    if source == "observation":
        window.conversation_id = conversation.id
    session = SimpleNamespace(conversation_id=conversation.id) if source == "session" else None
    await db.flush()
    original_get = repo.get
    locked_reads = 0

    async def read(*args, **kwargs):
        nonlocal locked_reads
        if kwargs.get("for_update"):
            locked_reads += 1
            if (source == "removed" and locked_reads == 1) or (
                source == "deleted_after_send" and locked_reads == 2
            ):
                return None
        return await original_get(*args, **kwargs)

    async def execute(_ctx, _agent, _prompt, **kwargs):
        if "structured" in kwargs:
            kwargs["structured"].append({"score": 100, "reason": "Useful"})
        elif source in {"session", "observation"}:
            assert kwargs["conversation_id"] == conversation.id
        return "Useful answer", SimpleNamespace(id=uuid4(), status="completed")

    adapter = SimpleNamespace(send_message=AsyncMock())
    with (
        patch(
            "app.services.channels.observation.AgentRunnerService.execute",
            new=AsyncMock(side_effect=execute),
        ),
        patch(
            "app.services.channels.observation.AgentRegistryService.get_runnable_spec",
            new=AsyncMock(return_value=(None, AgentSpec(name="Helper"), uuid4())),
        ),
        patch(
            "app.services.channels.observation.channel_session_repo.get_by_bot_and_chat",
            new=AsyncMock(return_value=session),
        ),
        patch("app.services.channels.observation.observation_repo.get", new=read),
        patch("app.services.channels.observation.get_adapter", return_value=adapter),
        patch("app.services.channels.observation.unseal_bot_token", return_value="unused"),
    ):
        if source == "removed":
            with pytest.raises(AuthorizationError, match="removed"):
                await analyze(db, payload)
            adapter.send_message.assert_not_awaited()
        else:
            assert await analyze(db, payload)
            adapter.send_message.assert_awaited_once()
