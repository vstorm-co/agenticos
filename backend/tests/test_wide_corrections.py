"""Correcting a fact the whole organization or a project reads waits for a person.

`correct_memory` on somebody's own fact is theirs to make; on a fact everybody
here reads it is one instruction away from rewriting what every agent knows. So
such a call asks a person every time, whatever the approval mode, and the card
shows the fact before and after.
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ApprovalRequired
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition

from app.agents.capabilities import CapabilityToolInfo, load_builtins, register
from app.agents.capabilities.approval import ApprovalGate, always_asking_checks
from app.agents.capabilities.memory_files._approval import (
    correction_is_wide,
    describe_correction,
)
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import ApprovalStatus
from app.repositories.agent_run import ApprovalRow
from app.services.agent_runner import ApprovalChannel
from app.services.approvals import ApprovalService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

CORRECT = "correct_memory"


@pytest.fixture(autouse=True)
def _builtins_loaded() -> None:
    load_builtins()


def _tool_def(capability_id: str | None = "memory_files") -> ToolDefinition:
    return ToolDefinition(
        name=CORRECT,
        parameters_json_schema={"type": "object", "properties": {}},
        capability_id=capability_id,
    )


def _ctx(channel: Any) -> MagicMock:
    ctx = MagicMock()
    ctx.deps = AgentDeps(run_id=uuid.uuid4(), request_approval=channel)
    return ctx


def _channel(**kwargs: Any) -> ApprovalChannel:
    return ApprovalChannel(
        organization_id=uuid.uuid4(), agent_id=uuid.uuid4(), run_id=uuid.uuid4(), **kwargs
    )


async def _call(gate: ApprovalGate, channel: Any, tool_def: ToolDefinition | None = None) -> Any:
    return await gate.wrap_tool_execute(
        _ctx(channel),
        call=ToolCallPart(tool_name=CORRECT, args={}, tool_call_id="call-1"),
        tool_def=tool_def or _tool_def(),
        args={"claim_id": str(uuid.uuid4()), "statement": "Office closes at five"},
        handler=AsyncMock(return_value="corrected"),
    )


class TestEveryApprovalMode:
    @pytest.mark.parametrize(
        ("mode", "gate_every_tool", "channel"),
        [
            ("follow the agent", False, lambda: _channel()),
            ("ask about everything", True, lambda: _channel()),
            ("approve everything", False, lambda: _channel(standing_consent_by=uuid.uuid4())),
            (
                "a remembered always allow",
                False,
                lambda: _channel(tool_consent=AsyncMock(return_value=uuid.uuid4())),
            ),
        ],
    )
    async def test_a_wide_correction_waits_for_a_person(
        self, mode: str, gate_every_tool: bool, channel: Any
    ) -> None:
        gate = ApprovalGate(
            gate_every_tool=gate_every_tool,
            always_asking_checks={CORRECT: AsyncMock(return_value=True)},
        )
        asked = channel()

        with pytest.raises(ApprovalRequired):
            await _call(gate, asked)

        [parked] = asked.requested
        assert parked.always_asks and not parked.standing, mode

    async def test_a_correction_of_ones_own_fact_runs_as_it_did(self) -> None:
        gate = ApprovalGate(always_asking_checks={CORRECT: AsyncMock(return_value=False)})
        asked = _channel()

        assert await _call(gate, asked) == "corrected"
        assert asked.requested == []

    async def test_a_check_that_fails_asks(self) -> None:
        gate = ApprovalGate(
            always_asking_checks={CORRECT: AsyncMock(side_effect=RuntimeError("db down"))}
        )
        asked = _channel(standing_consent_by=uuid.uuid4())

        with pytest.raises(ApprovalRequired):
            await _call(gate, asked)

    async def test_a_tool_no_capability_owns_is_never_checked(self) -> None:
        check = AsyncMock(return_value=True)
        gate = ApprovalGate(always_asking_checks={CORRECT: check})

        assert await _call(gate, _channel(), _tool_def(capability_id=None)) == "corrected"
        check.assert_not_awaited()

    def test_a_renamed_correct_memory_keeps_its_check_and_a_disabled_binding_has_none(self) -> None:
        spec = AgentSpec(
            name="Remembers",
            capabilities=[
                {"id": "memory_files", "tool_overrides": {CORRECT: {"name": "fix_fact"}}},
                {"id": "context", "enabled": False},
            ],
        )

        assert set(always_asking_checks(spec)) == {"fix_fact"}

    def test_a_check_for_an_undeclared_tool_is_refused(self) -> None:
        with pytest.raises(RuntimeError, match="asks about tools it does not declare"):
            register(
                id="test_checks_a_stranger",
                name="Stranger",
                category="test",
                description="Declares one tool and checks another.",
                tools=[CapabilityToolInfo(id="read", description="Reads.")],
                always_asks_when={"write": AsyncMock(return_value=True)},
            )


def _deps() -> AgentDeps:
    return AgentDeps(organization_id=uuid.uuid4(), agent_id=uuid.uuid4(), run_id=uuid.uuid4())


def _reading(claim: Any):
    return (
        patch("app.services.memory._runtime.project_of", new=AsyncMock(return_value=None)),
        patch("app.services.memory._runtime.claim_for_approval", new=AsyncMock(return_value=claim)),
    )


class TestWhatTheCheckAndTheCardRead:
    @pytest.mark.parametrize(
        ("scope", "wide"),
        [("org", True), ("project", True), ("profile", False), ("this agent", False)],
    )
    async def test_only_a_project_or_organization_fact_is_wide(
        self, scope: str, wide: bool
    ) -> None:
        project_of, claim_for_approval = _reading(MagicMock(scope=scope))
        with project_of, claim_for_approval:
            assert await correction_is_wide(_deps(), {"claim_id": str(uuid.uuid4())}) is wide

    async def test_a_claim_the_run_cannot_read_is_not_wide(self) -> None:
        project_of, claim_for_approval = _reading(None)
        with project_of, claim_for_approval:
            assert await correction_is_wide(_deps(), {"claim_id": str(uuid.uuid4())}) is False
            assert await describe_correction(_deps(), {"claim_id": str(uuid.uuid4())}, None) is None

    async def test_the_card_shows_the_fact_before_and_after(self) -> None:
        project_of, claim_for_approval = _reading(MagicMock(statement="Office closes at six"))
        with project_of, claim_for_approval:
            described = await describe_correction(
                _deps(),
                {"claim_id": str(uuid.uuid4()), "statement": "Office closes at five"},
                None,
            )

        assert described == {"before": "Office closes at six", "after": "Office closes at five"}

    @pytest.mark.parametrize("allow_personal", [True, False])
    async def test_the_card_reads_what_the_tool_reads(self, allow_personal: bool) -> None:
        from app.agents.capabilities.memory_files import MemoryFilesConfig

        scopes = MagicMock(return_value=[])
        project_of, claim_for_approval = _reading(None)
        with (
            patch(
                "app.agents.capabilities.memory_files._approval.readable_claim_scopes", new=scopes
            ),
            project_of,
            claim_for_approval,
        ):
            await describe_correction(
                _deps(),
                {"claim_id": str(uuid.uuid4())},
                MemoryFilesConfig(allow_personal=allow_personal),
            )

        assert scopes.call_args.kwargs["allow_personal"] is allow_personal

    @pytest.mark.parametrize("scope", ["org", "project"])
    async def test_private_runs_detect_shared_claims_without_reading_personal_claims(
        self, scope: str
    ) -> None:
        from collections.abc import Sequence
        from datetime import UTC, datetime

        from app.agents.audience import RunAudience
        from app.repositories.memory_claim import ClaimScope
        from app.services.memory._runtime import ClaimView

        deps = _deps()
        deps.audience = RunAudience(user_id=uuid.uuid4())
        project = uuid.uuid4()
        claim_id = uuid.uuid4()
        key = f"{scope}:{deps.organization_id if scope == 'org' else project}"
        claim = ClaimView(
            id=claim_id,
            statement="Office closes at six",
            subject=None,
            kind="fact",
            origin="person",
            status="current",
            scope=scope,
            effective_from=None,
            observed_at=datetime.now(UTC),
        )

        async def read(
            *, organization_id: uuid.UUID, claim_id: uuid.UUID, scopes: Sequence[ClaimScope]
        ) -> ClaimView | None:
            assert organization_id == deps.organization_id
            assert claim_id == claim.id
            assert all(not item.scope_key.startswith("person:") for item in scopes)
            return claim if ClaimScope(key) in scopes else None

        with (
            patch("app.services.memory._runtime.project_of", AsyncMock(return_value=project)),
            patch("app.services.memory._runtime.claim_for_approval", side_effect=read),
        ):
            assert await correction_is_wide(deps, {"claim_id": str(claim_id)}) is True


def _correction_row(triggered_by: uuid.UUID) -> ApprovalRow:
    return ApprovalRow(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        agent_name="Helper",
        tool_id=CORRECT,
        tool_args={"claim_id": "c", "statement": "Office closes at five"},
        capability_tool_id=CORRECT,
        context={"before": "Office closes at six", "after": "Office closes at five"},
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


async def test_a_queue_reader_who_may_not_see_the_run_reads_neither_version(
    mock_db_session,
) -> None:
    reader = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.MEMBER.value
    )

    [read] = await ApprovalService(mock_db_session).as_read_by(
        reader, [_correction_row(triggered_by=uuid.uuid4())]
    )

    assert read.content_hidden
    assert read.context == {}
    assert read.tool_args == {"claim_id": "c"}
