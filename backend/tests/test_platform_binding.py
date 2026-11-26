"""Binding an agent to this platform's own MCP server (#2063)."""

import uuid
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.audience import RunAudience
from app.agents.spec import AgentSpec, OrgMcpServerRef, PlatformMcpServerRef
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_run import AgentRun, RunSurface
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService, _routine_source

pytestmark = pytest.mark.anyio

CTX = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")


class TestTheCredential:
    async def test_minted_only_for_an_agent_that_binds_the_platform(self) -> None:
        runner = AgentRunnerService(MagicMock())
        mint = AsyncMock(return_value="aos_minted")
        bound = AgentSpec(
            name="AI Architect", mcp_servers=[PlatformMcpServerRef(account="platform")]
        )
        unbound = AgentSpec(name="Support")

        with patch("app.services.agent_runner.mint_for_run", new=mint):
            assert await runner._platform_credential(bound, CTX) == "aos_minted"
            assert await runner._platform_credential(unbound, CTX) is None

        mint.assert_awaited_once_with(
            CTX, agent_id=None, conversation_id=None, run_id=None, reporting_only=False
        )

    async def test_a_fresh_agent_is_named_before_its_run_row_exists(self) -> None:
        runner = AgentRunnerService(MagicMock())
        agent_id = uuid.uuid4()
        bound = AgentSpec(name="Researcher", mcp_servers=[PlatformMcpServerRef(account="platform")])
        with patch(
            "app.services.agent_runner.mint_for_run", new=AsyncMock(return_value="aos_minted")
        ) as mint:
            assert await runner._platform_credential(bound, CTX, agent_id=agent_id) == "aos_minted"
        mint.assert_awaited_once_with(
            CTX, agent_id=agent_id, conversation_id=None, run_id=None, reporting_only=False
        )

    async def test_existing_agent_identity_travels_with_its_platform_credential(self) -> None:
        runner = AgentRunnerService(MagicMock())
        run = MagicMock(id=uuid.uuid4(), agent_id=uuid.uuid4(), routine_origin_id=None)
        bound = AgentSpec(name="Researcher", mcp_servers=[PlatformMcpServerRef(account="platform")])
        with (
            patch.object(runner, "_run_owner_context", new=AsyncMock(return_value=CTX)),
            patch(
                "app.services.agent_runner.mint_for_run", new=AsyncMock(return_value="aos_minted")
            ) as mint,
        ):
            assert await runner._platform_credential(bound, CTX, run) == "aos_minted"
        mint.assert_awaited_once_with(
            CTX, agent_id=run.agent_id, conversation_id=None, run_id=run.id, reporting_only=False
        )

    async def test_a_run_resumed_by_somebody_else_keeps_its_owner_s_authority(self) -> None:
        """Codex on #2062: an administrator answering an approval lent the run their role."""
        runner = AgentRunnerService(MagicMock())
        owner = uuid.uuid4()
        run = MagicMock(user_id=owner, initiated_by_publisher_fallback=False, key_scopes=None)
        membership = MagicMock(role="member")

        with patch(
            "app.services.agent_runner.member_repo.get_active",
            new=AsyncMock(return_value=membership),
        ):
            rebuilt = await runner._run_owner_context(CTX, run)
        assert rebuilt is not None
        assert (rebuilt.user_id, rebuilt.role) == (owner, "member")

        bound = AgentSpec(
            name="AI Architect", mcp_servers=[PlatformMcpServerRef(account="platform")]
        )
        with (
            patch(
                "app.services.agent_runner.member_repo.get_active",
                new=AsyncMock(return_value=None),
            ),
            patch("app.services.agent_runner.mint_for_run", new=AsyncMock()) as mint,
        ):
            assert await runner._run_owner_context(CTX, run) is None
            assert await runner._platform_credential(bound, CTX, run) is None
        mint.assert_not_awaited()

        assert await runner._run_owner_context(CTX, None) is CTX
        own = MagicMock(user_id=CTX.user_id, key_scopes=None)
        assert await runner._run_owner_context(CTX, own) is CTX

    @pytest.mark.security
    async def test_a_run_a_key_started_stays_under_the_key_when_resumed(self) -> None:
        """Codex on #2062: an `agents:run` key's run, approved and resumed by
        somebody else, minted a credential with the owner's whole role."""
        runner = AgentRunnerService(MagicMock())
        owner = uuid.uuid4()
        run = MagicMock(
            user_id=owner, initiated_by_publisher_fallback=False, key_scopes=["agents:run", "nope"]
        )

        with patch(
            "app.services.agent_runner.member_repo.get_active",
            new=AsyncMock(return_value=MagicMock(role="owner")),
        ):
            rebuilt = await runner._run_owner_context(CTX, run)
        assert rebuilt is not None
        assert rebuilt.key_scopes == frozenset({Perm.AGENTS_RUN})
        assert not rebuilt.has(Perm.MEMBERS_MANAGE)

        # The owner resuming it themselves stays under it too, and a key they
        # resume with narrows it further.
        mine = MagicMock(user_id=CTX.user_id, key_scopes=["agents:run", "agents:view"])
        resumed = await runner._run_owner_context(CTX, mine)
        assert resumed is not None
        assert resumed.key_scopes == frozenset({Perm.AGENTS_RUN, Perm.AGENTS_VIEW})
        keyed = AuthContext(
            user_id=CTX.user_id,
            organization_id=CTX.organization_id,
            role="owner",
            key_scopes=frozenset({Perm.AGENTS_VIEW}),
        )
        narrowed = await runner._run_owner_context(keyed, mine)
        assert narrowed is not None
        assert narrowed.key_scopes == frozenset({Perm.AGENTS_VIEW})


class TestPublishing:
    async def test_the_platform_is_bound_under_its_own_prefix(self) -> None:
        registry = AgentRegistryService(MagicMock())
        connection = MagicMock(visibility="org")
        connection.name = "agenticos"
        org_ref = OrgMcpServerRef(connection_id=uuid.uuid4())

        with patch(
            "app.services.agent_registry.mcp_connection_repo.get_org_scoped_by_ids",
            new=AsyncMock(return_value={org_ref.connection_id: connection}),
        ):
            alone = await registry._mcp_problems(
                CTX, [PlatformMcpServerRef(account="platform")], taken={}
            )
            clashing = await registry._mcp_problems(
                CTX, [PlatformMcpServerRef(account="platform"), org_ref], taken={}
            )

        assert alone == []
        assert len(clashing) == 1
        assert "'agenticos'" in clashing[0]

    @pytest.mark.security
    async def test_a_tool_approval_naming_no_platform_tool_is_refused(self) -> None:
        """A mistyped name would leave the tool on the binding's default, silently."""
        registry = AgentRegistryService(MagicMock())

        known = await registry._mcp_problems(
            CTX,
            [
                PlatformMcpServerRef(
                    account="platform", tool_approval={"add_virtual_table_record": "never"}
                )
            ],
            taken={},
        )
        unknown = await registry._mcp_problems(
            CTX,
            [PlatformMcpServerRef(account="platform", tool_approval={"add_table_row": "never"})],
            taken={},
        )

        assert known == []
        assert unknown == [
            "This platform's server has no tool named add_table_row to set approval for"
        ]

    @pytest.mark.security
    async def test_a_tool_that_widens_authority_cannot_be_published_to_run_freely(self) -> None:
        """Codex on #3172: a Builder's agent, run by an Owner, invited an Admin unasked."""
        registry = AgentRegistryService(MagicMock())

        def binding(mode: str) -> list[PlatformMcpServerRef]:
            approvals = {"invite_member": mode, "update_proactivity_settings": mode}
            return [PlatformMcpServerRef(account="platform", tool_approval=approvals)]

        released = await registry._mcp_problems(CTX, binding("never"), taken={})
        asked = await registry._mcp_problems(CTX, binding("required"), taken={})

        assert released == [
            "invite_member, update_proactivity_settings always asks the person the agent "
            "runs for, so it cannot run freely"
        ]
        assert asked == []


class TestTheStoredBinding:
    def test_a_binding_with_no_tool_of_its_own_stores_as_before(self) -> None:
        """Published agents' stored specs do not change shape."""
        stored = {"account": "platform", "allowed_tools": None, "approval": "writes"}

        assert PlatformMcpServerRef.model_validate(stored).model_dump(mode="json") == stored

    @pytest.mark.security
    def test_each_tool_s_own_approval_survives_the_yaml_round_trip(self) -> None:
        spec = AgentSpec(
            name="Ops",
            mcp_servers=[
                PlatformMcpServerRef(
                    account="platform",
                    tool_approval={"run_workflow": "never", "default_tool": "default"},
                )
            ],
        )

        (platform,) = AgentSpec.from_yaml(spec.to_yaml()).mcp_servers
        assert isinstance(platform, PlatformMcpServerRef)
        assert platform.tool_approval == {"run_workflow": "never"}


@pytest.mark.parametrize(
    "surface",
    [
        RunSurface.WEB,
        RunSurface.SLACK,
        RunSurface.TELEGRAM,
        RunSurface.MATTERMOST,
        RunSurface.TEAMS,
        RunSurface.SMS,
        RunSurface.EMAIL,
    ],
)
def test_only_an_admitted_private_human_turn_can_create_personal_routine_authority(
    surface: RunSurface,
) -> None:
    conversation = uuid.uuid4()
    assert (
        _routine_source(
            CTX,
            surface=surface,
            conversation_id=conversation,
            memory_room_key=None,
            audience=None,
            public_origin=False,
            impersonated=False,
            existing_run=None,
        )
        == conversation
    )


@pytest.mark.parametrize(
    "case",
    [
        "schedule",
        "workflow",
        "api",
        "embed",
        "a2a",
        "proactive",
        "no-conversation",
        "no-person",
        "publisher",
        "personal-fire",
        "routine",
        "key",
        "key-scopes",
        "room",
        "public-origin",
        "impersonated",
        "restored-room",
        "restored-anonymous",
        "restored-other-person",
        "old-publisher",
        "old-key",
        "old-routine",
        "old-surface",
    ],
)
def test_background_and_resumed_nonprivate_runs_never_gain_personal_routine_authority(
    case: str,
) -> None:
    ctx = CTX
    surface = {
        "schedule": RunSurface.SCHEDULE,
        "workflow": RunSurface.WORKFLOW,
        "api": RunSurface.API,
        "embed": RunSurface.EMBED,
        "a2a": RunSurface.A2A,
        "proactive": RunSurface.PROACTIVE,
    }.get(case, RunSurface.SLACK)
    if case == "no-person":
        ctx = replace(ctx, user_id=None)
    if case == "publisher":
        ctx = replace(ctx, subject_is_publisher_fallback=True)
    if case == "personal-fire":
        ctx = replace(ctx, fired_as_creator="schedule")
    if case == "routine":
        ctx = replace(ctx, routine_id=uuid.uuid4())
    if case == "key":
        ctx = replace(ctx, api_key_id=uuid.uuid4())
    if case == "key-scopes":
        ctx = replace(ctx, key_scopes=frozenset({Perm.AGENTS_RUN}))
    audience = None
    if case == "restored-room":
        audience = RunAudience(user_id=CTX.user_id, room_key="room:slack:C123")
    if case == "restored-anonymous":
        audience = RunAudience()
    if case == "restored-other-person":
        audience = RunAudience(user_id=uuid.uuid4())
    run = None
    if case.startswith("old-"):
        run = AgentRun(
            user_id=CTX.user_id,
            surface=RunSurface.SLACK.value,
            initiated_by_publisher_fallback=case == "old-publisher",
            key_scopes=None,
            routine_origin_id=None,
        )
        if case == "old-key":
            run.key_scopes = ["agents:run"]
        if case == "old-routine":
            run.routine_origin_id = uuid.uuid4()
        if case == "old-surface":
            run.surface = RunSurface.API.value
    assert (
        _routine_source(
            ctx,
            surface=surface,
            conversation_id=None if case == "no-conversation" else uuid.uuid4(),
            memory_room_key="room:slack:C123" if case == "room" else None,
            audience=audience,
            public_origin=case == "public-origin",
            impersonated=case == "impersonated",
            existing_run=run,
        )
        is None
    )


def test_resumed_private_chat_keeps_the_original_person_instead_of_the_approver() -> None:
    original = uuid.uuid4()
    conversation = uuid.uuid4()
    run = AgentRun(
        user_id=original,
        surface=RunSurface.WEB.value,
        initiated_by_publisher_fallback=False,
        key_scopes=None,
        routine_origin_id=None,
    )
    assert (
        _routine_source(
            CTX,
            surface=RunSurface.WEB,
            conversation_id=conversation,
            memory_room_key=None,
            audience=RunAudience(user_id=original),
            public_origin=False,
            impersonated=False,
            existing_run=run,
        )
        == conversation
    )
