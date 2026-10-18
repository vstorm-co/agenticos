"""Calling another vendor's agent over A2A, and delegating to one (#2092).

The remote agent is an `httpx2.MockTransport` behind the real pinned client, so
the SSRF check runs as it would; DNS answers one public address except for names
that resolve to a private one.
"""

from __future__ import annotations

import json
import socket
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx2
import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.agents import a2a_delegate as delegate_module
from app.agents.a2a_delegate import a2a_delegate, latest_prompt
from app.services import a2a_client
from app.services.a2a_client import A2AClientError, card_address, fetch_card, send_message

pytestmark = pytest.mark.anyio

CARD = {
    "protocolVersion": "0.3.0",
    "name": "Contract reviewer",
    "description": "Reads contracts and flags risky clauses.",
    "url": "https://agents.example.com/a2a/reviewer",
    "skills": [{"id": "review", "name": "Review", "description": "Review a contract"}],
}


@pytest.fixture(autouse=True)
def _dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(host: str, port: object, *_args: object, **_kwargs: object):
        address = "10.0.0.5" if str(host).startswith("internal") else "93.184.216.34"
        return [(2, 1, 6, "", (address, port or 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


def _wire(
    response: httpx2.Response, seen: list[httpx2.Request] | None = None
) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if seen is not None:
            seen.append(request)
        return response

    return httpx2.MockTransport(handler)


def _rpc(result: dict[str, Any]) -> httpx2.Response:
    return httpx2.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": result})


def _task(state: str, *, answer: str = "", note: str | None = None) -> dict[str, Any]:
    task: dict[str, Any] = {
        "kind": "task",
        "id": "t1",
        "contextId": "ctx-1",
        "status": {"state": state},
        "artifacts": [],
    }
    if answer:
        task["artifacts"] = [{"artifactId": "a", "parts": [{"kind": "text", "text": answer}]}]
    if note:
        task["status"]["message"] = {
            "kind": "message",
            "role": "agent",
            "messageId": "m",
            "parts": [{"kind": "text", "text": note}],
        }
    return task


class TestReadingACard:
    @pytest.mark.parametrize(
        ("given", "fetched"),
        [
            (
                "https://agents.example.com",
                "https://agents.example.com/.well-known/agent-card.json",
            ),
            (
                "https://agents.example.com/",
                "https://agents.example.com/.well-known/agent-card.json",
            ),
            ("https://x.example.com/card.json", "https://x.example.com/card.json"),
            # A signed address: the query is the credential, not where the path ends.
            (
                "https://x.example.com/card.json?sig=abc",
                "https://x.example.com/card.json?sig=abc",
            ),
            (
                "https://x.example.com/agent?sig=abc",
                "https://x.example.com/agent/.well-known/agent-card.json?sig=abc",
            ),
        ],
    )
    def test_a_base_address_reads_the_well_known_card(self, given: str, fetched: str) -> None:
        assert card_address(given) == fetched

    async def test_a_card_offering_another_transport_is_refused(self) -> None:
        """Registered, it would fail every delegation: this client speaks JSON-RPC."""
        grpc = {**CARD, "preferredTransport": "GRPC"}
        with pytest.raises(A2AClientError, match="speaks only JSON-RPC"):
            await fetch_card(
                "https://agents.example.com",
                transport=httpx2.MockTransport(lambda _request: httpx2.Response(200, json=grpc)),
            )

    async def test_a_card_is_read_and_validated(self) -> None:
        seen: list[httpx2.Request] = []
        card = await fetch_card(
            "https://agents.example.com", transport=_wire(httpx2.Response(200, json=CARD), seen)
        )
        assert card.name == "Contract reviewer"
        assert card.url == CARD["url"]
        assert str(seen[0].url).endswith("/.well-known/agent-card.json")

    @pytest.mark.security
    async def test_an_address_inside_the_network_is_refused(self) -> None:
        with pytest.raises(A2AClientError, match="not one this deployment may call"):
            await fetch_card("https://internal.example.com", transport=_wire(httpx2.Response(200)))

    @pytest.mark.parametrize(
        ("response", "says"),
        [
            (httpx2.Response(404), "HTTP 404"),
            (
                httpx2.Response(200, json={"hello": "world"}),
                "does not answer with an A2A agent card",
            ),
            (httpx2.Response(200, content=b"x" * (a2a_client.MAX_CARD_BYTES + 1)), "larger"),
            # A card naming an endpoint nothing could send work to, or one too
            # long to store, is not a card this deployment can register.
            (
                httpx2.Response(200, json={**CARD, "url": "ftp://agents.example.com/a2a"}),
                "does not answer with an A2A agent card",
            ),
            (
                httpx2.Response(200, json={**CARD, "url": "not a url"}),
                "does not answer with an A2A agent card",
            ),
            (
                httpx2.Response(
                    200, json={**CARD, "url": "https://agents.example.com/" + "a" * 1000}
                ),
                "does not answer with an A2A agent card",
            ),
        ],
    )
    async def test_anything_but_a_card_is_refused(
        self, response: httpx2.Response, says: str
    ) -> None:
        with pytest.raises(A2AClientError, match=says):
            await fetch_card("https://agents.example.com", transport=_wire(response))

    async def test_an_unreachable_agent_is_said_so(self) -> None:
        def down(_request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("refused")

        with pytest.raises(A2AClientError, match="could not be fetched"):
            await fetch_card("https://agents.example.com", transport=httpx2.MockTransport(down))


class TestSendingAMessage:
    @pytest.mark.security
    async def test_a_key_is_never_sent_over_plain_http(self) -> None:
        seen: list[httpx2.Request] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.append(request)
            return httpx2.Response(200, json={})

        with pytest.raises(A2AClientError, match="not HTTPS"):
            await send_message(
                "http://agents.example.com/a2a",
                "Hi",
                context_id=None,
                bearer="sk-org-key",
                transport=httpx2.MockTransport(handler),
            )
        assert seen == []

    async def test_a_completed_task_is_its_answer_and_its_context(self) -> None:
        seen: list[httpx2.Request] = []
        reply = await send_message(
            CARD["url"],
            "Review clause 7",
            context_id="ctx-0",
            bearer="secret-token",
            transport=_wire(_rpc(_task("completed", answer="Clause 7 is fine.")), seen),
        )
        assert (reply.text, reply.context_id, reply.state) == (
            "Clause 7 is fine.",
            "ctx-1",
            "completed",
        )
        (request,) = seen
        body = json.loads(request.content)
        assert body["method"] == "message/send"
        assert body["params"]["message"]["parts"] == [{"kind": "text", "text": "Review clause 7"}]
        assert body["params"]["message"]["contextId"] == "ctx-0"
        # Polled rather than held open past the read timeout on a long task.
        assert body["params"]["configuration"]["blocking"] is False
        assert request.headers["authorization"] == "Bearer secret-token"

    async def test_a_plain_message_is_an_answer_too(self) -> None:
        message = {
            "kind": "message",
            "role": "agent",
            "messageId": "m",
            "contextId": "ctx-9",
            "parts": [{"kind": "text", "text": "Done."}],
        }
        reply = await send_message(
            CARD["url"], "Hi", context_id=None, bearer=None, transport=_wire(_rpc(message))
        )
        assert (reply.text, reply.context_id) == ("Done.", "ctx-9")

    @pytest.mark.parametrize(
        ("state", "says"),
        [
            ("input-required", "waiting for more input"),
            ("auth-required", "needs its own sign-in"),
            ("failed", "task failed"),
        ],
    )
    async def test_a_task_that_did_not_finish_says_what_it_is_waiting_for(
        self, state: str, says: str
    ) -> None:
        reply = await send_message(
            CARD["url"],
            "Hi",
            context_id=None,
            bearer=None,
            transport=_wire(_rpc(_task(state, note="details"))),
        )
        assert says in reply.text
        assert "details" in reply.text

    async def test_a_task_still_under_way_is_read_again_until_it_ends(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An agent may answer `message/send` before it is done; the answer lands
        on the task, which is the only thing to read it from."""
        monkeypatch.setattr(a2a_client, "POLL_SECONDS", 0)
        answers = iter(
            [
                _rpc(_task("submitted")),
                _rpc(_task("working")),
                _rpc(_task("completed", answer="Done.")),
            ]
        )
        seen: list[httpx2.Request] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.append(request)
            return next(answers)

        reply = await send_message(
            CARD["url"], "Hi", context_id=None, bearer=None, transport=httpx2.MockTransport(handler)
        )

        assert (reply.state, reply.text) == ("completed", "Done.")
        methods = [json.loads(request.content)["method"] for request in seen]
        assert methods == ["message/send", "tasks/get", "tasks/get"]
        assert json.loads(seen[1].content)["params"] == {"id": reply.task_id}

    async def test_a_task_that_never_ends_is_answered_with_its_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(a2a_client, "POLL_SECONDS", 0)
        monkeypatch.setattr(a2a_client, "POLL_FOR_SECONDS", 0)
        reply = await send_message(
            CARD["url"], "Hi", context_id=None, bearer=None, transport=_wire(_rpc(_task("working")))
        )
        assert reply.state == "working" and "still working" in reply.text

    async def test_a_task_waiting_on_input_is_continued_by_the_next_message(self) -> None:
        seen: list[httpx2.Request] = []
        await send_message(
            CARD["url"],
            "Here is the file",
            context_id="ctx-1",
            task_id="task-7",
            bearer=None,
            transport=_wire(_rpc(_task("completed", answer="Thanks.")), seen),
        )
        message = json.loads(seen[0].content)["params"]["message"]
        assert (message["taskId"], message["contextId"]) == ("task-7", "ctx-1")

    async def test_an_endless_reply_is_refused_while_it_arrives(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Counted as it comes: a remote server answering forever must not fill
        this worker's memory before anything is cut."""
        monkeypatch.setattr(a2a_client, "MAX_RESPONSE_BYTES", 64)
        endless = httpx2.Response(200, content=b"x" * 1000)
        with pytest.raises(A2AClientError, match="more than"):
            await send_message(
                CARD["url"], "Hi", context_id=None, bearer=None, transport=_wire(endless)
            )

    async def test_a_long_answer_is_cut_and_says_so(self) -> None:
        long = "x" * (a2a_client.MAX_ANSWER_CHARS + 10)
        reply = await send_message(
            CARD["url"],
            "Hi",
            context_id=None,
            bearer=None,
            transport=_wire(_rpc(_task("completed", answer=long))),
        )
        assert reply.text.endswith("[The answer went on for 10 more characters.]")

    @pytest.mark.parametrize(
        ("response", "says"),
        [
            (httpx2.Response(401), "refused the credential"),
            (httpx2.Response(500), "HTTP 500"),
            (httpx2.Response(200, content=b"<html>"), "did not answer with JSON"),
            (httpx2.Response(200, json=[1]), "JSON-RPC"),
            (
                httpx2.Response(200, json={"jsonrpc": "2.0", "error": {"message": "busy"}}),
                "refused the task: busy",
            ),
            (httpx2.Response(200, json={"jsonrpc": "2.0", "result": None}), "no result"),
            (_rpc({"kind": "task", "id": "t"}), "neither a task nor a message"),
        ],
    )
    async def test_anything_but_an_answer_is_an_error(
        self, response: httpx2.Response, says: str
    ) -> None:
        with pytest.raises(A2AClientError, match=says):
            await send_message(
                CARD["url"], "Hi", context_id=None, bearer=None, transport=_wire(response)
            )

    @pytest.mark.security
    async def test_an_endpoint_inside_the_network_is_never_called(self) -> None:
        seen: list[httpx2.Request] = []
        with pytest.raises(A2AClientError, match="not one this deployment may call"):
            await send_message(
                "https://internal.example.com/a2a",
                "Hi",
                context_id=None,
                bearer="secret-token",
                transport=_wire(_rpc(_task("completed")), seen),
            )
        assert seen == []

    async def test_an_unreachable_endpoint_is_said_so(self) -> None:
        def down(_request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("refused")

        with pytest.raises(A2AClientError, match="could not be reached"):
            await send_message(
                CARD["url"],
                "Hi",
                context_id=None,
                bearer=None,
                transport=httpx2.MockTransport(down),
            )


class TestDelegatingToARemoteAgent:
    def test_the_latest_prompt_is_what_is_sent(self) -> None:
        messages = [
            ModelRequest(parts=[UserPromptPart("first")]),
            ModelResponse(parts=[TextPart("ok")]),
            ModelRequest(parts=[UserPromptPart(["second", "part"])]),
        ]
        assert latest_prompt(messages) == "second\npart"
        assert latest_prompt([ModelResponse(parts=[TextPart("x")])]) == ""

    def test_a_tool_return_after_the_prompt_does_not_hide_it(self) -> None:
        messages = [
            ModelRequest(parts=[UserPromptPart("ask"), SystemPromptPart("context")]),
            ModelRequest(parts=[ToolReturnPart(tool_name="t", content="x", tool_call_id="1")]),
        ]
        assert latest_prompt(messages) == "ask"

    @pytest.mark.security
    async def test_each_call_is_budgeted_booked_and_continues_the_conversation(self) -> None:
        replies = [
            a2a_client.A2AReply(text="First answer", context_id="ctx-1", state="completed"),
            a2a_client.A2AReply(text="", context_id=None, state="completed"),
        ]
        sent = AsyncMock(side_effect=replies)
        budget = AsyncMock()
        with (
            patch.object(delegate_module, "send_message", sent),
            patch.object(delegate_module, "assert_ambient_budget", budget),
            patch.object(delegate_module, "record_ambient_usage") as booked,
        ):
            agent = a2a_delegate(handle="reviewer", endpoint=CARD["url"], bearer="tok")()
            first = await agent.run("Review the contract")
            second = await agent.run("And clause 9?")

        assert first.output == "First answer"
        assert second.output == "(The remote agent sent no text.)"
        assert sent.await_args_list[0].kwargs == {
            "context_id": None,
            "task_id": None,
            "bearer": "tok",
        }
        assert sent.await_args_list[1].kwargs["context_id"] == "ctx-1"
        assert budget.await_count == 2
        assert booked.call_args.args[0] == "a2a:reviewer"
        assert booked.call_args.kwargs["provider"] == "a2a"

    async def test_a_task_waiting_on_input_is_continued_and_a_finished_one_is_not(
        self,
    ) -> None:
        replies = [
            a2a_client.A2AReply(
                text="Which file?", context_id="c", state="input-required", task_id="t-1"
            ),
            a2a_client.A2AReply(text="Done.", context_id="c", state="completed", task_id="t-1"),
            a2a_client.A2AReply(text="Again.", context_id="c", state="completed", task_id="t-2"),
        ]
        sent = AsyncMock(side_effect=replies)
        with (
            patch.object(delegate_module, "send_message", sent),
            patch.object(delegate_module, "assert_ambient_budget", AsyncMock()),
            patch.object(delegate_module, "record_ambient_usage"),
        ):
            agent = a2a_delegate(handle="reviewer", endpoint=CARD["url"], bearer=None)()
            for prompt in ("Review it", "contract.pdf", "Now clause 9"):
                await agent.run(prompt)

        assert [call.kwargs["task_id"] for call in sent.await_args_list] == [None, "t-1", None]

    async def test_a_remote_agent_that_fails_is_an_answer_and_still_booked(self) -> None:
        with (
            patch.object(
                delegate_module, "send_message", AsyncMock(side_effect=A2AClientError("down"))
            ),
            patch.object(delegate_module, "assert_ambient_budget", AsyncMock()),
            patch.object(delegate_module, "record_ambient_usage") as booked,
        ):
            result = await a2a_delegate(handle="reviewer", endpoint=CARD["url"], bearer=None)().run(
                "Hi"
            )

        assert result.output == "The remote agent reviewer did not answer: down"
        # A call that dropped may still have been worked on: booked unpriced, so
        # the run's cost says it is a floor rather than reading as complete.
        booked.assert_called_once()
        assert booked.call_args.args[0] == "a2a:reviewer"

    async def test_a_streamed_delegation_gets_the_same_answer(self) -> None:
        reply = a2a_client.A2AReply(text="Streamed", context_id=None, state="completed")
        with (
            patch.object(delegate_module, "send_message", AsyncMock(return_value=reply)),
            patch.object(delegate_module, "assert_ambient_budget", AsyncMock()),
            patch.object(delegate_module, "record_ambient_usage"),
        ):
            agent = a2a_delegate(handle="reviewer", endpoint=CARD["url"], bearer=None)()
            async with agent.run_stream("Hi") as run:
                assert await run.get_output() == "Streamed"
