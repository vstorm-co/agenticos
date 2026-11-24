"""Bounded model context, lossless detail reads and receipts after successful writes."""

import json
from decimal import Decimal
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field, JsonValue, ValidationError

from app.schemas.agent import AgentRunResult, ParkedCall, RunStep
from app.services.platform_mcp import platform_tool_catalog
from app.services.platform_mcp._disclosure import (
    MAX_RESPONSE_BYTES,
    Operation,
    _handle,
    _open_handle,
    details,
    disclosure_operations,
    encoded,
    fingerprint,
    listing,
    metadata,
    page,
    pointer,
    protect,
)
from app.services.platform_mcp._tools import platform_tools

pytestmark = pytest.mark.anyio
ID = UUID("00000000-0000-4000-8000-000000000001")


def test_hashes_ignore_object_key_order_but_detect_changed_values() -> None:
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})
    assert fingerprint("before") != fingerprint("after")


def test_page_filters_before_slicing_and_preserves_real_totals() -> None:
    assert page(["other", "match 1", "match 2"], q="MATCH", limit=1) == {
        "items": ["match 1"],
        "total": 2,
        "next_skip": 1,
    }
    assert page(["x"], skip=4)["next_skip"] is None


@pytest.mark.parametrize("value", [None, True, 12, "text", [1]])
def test_scalar_receipts_do_not_repeat_bodies(value: JsonValue) -> None:
    assert isinstance(metadata(value), dict)


def test_receipt_omits_bodies_long_keys_and_large_values() -> None:
    assert metadata(
        {"id": "one", "content": "body", "long": "x" * 301, "x" * 100: 1, "ok": True}
    ) == {
        "id": "one",
        "ok": True,
    }
    assert len(metadata({str(i): i for i in range(100)})) == 20


@pytest.mark.parametrize("container", ["object", "array"])
def test_unpaged_discovery_searches_full_rows_before_projecting(container: str) -> None:
    rows: list[JsonValue] = [{"id": "one", "config": {"source": "MATCH"}}, {"id": "two"}]
    value: JsonValue = rows if container == "array" else {"items": rows}
    assert listing(value, local=True, q="match")["items"] == [{"id": "one"}]
    assert listing(value, local=True, detailed=True)["items"] == rows


def test_server_pages_keep_totals_and_do_not_slice_a_second_time() -> None:
    result = listing({"items": [{"id": "third", "content": "body"}], "total": 5}, skip=2, limit=1)
    assert result == {"items": [{"id": "third"}], "total": 5, "next_skip": 3}
    assert listing({"items": [], "total": 5}, skip=5)["next_skip"] is None
    assert listing({"items": [1]}, detailed=True)["items"] == [1]
    assert listing({"providers": []}) == {"providers": []}
    with pytest.raises(TypeError):
        listing(1)


@pytest.mark.parametrize("path", ["bad", "/missing", "/items/9", "/items/-1"])
def test_unknown_pointers_are_explicit_refusals(path: str) -> None:
    with pytest.raises(ToolError):
        pointer({"items": [1]}, path)


def test_pointers_support_escaped_keys_empty_names_and_array_indices() -> None:
    value: JsonValue = {"a/b": {"~": [3]}, "": 4}
    assert pointer(value, "") == value
    assert pointer(value, "/a~1b/~0/0") == 3
    assert pointer(value, "/") == 4


def test_text_windows_continue_without_mixing_revisions() -> None:
    first = details("abcdef", chars=2)
    assert first["content"] == "ab" and first["next_offset"] == 2
    second = details("abcdef", offset=2, chars=10, expected_hash=str(first["value_hash"]))
    assert second["content"] == "cdef" and second["next_offset"] is None
    assert details("abc", offset=9)["content"] == ""
    with pytest.raises(ToolError, match="changed"):
        details("changed", expected_hash=str(first["value_hash"]))


def test_json_fragments_can_be_assembled_into_the_original_contract() -> None:
    value: JsonValue = {"$defs": {"record": {"description": "żółw" * 1000}}, "type": "object"}
    chunks: list[str] = []
    offset = 0
    digest = fingerprint(value)
    while True:
        result = details(value, mode="content", offset=offset, chars=500, expected_hash=digest)
        assert result["encoding"] == "json-fragment"
        chunks.append(str(result["content"]))
        next_offset = result["next_offset"]
        if next_offset is None:
            break
        assert isinstance(next_offset, int)
        offset = next_offset
    assert json.loads("".join(chunks)) == value


def test_inspection_pages_keys_and_large_row_summaries_with_a_continuation() -> None:
    assert details({"b": 2, "a": 1}, limit=1)["items"][0]["pointer"] == "/a"
    assert details({"b": 2, "a": 1}, limit=1)["next_skip"] == 1
    assert details(None)["value"] is None
    assert details([1], skip=9)["next_skip"] is None
    fat: JsonValue = [{str(i): "x" * 200 for i in range(20)} for _ in range(50)]
    result = details(fat, limit=50)
    assert result["next_skip"] is not None
    assert len(encoded(result).encode()) < MAX_RESPONSE_BYTES


async def test_small_reads_keep_their_contract_and_large_reads_offer_navigation() -> None:
    async def read() -> JsonValue:
        return {"id": "one", "content": "x" * 100000}

    result = await protect("read", read, writes=False, credential=lambda: "caller")()
    assert result["summary"] == {"id": "one"}
    assert result["read_tool"] == "read_platform_details"
    assert result["request_completed"] is True

    async def small() -> JsonValue:
        return {"id": "one"}

    assert await protect("small", small, writes=False)() == {"id": "one"}

    async def array() -> JsonValue:
        return [1]

    assert (await protect("array", array, writes=False, credential=lambda: "caller")())[
        "details_available"
    ] is True


async def test_large_write_is_a_receipt_with_status_and_questions_not_a_failure() -> None:
    calls = 0

    async def write() -> JsonValue:
        nonlocal calls
        calls += 1
        return {
            "run_id": str(ID),
            "status": "awaiting_answer",
            "content": "x" * 100000,
            "questions": [{"text": "Choose"}],
            "next_actions": ["answer"],
            "workflow": {"id": str(ID), "draft_graph": {}},
            "table": {"id": "x" * 100000},
        }

    result = await protect("write", write, writes=True)()
    assert calls == 1
    assert result["summary"]["status"] == "awaiting_answer"
    assert result["summary"]["questions"] == [{"text": "Choose"}]
    assert result["summary"]["workflow"] == {"id": str(ID)}
    assert result["read_tool"] is None
    assert len(encoded(result).encode()) < MAX_RESPONSE_BYTES


async def test_huge_interactive_data_still_does_not_invert_a_committed_request() -> None:
    async def write() -> JsonValue:
        return {"status": "awaiting_answer", "questions": ["x" * 100000]}

    result = await protect("write", write, writes=True)()
    assert result["request_completed"] is True
    assert "questions" not in result["summary"]
    assert result["summary"]["status"] == "awaiting_answer"


async def test_detail_continuation_repeats_only_the_previously_authorized_read() -> None:
    calls: list[UUID] = []
    body = "x" * 20000

    async def read(resource_id: UUID, detailed: bool = False) -> JsonValue:
        calls.append(resource_id)
        return {"body": body, "detailed": detailed}

    operations: tuple[Operation, ...] = (("read", read, False),)
    reader = disclosure_operations(operations, lambda: "caller")[0][1]
    receipt = await protect("read", read, writes=False, credential=lambda: "caller")(ID)
    result = await reader(receipt["continuation"], pointer="/body", chars=100)
    assert result["content"] == "x" * 100
    assert (await reader(receipt["continuation"], pointer="/detailed"))["value"] is False
    assert calls == [ID, ID, ID]
    body = "changed"
    with pytest.raises(ToolError, match="changed"):
        await reader(receipt["continuation"])


@pytest.mark.security
@pytest.mark.parametrize("name", ["write", "unknown", "read_platform_details"])
async def test_detail_reader_cannot_execute_writes_or_recurse(name: str) -> None:
    async def write() -> JsonValue:
        pytest.fail("A read tool executed a write")

    reader = disclosure_operations((("write", write, True),), lambda: "caller")[0][1]
    with pytest.raises(ToolError, match="no longer available"):
        await reader(_handle(name, {}, {}, "caller"))


async def test_detail_reader_uses_the_original_input_constraints() -> None:
    async def read(limit: Annotated[int, Field(ge=1, le=2)]) -> JsonValue:
        return {"limit": limit}

    reader = disclosure_operations((("read", read, False),), lambda: "caller")[0][1]
    with pytest.raises(ValidationError):
        await reader(_handle("read", {"limit": 3}, {}, "caller"))


@pytest.mark.security
@pytest.mark.parametrize("handle", ["", "bad.signature", "x" * 24001])
def test_forged_continuations_cannot_authorize_a_read(handle: str) -> None:
    with pytest.raises(ToolError, match="Invalid or expired"):
        _open_handle(handle, "caller")


@pytest.mark.security
@pytest.mark.parametrize("caller", [None, "other"])
def test_continuations_cannot_cross_credentials(caller: str | None) -> None:
    with pytest.raises(ToolError):
        _open_handle(_handle("read", {}, {}, "caller"), caller)


@pytest.mark.security
def test_continuations_expire_and_cannot_have_their_arguments_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.platform_mcp._disclosure as module

    handle = _handle("read", {"id": "allowed"}, {}, "caller")
    body, signature = handle.split(".")
    with pytest.raises(ToolError):
        _open_handle(body + "." + "0" * len(signature), "caller")
    now = module.time.time()
    monkeypatch.setattr(module.time, "time", lambda: now + 301)
    with pytest.raises(ToolError):
        _open_handle(handle, "caller")


async def test_large_reads_without_a_caller_or_with_excessive_arguments_refuse() -> None:
    async def read(q: str = "") -> JsonValue:
        return {"body": "x" * 20000}

    with pytest.raises(ToolError, match="authenticated"):
        await protect("read", read, writes=False)()
    with pytest.raises(ToolError, match="arguments exceed"):
        await protect("read", read, writes=False, credential=lambda: "caller")("x" * 9000)
    result = await protect("read_platform_details", read, writes=False)()
    assert result["continuation"] is None


async def test_a_valid_large_case_write_returns_identity_without_echoing_case_text() -> None:
    from app.schemas.dataset import DatasetCaseCreate

    api = MagicMock()
    api.request = AsyncMock(
        return_value={
            "id": str(ID),
            "case_id": str(ID),
            "input": "x" * 32000,
            "reference_answer": "y" * 32000,
            "counter_example": "z" * 32000,
        }
    )
    tools = {tool.name: tool.function for tool in platform_tools(api)}
    result = await tools["add_dataset_case"](
        ID,
        DatasetCaseCreate(
            input="x" * 32000, reference_answer="y" * 32000, counter_example="z" * 32000
        ),
    )
    assert api.request.await_count == 1
    assert result["case_id"] == str(ID)
    assert result["read_tool"] == "get_dataset_case"
    assert len(encoded(result).encode()) < 1000


async def test_every_tool_definition_and_the_complete_catalog_fit_discovery_allowances() -> None:
    server = FastMCP("budget")
    for tool in platform_tool_catalog():
        server.tool(tool.function)
    async with Client(server) as client:
        tools = await client.list_tools()
    rows = [tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in tools]
    assert len(json.dumps(rows, ensure_ascii=False).encode()) < 230000
    assert max(len(json.dumps(row, ensure_ascii=False).encode()) for row in rows) < 6000
    names = {row["name"] for row in rows}
    assert {"get_authoring_schema", "read_platform_details", "get_dataset_case"} <= names


def test_inspection_can_search_children_before_paging() -> None:
    result = details(
        {"irrelevant": {"type": "integer"}, "chosen": {"type": "string"}}, q="chosen", limit=1
    )
    assert result["total"] == 1 and result["items"][0]["pointer"] == "/chosen"
    assert details(["one", "two"], q="missing")["items"] == []


def test_verbose_refusals_are_bounded_without_becoming_successful_or_empty() -> None:
    from app.services.platform_mcp._disclosure import error_envelope

    small: dict[str, JsonValue] = {
        "status": 403,
        "code": "FORBIDDEN",
        "message": "Missing permission",
        "details": {"required": ["agents:edit"]},
    }
    assert json.loads(error_envelope(small)) == {"error": small}
    large: dict[str, JsonValue] = {
        **small,
        "message": "x" * 100000,
        "details": {
            "field_errors": [{"field": "input", "message": "too large"} for _ in range(1000)],
            "required": ["agents:edit"],
            "x" * 100: "large",
            "unstructured": "x" * 100000,
            "huge_rows": [{str(i): "x" * 200 for i in range(20)} for _ in range(100)],
        },
    }
    result = error_envelope(large)
    assert len(result.encode()) < MAX_RESPONSE_BYTES
    parsed = json.loads(result)["error"]
    assert parsed["status"] == 403 and parsed["details_omitted"]
    assert parsed["details"]["required"] == ["agents:edit"]
    assert parsed["details"]["field_errors"]["total"] == 1000
    assert "input" in result
    assert "error" in json.loads(error_envelope({"message": ["x" * 100000], "details": None}))


async def test_direct_tool_diagnostics_also_obey_the_context_allowance() -> None:
    from app.services.platform_mcp import _with_domain_errors

    async def failed() -> dict[str, JsonValue]:
        raise ToolError("bad input " * 10000)

    with pytest.raises(ToolError) as caught:
        await _with_domain_errors(failed)()
    assert len(str(caught.value).encode()) < MAX_RESPONSE_BYTES

    async def ordinary() -> dict[str, JsonValue]:
        raise ToolError("ordinary refusal")

    with pytest.raises(ToolError, match="ordinary refusal"):
        await _with_domain_errors(ordinary)()


def test_discovery_counts_dependency_arrays_instead_of_loading_every_use() -> None:
    assert metadata(
        {"id": "one", "used_by": [{"name": "reader"}], "resources": [], "excerpt": "large context"}
    ) == {"id": "one", "used_by_count": 1, "resources_count": 0}


async def test_protocol_validation_errors_are_bounded_before_operation_execution() -> None:
    from app.services.platform_mcp import _BoundToolErrors

    server = FastMCP("validation", middleware=[_BoundToolErrors()])

    @server.tool
    async def read(identities: list[UUID]) -> dict[str, JsonValue]:
        pytest.fail("Invalid arguments reached the operation")

    async with Client(server) as client:
        with pytest.raises(ToolError) as error:
            await client.call_tool("read", {"identities": ["bad" * 1000] * 100})
        assert len(str(error.value).encode()) < 8192
        assert "narrow the input" in str(error.value)
        with pytest.raises(ToolError):
            await client.call_tool("read", {"identities": ["invalid"]})


async def test_bound_error_middleware_leaves_a_small_success_unchanged() -> None:
    from app.services.platform_mcp import _BoundToolErrors

    server = FastMCP("ok", middleware=[_BoundToolErrors()])

    @server.tool
    async def read() -> dict[str, JsonValue]:
        return {"ok": True}

    async with Client(server) as client:
        assert (await client.call_tool("read", {})).data == {"ok": True}


@pytest.mark.security
def test_continuation_validation_refuses_signed_invalid_payloads_and_non_ascii_signatures() -> None:
    import base64

    from app.services.platform_mcp._disclosure import _mac

    payload = b'{"operation":1}'
    body = base64.urlsafe_b64encode(payload).decode()
    for handle in (body + "." + _mac(payload), body + "." + "界"):
        with pytest.raises(ToolError):
            _open_handle(handle, "caller")


def test_metadata_allowance_counts_utf8_bytes() -> None:
    result = metadata({f"field{i}": "界" * 200 for i in range(20)})
    assert len(encoded(result).encode()) <= 2500


async def test_discovery_narrows_routines_and_preserves_explicit_detail_opt_in() -> None:
    api = MagicMock()
    api.credential_id.return_value = "caller"
    api.request = AsyncMock(
        return_value={
            "items": [
                {"id": "one", "name": "chosen", "instructions": "body"},
                {"id": "two", "name": "other"},
            ]
        }
    )
    tools = {tool.name: tool.function for tool in platform_tools(api)}
    selected = await tools["list_routines"](agent_id=ID, q="chosen", limit=1)
    assert selected["total"] == 1 and len(selected["items"]) == 1
    assert "instructions" not in selected["items"][0]
    with pytest.raises(ToolError):
        await tools["list_routines"](q="global search")
    api.request.return_value = {
        "items": [{"case_id": str(ID), "input": "question", "reference_answer": "answer"}],
        "total": 1,
    }
    full = await tools["list_dataset_cases"](ID, detailed=True)
    assert full["items"][0]["reference_answer"] == "answer"
    api.request.return_value = {"id": str(ID), "content": "body", "resources": []}
    skill = await tools["get_skill"](ID)
    assert skill["content_chars"] == 4 and "content" not in skill
    api.request.return_value = [{"id": "board", "name": "Tasks", "config": "large"}]
    assert (await tools["list_task_boards"]())["items"] == [
        {"id": "board", "name": "Tasks", "config": "large"}
    ]


async def test_agent_authoring_preserves_platform_tool_policies_in_compact_inputs() -> None:
    api = MagicMock()
    api.request = AsyncMock(return_value={"id": str(ID)})
    tools = {tool.name: tool.function for tool in platform_tools(api)}
    binding: dict[str, JsonValue] = {
        "account": "platform",
        "approval": "writes",
        "allowed_tools": ["get_agent"],
        "tool_approval": {"get_agent": "required"},
    }
    await tools["create_agent_draft"](
        name="Scoped assistant",
        instructions="Help within the chosen scope.",
        mcp_servers=[binding],
        capabilities=["ask_user"],
    )
    assert api.request.call_args.kwargs["json"]["spec"]["mcp_servers"][0]["tool_approval"] == {
        "get_agent": "required"
    }


async def test_workflow_overviews_and_complete_graph_reads_are_distinct() -> None:
    api = MagicMock()
    api.request = AsyncMock(
        return_value={
            "id": str(ID),
            "draft_graph": {"nodes": [], "bindings": ["preserve"]},
            "draft_revision": 4,
        }
    )
    tools = {tool.name: tool.function for tool in platform_tools(api)}
    overview = await tools["get_workflow_definition"](ID)
    assert overview["graph_available"] is True and "draft_graph" not in overview
    full = await tools["get_workflow_definition"](ID, view="full")
    assert full["draft_graph"]["bindings"] == ["preserve"]


@pytest.mark.parametrize("section", ["summary", "config", "input", "output", "ports", "full"])
async def test_workflow_catalog_discloses_only_the_requested_contract_section(section: str) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.workflow_registry import WorkflowRegistryService

    catalog = await WorkflowRegistryService(MagicMock(spec=AsyncSession)).node_catalog()
    api = MagicMock()
    api.credential_id.return_value = "caller"
    api.request = AsyncMock(return_value=catalog.model_dump(mode="json"))
    tool = {tool.name: tool.function for tool in platform_tools(api)}["get_workflow_node"]
    result = await tool("trigger.manual", section=section)
    assert result["id"] == "trigger.manual"
    if section == "summary":
        assert "config_schema" not in result
    elif section == "full":
        assert "config_schema" in result
    else:
        assert ("ports" if section == "ports" else section + "_schema") in result
    api.refuse.side_effect = ToolError("Not found")
    with pytest.raises(ToolError, match="Not found"):
        await tool("no-such-node")


@pytest.mark.parametrize("tool", ["run_agent", "test_agent_draft", "answer_agent_questions"])
async def test_large_run_history_preserves_the_real_pending_approval_contract(tool: str) -> None:
    pending = ParkedCall(
        id=ID,
        tool_call_id="waiting",
        tool_name="send_email",
        tool_args={"to": "person@example.com"},
    )
    run = AgentRunResult(
        run_id=ID,
        output="",
        status="awaiting_approval",
        cost_usd=Decimal("0"),
        input_tokens=1,
        output_tokens=1,
        parked=[pending],
        steps=[RunStep(tool_call_id="finished", tool_name="search", result="x" * 100000)],
    )
    calls = 0

    async def write() -> JsonValue:
        nonlocal calls
        calls += 1
        return run.model_dump(mode="json")

    result = await protect(tool, write, writes=True)()
    assert calls == 1 and result["continuation"] is None
    assert result["summary"]["status"] == "awaiting_approval"
    assert result["summary"]["parked"] == [pending.model_dump(mode="json")]
    assert "approval_details_omitted" not in result["summary"]
    assert len(encoded(result).encode()) <= MAX_RESPONSE_BYTES


async def test_large_pending_approvals_keep_bounded_identities_and_a_full_console_review_link() -> (
    None
):
    run = AgentRunResult(
        run_id=ID,
        output="",
        status="awaiting_approval",
        cost_usd=Decimal("0"),
        input_tokens=1,
        output_tokens=1,
        parked=[
            ParkedCall(
                id=UUID(int=index + 1),
                tool_call_id=f"waiting-{index}",
                tool_name="send_email",
                tool_args={"body": "private argument" * 1000},
            )
            for index in range(12)
        ],
    )

    async def write() -> JsonValue:
        return run.model_dump(mode="json")

    result = await protect("run_agent", write, writes=True)()
    summary = result["summary"]
    assert summary["parked_total"] == 12 and len(summary["parked"]) == 10
    assert summary["parked"][0] == {
        "id": str(UUID(int=1)),
        "tool_call_id": "waiting-0",
        "tool_name": "send_email",
    }
    assert summary["approval_details_omitted"] is True
    destination = urlsplit(summary["approval_review_url"])
    assert destination.path == "/runs"
    assert parse_qs(destination.query) == {"tab": ["approvals"], "run": [str(ID)]}
    assert "never approve" in summary["approval_instruction"]
    assert "private argument" not in encoded(result)
    assert result["continuation"] is None and result["request_completed"] is True
    assert len(encoded(result).encode()) <= MAX_RESPONSE_BYTES


async def test_an_unidentified_large_interaction_hands_off_to_the_queue_without_inventing_ids() -> (
    None
):
    async def write() -> JsonValue:
        return {
            "status": "awaiting_approval",
            "parked": [
                {"id": "approval", "tool_name": "tool", "tool_args": {"body": "x" * 100000}},
                "unsupported entry",
            ],
        }

    result = await protect("write", write, writes=True)()
    summary = result["summary"]
    assert summary["parked"] == [{"id": "approval", "tool_name": "tool"}]
    assert parse_qs(urlsplit(summary["approval_review_url"]).query) == {"tab": ["approvals"]}
    assert len(encoded(result).encode()) <= MAX_RESPONSE_BYTES
