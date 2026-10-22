"""Naming a parked call for the person deciding it - and never letting that block it.

An approval card that says `table_id: 6f1c…` asks a person to approve something
they cannot read, so a tool may describe its parked call: its ids as names. The
description is a courtesy and the approval is not, which is what most of this
file guards - a describer that fails, hangs or answers nothing leaves the call
parked exactly as it was, with no context. The real access checks behind the
table describers are proved against Postgres in
`tests/integration/test_approval_context.py`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ApprovalRequired
from pydantic_ai.tools import ToolDefinition

from app.agents.capabilities import (
    REGISTRY,
    CapabilityBuildContext,
    CapabilityToolInfo,
    load_builtins,
    register,
)
from app.agents.capabilities.approval import (
    ApprovalGate,
    ApprovalGranted,
    ApprovalPending,
    ApprovalRequest,
    approval_describers,
    approval_tool_ids,
)
from app.agents.capabilities.approval import _capability as gate_module
from app.agents.capabilities.virtual_tables import _describe
from app.agents.capabilities.virtual_tables._describe import (
    APPROVAL_DESCRIBERS,
    describe_record_write,
)
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec
from app.core.exceptions import NotFoundError
from app.services.agent_runner import ApprovalChannel

# What an approver is shown, and whether a held call is described: approval-gate behaviour.
pytestmark = [pytest.mark.anyio, pytest.mark.security]

NAMES = {"table": "Support"}


@pytest.fixture(autouse=True)
def _builtins_loaded() -> None:
    load_builtins()


def _tool_def(name: str = "update_record", capability_id: str | None = "virtual_tables"):
    return ToolDefinition(
        name=name,
        parameters_json_schema={"type": "object", "properties": {}},
        capability_id=capability_id,
    )


def _ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.deps = AgentDeps(
        run_id=uuid.uuid4(), request_approval=AsyncMock(return_value=ApprovalPending())
    )
    return ctx


async def _described(request: ApprovalRequest) -> dict[str, str] | None:
    """What the channel would store for the request: its describer's answer, if any."""
    return None if request.describe is None else await request.describe()


async def _park(gate: ApprovalGate, tool_def: ToolDefinition | None = None) -> ApprovalRequest:
    """Drive one gated call into a pending decision and return what was asked."""
    ctx = _ctx()
    tool_def = tool_def or _tool_def()
    with pytest.raises(ApprovalRequired):
        await gate.wrap_tool_execute(
            ctx,
            call=MagicMock(tool_call_id="call-1"),
            tool_def=tool_def,
            args={"table_id": uuid.uuid4()},
            handler=AsyncMock(),
        )
    [request] = ctx.deps.request_approval.await_args.args
    return request


class TestTheGateDescribes:
    async def test_a_described_call_is_asked_about_with_its_names(self):
        describe = AsyncMock(return_value=NAMES)
        gate = ApprovalGate(
            required_tool_names=frozenset({"update_record"}), describers={"update_record": describe}
        )

        request = await _park(gate)

        # Not yet: the channel describes a call only once it knows it will record it.
        describe.assert_not_awaited()
        assert await _described(request) == NAMES
        # The describer reads the validated arguments, so an id is still a `UUID`.
        [deps, args] = describe.await_args.args
        assert isinstance(args["table_id"], uuid.UUID)
        assert isinstance(deps, AgentDeps)

    async def test_a_describer_that_fails_still_parks_the_call(self):
        describe = AsyncMock(side_effect=RuntimeError("database went away"))
        gate = ApprovalGate(
            required_tool_names=frozenset({"update_record"}), describers={"update_record": describe}
        )

        request = await _park(gate)

        assert await _described(request) is None
        assert request.tool_name == "update_record"

    async def test_a_describer_that_hangs_is_given_up_on(self):
        async def hang(_deps: AgentDeps, _args: Mapping[str, Any]) -> dict[str, str]:
            await asyncio.sleep(10)
            return NAMES

        gate = ApprovalGate(
            required_tool_names=frozenset({"update_record"}), describers={"update_record": hang}
        )

        with patch.object(gate_module, "DESCRIBE_TIMEOUT_SECONDS", 0.01):
            request = await _park(gate)
            assert await _described(request) is None

    async def test_an_empty_description_is_no_context(self):
        gate = ApprovalGate(
            required_tool_names=frozenset({"update_record"}),
            describers={"update_record": AsyncMock(return_value={})},
        )

        assert await _described(await _park(gate)) is None

    @pytest.mark.security
    async def test_a_tool_no_capability_owns_is_never_described(self):
        """Under `ASK_ALL` an MCP tool is gated too; a describer written for another
        tool of the same name must not run against its arguments."""
        describe = AsyncMock(return_value=NAMES)
        gate = ApprovalGate(gate_every_tool=True, describers={"update_record": describe})

        request = await _park(gate, _tool_def(capability_id=None))

        assert (request.describe, request.capability_tool_id) == (None, None)
        describe.assert_not_awaited()

    async def test_a_tool_with_no_describer_is_asked_about_as_before(self):
        request = await _park(ApprovalGate(required_tool_names=frozenset({"update_record"})))

        assert request.describe is None

    async def test_a_renamed_tool_is_asked_about_under_its_stable_id(self):
        """The card words a call by tool; a renamed `update_record` must still find its words."""
        gate = ApprovalGate(
            required_tool_names=frozenset({"change_record"}),
            tool_ids={"change_record": "update_record"},
        )

        request = await _park(gate, _tool_def("change_record"))

        assert (request.tool_name, request.capability_tool_id) == (
            "change_record",
            "update_record",
        )


def _channel(**kwargs: Any) -> ApprovalChannel:
    return ApprovalChannel(
        organization_id=uuid.uuid4(), agent_id=uuid.uuid4(), run_id=uuid.uuid4(), **kwargs
    )


def _request(describe: AsyncMock) -> ApprovalRequest:
    return ApprovalRequest(
        capability_id="virtual_tables",
        tool_name="change_record",
        tool_call_id="call-1",
        tool_args={"table_id": "6f1c"},
        capability_tool_id="update_record",
        describe=describe,
    )


class TestTheChannelKeepsTheNames:
    async def test_a_parked_call_carries_its_context_to_its_row(self):
        channel = _channel()

        await channel(_request(AsyncMock(return_value=NAMES)))

        [parked] = channel.requested
        assert (parked.tool_args, parked.context) == ({"table_id": "6f1c"}, NAMES)
        assert (parked.tool_name, parked.capability_tool_id) == ("change_record", "update_record")

    async def test_a_call_granted_by_standing_consent_is_described_for_its_row(self):
        channel = _channel(standing_consent_by=uuid.uuid4())

        decision = await channel(_request(AsyncMock(return_value=NAMES)))

        assert isinstance(decision, ApprovalGranted)
        [recorded] = channel.requested
        assert (recorded.standing, recorded.context) == (True, NAMES)

    async def test_a_call_already_decided_is_not_described(self):
        """A resumed run answers from its decisions; describing would cost a session
        and up to the timeout for a description nobody reads."""
        describe = AsyncMock(return_value=NAMES)
        channel = _channel(decided={"call-1": ApprovalGranted({"table_id": "6f1c"})})

        decision = await channel(_request(describe))

        assert decision == ApprovalGranted({"table_id": "6f1c"})
        describe.assert_not_awaited()
        assert channel.requested == []

    async def test_the_gate_runs_a_pre_decided_call_without_describing_it(self):
        describe = AsyncMock(return_value=NAMES)
        gate = ApprovalGate(
            required_tool_names=frozenset({"update_record"}), describers={"update_record": describe}
        )
        args = {"table_id": uuid.uuid4()}
        channel = _channel(decided={"call-1": ApprovalGranted({"table_id": str(args["table_id"])})})
        ctx = MagicMock()
        ctx.deps = AgentDeps(run_id=uuid.uuid4(), request_approval=channel)
        handler = AsyncMock(return_value="updated")

        result = await gate.wrap_tool_execute(
            ctx,
            call=MagicMock(tool_call_id="call-1"),
            tool_def=_tool_def(),
            args=args,
            handler=handler,
        )

        assert result == "updated"
        handler.assert_awaited_once_with(args)
        describe.assert_not_awaited()


class TestWhichToolsAreDescribed:
    def test_a_renamed_tool_keeps_its_describer(self):
        spec = AgentSpec(
            name="Clerk",
            capabilities=[
                {
                    "id": "virtual_tables",
                    "tool_overrides": {"update_record": {"name": "change_record"}},
                },
                # Bound, with no describer of its own: nothing of it is described.
                {"id": "clock"},
            ],
        )

        describers = approval_describers(spec)
        tool_ids = approval_tool_ids(spec)

        assert tool_ids["change_record"] == "update_record"
        assert "update_record" not in tool_ids
        assert describers["change_record"] is describe_record_write
        assert "update_record" not in describers
        assert describers["delete_record"] is describe_record_write
        # Reads are never parked by the spec, so nothing describes them.
        assert "list_records" not in describers

    def test_a_disabled_binding_describes_nothing(self):
        spec = AgentSpec(name="Clerk", capabilities=[{"id": "virtual_tables", "enabled": False}])

        assert approval_describers(spec) == {}

    def test_the_table_writes_are_the_described_tools(self):
        assert set(APPROVAL_DESCRIBERS) == {
            "create_record",
            "upsert_record",
            "update_record",
            "delete_record",
        }
        assert REGISTRY["virtual_tables"].describers == APPROVAL_DESCRIBERS

    def test_describing_a_tool_the_capability_does_not_declare_is_refused(self):
        with pytest.raises(RuntimeError, match="does not declare"):
            register(
                id="test_stray_describer",
                name="Stray",
                category="test",
                description="Describes a tool it never declared",
                tools=(CapabilityToolInfo(id="real", description="Exists."),),
                describers={"imagined": AsyncMock()},
            )
        assert "test_stray_describer" not in REGISTRY

    def test_a_capability_may_describe_its_own_tools(self):
        @register(
            id="test_described",
            name="Described",
            category="test",
            description="Describes its own tool",
            tools=(CapabilityToolInfo(id="real", description="Exists."),),
            describers={"real": AsyncMock()},
        )
        def _build(_ctx: CapabilityBuildContext) -> None:
            return None

        try:
            assert set(REGISTRY["test_described"].describers) == {"real"}
        finally:
            REGISTRY.pop("test_described")


# -- the table describers, with the services stubbed -----------------------------

TABLE = SimpleNamespace(id=uuid.uuid4(), name="Orders")
PERSON = uuid.uuid4()


def _deps(person: uuid.UUID | None = PERSON) -> AgentDeps:
    return AgentDeps(organization_id=uuid.uuid4(), run_person=person)


@asynccontextmanager
async def _session() -> AsyncIterator[MagicMock]:
    yield MagicMock()


def _stubbed(*, table: Any = TABLE, record: Any = None, member: Any = "member"):
    """Patch the session, the member and the service the describers read through."""
    tables = MagicMock()
    tables.describe_table = AsyncMock(
        side_effect=table if isinstance(table, Exception) else None, return_value=table
    )
    tables.get_record = AsyncMock(
        side_effect=record if isinstance(record, Exception) else None, return_value=record
    )
    return (
        patch.object(_describe, "get_db_context", _session),
        patch.object(_describe, "acting_member", AsyncMock(return_value=member)),
        patch.object(_describe, "VirtualTableService", MagicMock(return_value=tables)),
    )


async def _with(patches: tuple[Any, ...], call: Any) -> Any:
    with patches[0], patches[1], patches[2]:
        return await call


def _missing() -> NotFoundError:
    return NotFoundError(message="Not found", details={})


class TestWritingARecord:
    @pytest.mark.parametrize(
        "args",
        [
            {"external_id": " A-1 ", "values": {"Customer": "Ada"}},
            {"values": {"Quantity": 2, "Customer": "Ada Lovelace"}},
            {"record_id": str(uuid.uuid4())},
            {},
        ],
        ids=["external id", "values", "record id", "nothing else"],
    )
    @pytest.mark.security
    async def test_only_the_table_is_named(self, args: dict[str, Any]):
        """No record label: it is a cell's text, stored on a row every approver reads
        and kept after the record is gone."""
        patches = _stubbed(
            record=SimpleNamespace(external_id="B-7", values={str(uuid.uuid4()): "Grace"})
        )

        context = await _with(
            patches, describe_record_write(_deps(), {"table_id": TABLE.id, **args})
        )

        assert context == {"table": "Orders"}

    @pytest.mark.security
    async def test_the_stored_record_is_never_read(self):
        tables = MagicMock(describe_table=AsyncMock(return_value=TABLE), get_record=AsyncMock())
        patches = _stubbed()
        with (
            patches[0],
            patches[1],
            patch.object(_describe, "VirtualTableService", MagicMock(return_value=tables)),
        ):
            await describe_record_write(_deps(), {"table_id": TABLE.id, "record_id": uuid.uuid4()})

        tables.get_record.assert_not_awaited()

    @pytest.mark.security
    async def test_a_table_the_person_may_not_see_is_not_named(self):
        context = await _with(
            _stubbed(table=_missing()),
            describe_record_write(_deps(), {"table_id": uuid.uuid4(), "external_id": "A-1"}),
        )

        assert context is None

    @pytest.mark.security
    async def test_a_run_for_nobody_names_nothing(self):
        context = await _with(
            _stubbed(), describe_record_write(_deps(None), {"table_id": TABLE.id})
        )

        assert context is None
