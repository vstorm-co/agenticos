"""A tool that always asks: nothing decided in advance may answer for its call.

`share_memory` widens who may read a fact, so it is marked
`always_requires_approval`. The spec cannot waive that, and neither may the two
decisions a person makes before a call exists - "Approve everything" on the
session and a remembered "Always allow this tool". The card has to show what
would be shared, and only to somebody who may read the run it came from.
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ApprovalRequired
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition

from app.agents.approval import ApprovalGranted, ApprovalPending, ApprovalRequest
from app.agents.capabilities import CapabilityToolInfo, load_builtins, register
from app.agents.capabilities.approval import (
    ApprovalGate,
    always_asking_tools,
    private_approval_fields,
)
from app.agents.capabilities.memory_files._approval import describe_share
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import ApprovalStatus, RunStatus, ToolApproval
from app.repositories.agent_run import ApprovalRow
from app.services.agent_runner import AgentRunnerService, ApprovalChannel, ParkedApproval
from app.services.approvals import ApprovalService, withhold
from app.services.memory._runtime import ClaimView

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture(autouse=True)
def _builtins_loaded() -> None:
    load_builtins()


def _request(*, always_asks: bool, tool_name: str = "share_memory") -> ApprovalRequest:
    return ApprovalRequest(
        capability_id="memory_files",
        tool_name=tool_name,
        tool_call_id="call-1",
        tool_args={"claim_id": str(uuid.uuid4()), "to": "organization"},
        capability_tool_id=tool_name,
        always_asks=always_asks,
    )


def _channel(**kwargs: Any) -> ApprovalChannel:
    return ApprovalChannel(
        organization_id=uuid.uuid4(), agent_id=uuid.uuid4(), run_id=uuid.uuid4(), **kwargs
    )


class TestChannel:
    async def test_approve_everything_does_not_answer_an_always_asking_call(self) -> None:
        channel = _channel(standing_consent_by=uuid.uuid4())

        decision = await channel(_request(always_asks=True))

        assert isinstance(decision, ApprovalPending)
        [parked] = channel.requested
        assert parked.always_asks and not parked.standing
        assert parked.tool_consented_by is None
        assert list(channel.parked.values()) == ["call-1"]

    async def test_a_remembered_consent_does_not_answer_an_always_asking_call(self) -> None:
        consent = AsyncMock(return_value=uuid.uuid4())
        channel = _channel(tool_consent=consent)

        decision = await channel(_request(always_asks=True))

        assert isinstance(decision, ApprovalPending)
        consent.assert_not_awaited()
        assert not channel.requested[0].standing

    async def test_an_ordinary_gated_call_is_still_answered_in_advance(self) -> None:
        consenter = uuid.uuid4()
        waived = _channel(standing_consent_by=consenter)
        remembered = _channel(tool_consent=AsyncMock(return_value=consenter))

        for channel in (waived, remembered):
            decision = await channel(_request(always_asks=False, tool_name="send_email"))
            assert isinstance(decision, ApprovalGranted)
            assert channel.requested[0].standing
            assert channel.parked == {}

    async def test_the_row_is_written_saying_it_always_asks(self) -> None:
        channel = _channel()
        channel.requested.append(
            ParkedApproval(
                approval_id=uuid.uuid4(),
                tool_call_id="call-1",
                tool_name="share_memory",
                tool_args={},
                always_asks=True,
            )
        )
        service = AgentRunnerService(MagicMock())

        with (
            patch(
                "app.services.agent_runner.agent_repo.existing_ids_locked",
                new=AsyncMock(return_value=set()),
            ),
            patch.object(service.approvals, "request", new=AsyncMock()) as written,
        ):
            await service._write_approvals(MagicMock(approvals=channel), include_pending=True)

        assert written.await_args.kwargs["always_asks"] is True


class TestGate:
    @staticmethod
    def _tool_def(name: str) -> ToolDefinition:
        return ToolDefinition(
            name=name,
            parameters_json_schema={"type": "object", "properties": {}},
            capability_id="memory_files",
        )

    async def _asked(self, gate: ApprovalGate, name: str) -> ApprovalRequest:
        ask = AsyncMock(return_value=ApprovalPending())
        ctx = MagicMock()
        ctx.deps = AgentDeps(run_id=uuid.uuid4(), request_approval=ask)
        with pytest.raises(ApprovalRequired):
            await gate.wrap_tool_execute(
                ctx,
                call=ToolCallPart(tool_name=name, args={}, tool_call_id="call-1"),
                tool_def=self._tool_def(name),
                args={},
                handler=AsyncMock(),
            )
        request: ApprovalRequest = ask.await_args.args[0]
        return request

    async def test_the_gate_marks_an_always_asking_tool(self) -> None:
        gate = ApprovalGate(
            required_tool_names=frozenset({"share_memory", "correct_memory"}),
            always_asking_tool_names=frozenset({"share_memory"}),
        )

        assert (await self._asked(gate, "share_memory")).always_asks
        assert not (await self._asked(gate, "correct_memory")).always_asks

    def test_a_renamed_share_memory_still_always_asks(self) -> None:
        spec = AgentSpec(
            name="Remembers",
            capabilities=[
                {
                    "id": "memory_files",
                    "approval": "never",
                    "tool_overrides": {"share_memory": {"name": "publish_fact"}},
                }
            ],
        )

        assert always_asking_tools(spec) == frozenset({"publish_fact"})


class TestRegistry:
    def test_share_memory_hides_the_fact_it_quotes(self) -> None:
        assert private_approval_fields("share_memory") == frozenset({"claim"})
        assert private_approval_fields("send_email") == frozenset()
        assert private_approval_fields(None) == frozenset()

    def test_hiding_fields_of_an_undeclared_tool_is_refused(self) -> None:
        with pytest.raises(RuntimeError, match="hides fields of tools it does not declare"):
            register(
                id="test_hides_a_stranger",
                name="Stranger",
                category="test",
                description="Declares one tool and hides another's fields.",
                tools=[CapabilityToolInfo(id="read", description="Reads.")],
                private_approval_fields={"write": ["body"]},
            )


def _approval(*, always_asks: bool, capability_tool_id: str = "share_memory") -> ToolApproval:
    return ToolApproval(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        tool_id=capability_tool_id,
        tool_args={"claim_id": "c", "to": "organization"},
        capability_tool_id=capability_tool_id,
        context={"claim": "Anna owns invoices", "audience": "organization"},
        status=ApprovalStatus.PENDING.value,
        always_asks=always_asks,
    )


def _member(
    role: str = OrgRoleName.OWNER.value, *, user_id: uuid.UUID | None = None
) -> AuthContext:
    return AuthContext(user_id=user_id or uuid.uuid4(), organization_id=uuid.uuid4(), role=role)


class TestRemembering:
    async def test_an_always_asking_approval_cannot_be_remembered(self, mock_db_session) -> None:
        approval = _approval(always_asks=True)
        service = ApprovalService(mock_db_session)

        with (
            patch(
                "app.services.approvals.agent_run_repo.get_approval",
                new=AsyncMock(return_value=approval),
            ),
            patch(
                "app.services.approvals.voice_call_repo.is_live_run",
                new=AsyncMock(return_value=False),
            ),
            patch.object(service, "hidden_fields", new=AsyncMock(return_value=frozenset())),
            patch("app.services.approvals.agent_run_repo.decide_approval") as decided,
            pytest.raises(BadRequestError, match="asks every time"),
        ):
            await service.decide(_member(), approval.id, approved=True, remember_scope="agent")

        decided.assert_not_called()
        assert approval.remember_scope is None

    async def test_its_card_offers_no_remembering(self) -> None:
        ctx = _member()
        approval = _approval(always_asks=True)
        run = MagicMock(
            status=RunStatus.AWAITING_APPROVAL.value,
            paused_state={},
            organization_id=ctx.organization_id,
        )
        service = AgentRunnerService(MagicMock())

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[approval]),
            ),
            patch(
                "app.services.agent_runner.ApprovalService.can_remember_in_run", return_value=True
            ),
            patch(
                "app.services.agent_runner.ApprovalService.hidden_fields",
                new=AsyncMock(return_value=frozenset()),
            ),
        ):
            [call] = await service.parked_calls(ctx, run)

        assert call.can_remember is False
        assert call.always_asks and not call.content_hidden
        assert call.context is not None and call.context["claim"] == "Anna owns invoices"

    async def test_a_parked_call_leaves_out_what_its_reader_may_not_see(self) -> None:
        ctx = _member()
        run = MagicMock(
            status=RunStatus.AWAITING_APPROVAL.value,
            paused_state={},
            organization_id=ctx.organization_id,
        )
        service = AgentRunnerService(MagicMock())

        with (
            patch(
                "app.services.agent_runner.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(return_value=[_approval(always_asks=True)]),
            ),
            patch(
                "app.services.agent_runner.ApprovalService.hidden_fields",
                new=AsyncMock(return_value=frozenset({"claim"})),
            ),
        ):
            [call] = await service.parked_calls(ctx, run)

        assert call.content_hidden
        assert call.context == {"audience": "organization"}


def _row(
    *, triggered_by: uuid.UUID | None, capability_tool_id: str = "share_memory"
) -> ApprovalRow:
    return ApprovalRow(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        agent_name="Helper",
        tool_id=capability_tool_id,
        tool_args={"claim_id": "c", "to": "organization"},
        capability_tool_id=capability_tool_id,
        context={"claim": "Anna owns invoices", "audience": "organization"},
        account=None,
        subagent_name=None,
        subagent_agent_id=None,
        status=ApprovalStatus.PENDING.value,
        triggered_by_user_id=triggered_by,
        triggered_by_email=None,
        decided_by_user_id=None,
        decided_by_email=None,
        decided_at=None,
        decided_via="click",
        note=None,
        created_at=None,
    )


class TestQueueReaders:
    async def test_a_reader_who_may_not_see_the_run_gets_the_audience_not_the_fact(
        self, mock_db_session
    ) -> None:
        row = _row(triggered_by=uuid.uuid4())

        [read] = await ApprovalService(mock_db_session).as_read_by(
            _member(OrgRoleName.MEMBER.value), [row]
        )

        assert read.content_hidden
        assert read.context == {"audience": "organization"}
        assert read.tool_args == row.tool_args

    async def test_the_person_whose_run_it_is_reads_the_fact(self, mock_db_session) -> None:
        ctx = _member(OrgRoleName.MEMBER.value)

        [read] = await ApprovalService(mock_db_session).as_read_by(
            ctx, [_row(triggered_by=ctx.user_id)]
        )

        assert not read.content_hidden
        assert read.context is not None and read.context["claim"] == "Anna owns invoices"

    async def test_a_reader_of_every_run_reads_it_only_for_an_agent_they_may_view(
        self, mock_db_session
    ) -> None:
        visible, hidden = _row(triggered_by=None), _row(triggered_by=None)
        agents = {visible.agent_id: MagicMock(), hidden.agent_id: MagicMock()}

        async def may_view(_db: Any, _ctx: Any, agent: Any, *_: Any, **__: Any) -> bool:
            return agent is agents[visible.agent_id]

        with (
            patch("app.services.approvals.agent_repo.get_many", new=AsyncMock(return_value=agents)),
            patch("app.services.access.resolve_access", new=may_view),
        ):
            reads = await ApprovalService(mock_db_session).as_read_by(
                _member(OrgRoleName.OPERATOR.value), [visible, hidden]
            )

        assert [read.content_hidden for read in reads] == [False, True]

    async def test_a_call_with_nothing_private_is_read_as_it_is(self, mock_db_session) -> None:
        row = _row(triggered_by=uuid.uuid4(), capability_tool_id="send_email")

        assert await ApprovalService(mock_db_session).as_read_by(
            _member(OrgRoleName.MEMBER.value), [row]
        ) == [row]

    async def test_the_decision_answer_hides_what_the_queue_hides(self, mock_db_session) -> None:
        approval = _approval(always_asks=True)
        service = ApprovalService(mock_db_session)
        stranger = _member(OrgRoleName.MEMBER.value)

        with patch(
            "app.services.approvals.agent_run_repo.get_run",
            new=AsyncMock(return_value=MagicMock(user_id=uuid.uuid4())),
        ):
            assert await service.hidden_fields(stranger, approval) == frozenset({"claim"})

        with patch(
            "app.services.approvals.agent_run_repo.get_run",
            new=AsyncMock(return_value=MagicMock(user_id=stranger.user_id)),
        ):
            assert await service.hidden_fields(stranger, approval) == frozenset()

        assert (
            await service.hidden_fields(
                stranger, _approval(always_asks=False, capability_tool_id="send_email")
            )
            == frozenset()
        )

    def test_withholding_leaves_a_missing_context_missing(self) -> None:
        assert withhold(frozenset({"claim"}), tool_args={"a": 1}, context=None) == ({"a": 1}, None)


class TestDescriber:
    @staticmethod
    def _deps() -> AgentDeps:
        return AgentDeps(organization_id=uuid.uuid4(), agent_id=uuid.uuid4(), run_id=uuid.uuid4())

    async def test_the_card_names_the_fact_and_its_audience(self) -> None:
        claim = MagicMock(spec=ClaimView, statement="Anna owns invoices")
        with (
            patch("app.services.memory._runtime.project_of", new=AsyncMock(return_value=None)),
            patch(
                "app.services.memory._runtime.claim_for_approval",
                new=AsyncMock(return_value=claim),
            ),
        ):
            described = await describe_share(
                self._deps(), {"claim_id": str(uuid.uuid4()), "to": "organization"}, None
            )

        assert described == {"claim": "Anna owns invoices", "audience": "organization"}

    async def test_a_claim_the_run_cannot_read_is_not_described(self) -> None:
        with (
            patch("app.services.memory._runtime.project_of", new=AsyncMock(return_value=None)),
            patch(
                "app.services.memory._runtime.claim_for_approval",
                new=AsyncMock(return_value=None),
            ),
        ):
            described = await describe_share(
                self._deps(), {"claim_id": str(uuid.uuid4()), "to": "project"}, None
            )

        assert described is None

    async def test_nothing_is_described_without_an_agent_or_an_id(self) -> None:
        assert await describe_share(AgentDeps(), {"claim_id": str(uuid.uuid4())}, None) is None
        assert await describe_share(self._deps(), {"claim_id": "not-an-id"}, None) is None


class TestTheDescriberReadsWhatTheToolReads:
    @pytest.mark.parametrize("allow_personal", [True, False])
    async def test_it_reads_personal_memory_only_where_the_binding_keeps_it(
        self, allow_personal: bool
    ) -> None:
        from app.agents.capabilities.memory_files import MemoryFilesConfig

        scopes = MagicMock(return_value=[])
        with (
            patch(
                "app.agents.capabilities.memory_files._approval.readable_claim_scopes", new=scopes
            ),
            patch("app.services.memory._runtime.project_of", new=AsyncMock(return_value=None)),
            patch(
                "app.services.memory._runtime.claim_for_approval",
                new=AsyncMock(return_value=None),
            ),
        ):
            await describe_share(
                AgentDeps(organization_id=uuid.uuid4(), agent_id=uuid.uuid4()),
                {"claim_id": str(uuid.uuid4())},
                MemoryFilesConfig(allow_personal=allow_personal),
            )

        assert scopes.call_args.kwargs["allow_personal"] is allow_personal

    async def test_a_spec_hands_each_describer_its_bindings_config(self) -> None:
        from app.agents.capabilities.approval import approval_describers

        spec = AgentSpec(
            name="Private",
            capabilities=[{"id": "memory_files", "config": {"allow_personal": False}}],
        )
        describe = approval_describers(spec)["share_memory"]
        with (
            patch(
                "app.agents.capabilities.memory_files._approval.readable_claim_scopes",
                new=MagicMock(return_value=[]),
            ) as scopes,
            patch("app.services.memory._runtime.project_of", new=AsyncMock(return_value=None)),
            patch(
                "app.services.memory._runtime.claim_for_approval", new=AsyncMock(return_value=None)
            ),
        ):
            await describe(
                AgentDeps(organization_id=uuid.uuid4(), agent_id=uuid.uuid4()),
                {"claim_id": str(uuid.uuid4())},
            )

        assert scopes.call_args.kwargs["allow_personal"] is False
