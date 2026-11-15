"""Tests for the secret-request shapes (#13).

Everything here feeds a value into the vault, which is why the edge cases
matter more than they look: a value that reaches a transcript, a run record
or an audit entry is a leak, not a bug in a form. Each test below pins one
place the value must never appear.
"""

import json
from types import SimpleNamespace

import pytest
from pydantic_ai.exceptions import CallDeferred
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart

from app.agents.secret_request import (
    SECRET_DECLINED_RESULT,
    SECRET_REQUEST_DEFERRED_KIND,
    _call_args,
    park_the_secret_request,
    parked_secret_request_items,
    parked_secret_requests_by_call,
    secret_request_item,
    secret_request_result,
)

pytestmark = pytest.mark.anyio

SENTINEL = "sk-test-SENTINEL-VALUE-7f3a9c"


def _call(tool_call_id: str = "call-1") -> ToolCallPart:
    return ToolCallPart(
        "request_secret",
        {
            "secret_name": "acme_api_key",
            "what_for": "Acme CRM, to list contacts",
            "kind": "api_key",
        },
        tool_call_id=tool_call_id,
    )


def _paused(messages: list) -> dict:
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    return {
        "messages": json.loads(ModelMessagesTypeAdapter.dump_json(messages)),
        "tool_call_ids": {},
        "questions": [],
        "secret_requests": ["call-1"],
    }


class TestSecretRequestItem:
    @pytest.mark.security
    def test_a_request_needs_a_name_and_a_reason(self):
        item = secret_request_item(_call())

        assert item.secret_name == "acme_api_key"
        assert item.what_for == "Acme CRM, to list contacts"
        assert item.kind == "api_key"

    @pytest.mark.security
    def test_a_request_without_a_name_is_refused(self):
        call = ToolCallPart(
            "request_secret", {"secret_name": "  ", "what_for": "x"}, tool_call_id="c"
        )
        with pytest.raises(ValueError, match="secret_name"):
            secret_request_item(call)

    @pytest.mark.security
    def test_a_request_without_a_reason_is_refused(self):
        call = ToolCallPart(
            "request_secret", {"secret_name": "x", "what_for": "  "}, tool_call_id="c"
        )
        with pytest.raises(ValueError, match="what_for"):
            secret_request_item(call)

    @pytest.mark.security
    def test_args_stored_as_a_json_string_still_parse(self):
        call = ToolCallPart(
            "request_secret",
            json.dumps({"secret_name": "x", "what_for": "y"}),
            tool_call_id="c",
        )
        assert secret_request_item(call).secret_name == "x"


class TestParkedItems:
    @pytest.mark.security
    def test_parked_calls_map_back_to_the_card(self):
        items = parked_secret_request_items(_paused([ModelResponse(parts=[_call()])]))

        assert [item.secret_name for item in items] == ["acme_api_key"]

    @pytest.mark.security
    def test_a_malformed_call_is_skipped_rather_than_breaking_the_read(self):
        bad = ToolCallPart(
            "request_secret", {"secret_name": "", "what_for": ""}, tool_call_id="call-1"
        )
        assert parked_secret_request_items(_paused([ModelResponse(parts=[bad])])) == []

    @pytest.mark.security
    def test_no_parked_state_means_no_requests(self):
        assert parked_secret_request_items(None) == []
        assert parked_secret_requests_by_call({"secret_requests": "not-a-list"}) == {}


@pytest.mark.security
async def test_parking_raises_the_deferred_kind():
    with pytest.raises(CallDeferred) as caught:
        await park_the_secret_request()

    assert caught.value.metadata == {"kind": SECRET_REQUEST_DEFERRED_KIND}


class TestResultStringsNeverCarryAValue:
    @pytest.mark.security
    def test_the_fulfilled_result_names_the_secret_and_its_hint_only(self):
        result = secret_request_result("acme_api_key", "9c2f")

        assert "acme_api_key" in result
        assert "9c2f" in result
        assert SENTINEL not in result

    @pytest.mark.security
    def test_the_declined_result_names_no_secret_at_all(self):
        assert SENTINEL not in SECRET_DECLINED_RESULT
        assert "declined" in SECRET_DECLINED_RESULT


class TestCallArgsShapes:
    """`_call_args` reads whatever shape a stored call kept, or nothing."""

    @pytest.mark.security
    def test_malformed_json_string_args_read_as_nothing(self):
        call = ToolCallPart("request_secret", "{not json", tool_call_id="c")
        assert _call_args(call) == {}

    @pytest.mark.security
    def test_json_that_is_not_an_object_reads_as_nothing(self):
        call = ToolCallPart("request_secret", "[1, 2]", tool_call_id="c")
        assert _call_args(call) == {}

    @pytest.mark.security
    def test_args_that_are_neither_object_nor_string_read_as_nothing(self):
        assert _call_args(SimpleNamespace(args=[1, 2])) == {}


class TestParkedItemsEdgeCases:
    @pytest.mark.security
    def test_no_wanted_calls_means_no_requests(self):
        assert parked_secret_requests_by_call({"messages": [], "secret_requests": []}) == {}
        assert parked_secret_requests_by_call({"messages": [], "secret_requests": [123]}) == {}

    @pytest.mark.security
    def test_a_user_message_is_skipped_not_read_as_a_request(self):
        items = parked_secret_request_items(
            _paused(
                [
                    ModelRequest(parts=[UserPromptPart(content="hi")]),
                    ModelResponse(parts=[_call()]),
                ]
            )
        )

        assert [item.secret_name for item in items] == ["acme_api_key"]

    @pytest.mark.security
    def test_parts_that_are_not_the_wanted_call_are_skipped(self):
        items = parked_secret_request_items(
            _paused(
                [
                    ModelResponse(
                        parts=[
                            TextPart(content="thinking"),
                            ToolCallPart(
                                "request_secret",
                                {"secret_name": "other_key", "what_for": "other work"},
                                tool_call_id="other-call",
                            ),
                        ]
                    )
                ]
            )
        )

        assert items == []
