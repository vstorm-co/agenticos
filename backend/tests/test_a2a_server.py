"""Serving an agent over A2A: its card, and the tasks other systems send it (#2092)."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent_run import RunStatus, RunSurface
from app.schemas.agent import ParkedCall
from app.services import a2a_server as module
from app.services.a2a_server import A2AServerService

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()
CTX = AuthContext(user_id=uuid.uuid4(), organization_id=ORG, role="member")


def _agent(**overrides: Any) -> MagicMock:
    agent = MagicMock(
        id=uuid.uuid4(),
        organization_id=ORG,
        slug="contracts",
        description="Reviews contracts.",
        tags=["legal"],
        current_version_id=uuid.uuid4(),
    )
    agent.name = "Contracts"
    for field, value in overrides.items():
        setattr(agent, field, value)
    return agent


def _run(status: str = RunStatus.COMPLETED.value, **overrides: Any) -> MagicMock:
    run = MagicMock(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        status=status,
        error=None,
        user_id=CTX.user_id,
    )
    for field, value in overrides.items():
        setattr(run, field, value)
    return run


def _send(text: str = "Review clause 7", **message: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "messageId": "m1",
                "parts": [{"kind": "text", "text": text}],
                **message,
            }
        },
    }


class _Served:
    """The repository and runner around one served agent."""

    def __init__(self, agent: MagicMock | None) -> None:
        self.agent = agent
        self.runner = MagicMock(
            execute=AsyncMock(),
            parked_calls=AsyncMock(return_value=[]),
            get_run=AsyncMock(),
        )
        self.conversations = MagicMock(
            for_api_run=AsyncMock(return_value=(uuid.uuid4(), None)),
            delete_conversation=AsyncMock(),
        )
        self.registry = MagicMock(get=AsyncMock(return_value=agent))

    def __enter__(self) -> _Served:
        self._patches = [
            patch.object(
                module.agent_repo, "get_served_over_a2a", AsyncMock(return_value=self.agent)
            ),
            patch.object(
                module.agent_repo, "get_version", AsyncMock(return_value=MagicMock(version=4))
            ),
            patch.object(module, "AgentRunnerService", return_value=self.runner),
            patch.object(module, "ConversationService", return_value=self.conversations),
            patch.object(module, "AgentRegistryService", return_value=self.registry),
        ]
        for started in self._patches:
            started.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        for started in self._patches:
            started.stop()


async def _ask(served: _Served, body: Any) -> dict[str, Any]:
    with served:
        return await A2AServerService(MagicMock()).handle(CTX, uuid.uuid4(), body)


class TestTheCard:
    async def test_a_served_agent_describes_itself_and_how_to_authenticate(self) -> None:
        agent = _agent()
        with _Served(agent):
            card = await A2AServerService(MagicMock()).card(agent.id)

        wire = card.model_dump(by_alias=True, exclude_none=True)
        assert wire["name"] == "Contracts"
        assert wire["version"] == "4"
        assert wire["url"].endswith(f"/a2a/{agent.id}")
        assert wire["skills"][0]["id"] == "contracts"
        assert wire["securitySchemes"]["bearer"]["scheme"] == "bearer"
        assert wire["securitySchemes"]["oauth"]["oauth2MetadataUrl"].endswith(
            "/.well-known/oauth-authorization-server"
        )
        assert wire["capabilities"] == {"streaming": False, "pushNotifications": False}

    async def test_an_agent_with_no_version_row_reads_as_version_one(self) -> None:
        agent = _agent(current_version_id=None)
        with _Served(agent):
            card = await A2AServerService(MagicMock()).card(agent.id)
        assert card.version == "1"

    @pytest.mark.security
    async def test_an_agent_that_is_not_served_has_no_card(self) -> None:
        with _Served(None), pytest.raises(NotFoundError):
            await A2AServerService(MagicMock()).card(uuid.uuid4())


@pytest.mark.security
class TestWhoMaySendATask:
    async def test_an_agent_that_is_not_served_is_not_found(self) -> None:
        with pytest.raises(NotFoundError):
            await _ask(_Served(None), _send())

    async def test_another_organizations_agent_is_not_found(self) -> None:
        """A key acts in its own organization; another tenant's served agent reads as absent."""
        with pytest.raises(NotFoundError):
            await _ask(_Served(_agent(organization_id=uuid.uuid4())), _send())

    async def test_a_key_not_allowed_to_run_it_is_refused_by_http_not_json_rpc(self) -> None:
        """A2A leaves who may call to the transport: a 403 a client reads as a
        refused credential, not `-32600`, which says the request was malformed."""
        served = _Served(_agent())
        served.runner.execute.side_effect = AuthorizationError(message="No run permission")
        with pytest.raises(AuthorizationError):
            await _ask(served, _send())


class TestSendingATask:
    async def test_a_message_runs_the_agent_and_answers_with_a_completed_task(self) -> None:
        served = _Served(_agent())
        run = _run()
        served.runner.execute.return_value = ("Clause 7 is fine.", run)

        answer = await _ask(served, _send())

        task = answer["result"]
        assert answer["id"] == "req-1"
        assert task["kind"] == "task"
        assert task["id"] == str(run.id)
        assert task["contextId"] == str(run.conversation_id)
        assert task["status"]["state"] == "completed"
        assert task["artifacts"][0]["parts"] == [{"kind": "text", "text": "Clause 7 is fine."}]
        call = served.runner.execute.await_args
        assert call.args[2] == "Review clause 7"
        assert call.kwargs["surface"] is RunSurface.A2A

    async def test_the_context_continues_the_conversation(self) -> None:
        served = _Served(_agent())
        served.runner.execute.return_value = ("ok", _run())
        context = uuid.uuid4()

        await _ask(served, _send(contextId=str(context)))

        assert served.conversations.for_api_run.await_args.args[1] == context

    async def test_a_run_waiting_for_a_person_is_input_required(self) -> None:
        served = _Served(_agent())
        served.runner.execute.return_value = ("", _run(RunStatus.AWAITING_APPROVAL.value))
        served.runner.parked_calls.return_value = [
            ParkedCall(id=uuid.uuid4(), tool_name="send_email", tool_args={})
        ]

        task = (await _ask(served, _send()))["result"]

        assert task["status"]["state"] == "input-required"
        assert "send_email" in task["status"]["message"]["parts"][0]["text"]
        assert task["artifacts"] == []

    async def test_a_run_that_failed_is_a_failed_task(self) -> None:
        served = _Served(_agent())
        run_id = uuid.uuid4()
        served.runner.execute.side_effect = BadRequestError(
            message="The model provider refused", details={"run_id": str(run_id)}
        )

        task = (await _ask(served, _send()))["result"]

        assert task["id"] == str(run_id)
        assert task["status"]["state"] == "failed"
        assert task["status"]["message"]["parts"][0]["text"] == "The model provider refused"

    async def test_a_refusal_before_any_run_is_an_error_and_leaves_no_thread(self) -> None:
        served = _Served(_agent())
        served.runner.execute.side_effect = BadRequestError(message="Not runnable")
        answer = await _ask(served, _send())
        assert answer["error"]["message"] == "Not runnable"
        # The thread it opened holds the question alone.
        opened = served.conversations.for_api_run.return_value[0]
        assert served.conversations.delete_conversation.await_args.args == (opened,)

    async def test_a_run_refused_for_access_leaves_no_thread_either(self) -> None:
        served = _Served(_agent())
        served.runner.execute.side_effect = AuthorizationError(message="Not yours")
        with pytest.raises(AuthorizationError):
            await _ask(served, _send())
        served.conversations.delete_conversation.assert_awaited_once()

    async def test_a_refusal_in_a_thread_already_going_is_raised_and_keeps_it(self) -> None:
        served = _Served(_agent())
        served.runner.execute.side_effect = AuthorizationError(message="Not yours")
        with pytest.raises(AuthorizationError):
            await _ask(served, _send(contextId=str(uuid.uuid4())))
        served.conversations.delete_conversation.assert_not_awaited()

    async def test_a_context_that_is_not_an_api_conversation_is_a_bad_parameter(self) -> None:
        """Refused by `for_api_run` as begun in the console: still a JSON-RPC answer,
        not an HTTP 400 a client reads as the agent being unreachable."""
        served = _Served(_agent())
        served.conversations.for_api_run.side_effect = BadRequestError(
            message="That conversation was not started through the API"
        )
        answer = await _ask(served, _send(contextId=str(uuid.uuid4())))
        assert answer["error"] == {
            "code": -32602,
            "message": "That conversation was not started through the API",
        }

    async def test_a_context_naming_no_conversation_is_a_bad_parameter(self) -> None:
        served = _Served(_agent())
        served.conversations.for_api_run.side_effect = NotFoundError(message="No conversation")
        answer = await _ask(served, _send(contextId=str(uuid.uuid4())))
        assert answer["error"]["code"] == -32602
        served.runner.execute.assert_not_awaited()

    @pytest.mark.parametrize("kind", ["data", "file"])
    async def test_a_part_that_is_not_text_is_refused_as_content_it_cannot_read(
        self, kind: str
    ) -> None:
        """Run on its text alone, the question would be answered without the
        file or the data it came with."""
        served = _Served(_agent())
        body = _send()
        body["params"]["message"]["parts"].append({"kind": kind, "data": {"x": 1}})

        answer = await _ask(served, body)

        assert answer["error"]["code"] == -32005
        assert kind in answer["error"]["message"]
        served.runner.execute.assert_not_awaited()

    async def test_a_refusal_in_a_thread_already_going_keeps_the_thread(self) -> None:
        served = _Served(_agent())
        served.runner.execute.side_effect = BadRequestError(message="Not runnable")
        await _ask(served, _send(contextId=str(uuid.uuid4())))
        served.conversations.delete_conversation.assert_not_awaited()

    @pytest.mark.parametrize(
        ("body", "code"),
        [
            ({"hello": "world"}, -32600),
            ({"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {}}, -32602),
            (_send(text="  "), -32602),
            (_send(contextId="not-an-id"), -32602),
        ],
    )
    async def test_a_malformed_request_is_a_json_rpc_error(
        self, body: dict[str, Any], code: int
    ) -> None:
        answer = await _ask(_Served(_agent()), body)
        assert answer["error"]["code"] == code


class TestWhoMayRunIt:
    @pytest.mark.security
    async def test_an_agent_the_caller_may_not_run_opens_no_conversation(self) -> None:
        """Refused only by the run, the request still committed, and each refusal
        left an empty thread behind."""
        served = _Served(_agent())
        served.registry.get.side_effect = NotFoundError(message="Agent not found")

        with pytest.raises(NotFoundError):
            await _ask(served, _send())

        served.conversations.for_api_run.assert_not_awaited()
        served.runner.execute.assert_not_awaited()


class TestContinuingATask:
    async def test_a_message_naming_a_task_is_refused_rather_than_run_beside_it(self) -> None:
        """The waiting run stays the one waiting; no second run starts."""
        served = _Served(_agent())
        answer = await _ask(served, _send(taskId=str(uuid.uuid4())))

        assert answer["error"]["code"] == -32004
        assert "decided in the console" in answer["error"]["message"]
        served.runner.execute.assert_not_awaited()


class TestReadingATask:
    def _get(self, task_id: str | None) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": 2, "method": "tasks/get", "params": {"id": task_id}}

    async def test_a_task_reads_where_its_run_stands_and_what_it_last_said(self) -> None:
        agent = _agent()
        served = _Served(agent)
        run = _run(agent_id=agent.id)
        served.runner.get_run.return_value = run
        with patch.object(
            module.conversation_repo, "last_answer_of_run", AsyncMock(return_value="Hello.")
        ):
            task = (await _ask(served, self._get(str(run.id))))["result"]

        assert task["status"]["state"] == "completed"
        assert task["artifacts"][0]["parts"][0]["text"] == "Hello."

    @pytest.mark.parametrize(
        ("status", "state"),
        [
            (RunStatus.RUNNING.value, "working"),
            (RunStatus.CANCELLED.value, "canceled"),
            (RunStatus.BUDGET_EXCEEDED.value, "failed"),
        ],
    )
    async def test_every_run_status_has_a_task_state(self, status: str, state: str) -> None:
        agent = _agent()
        served = _Served(agent)
        served.runner.get_run.return_value = _run(status, agent_id=agent.id)
        with patch.object(
            module.conversation_repo, "last_answer_of_run", AsyncMock(return_value=None)
        ):
            task = (await _ask(served, self._get(str(uuid.uuid4()))))["result"]
        assert task["status"]["state"] == state

    @pytest.mark.security
    async def test_another_agents_or_an_unknown_run_is_not_found(self) -> None:
        served = _Served(_agent())
        served.runner.get_run.return_value = _run(agent_id=uuid.uuid4())
        assert (await _ask(served, self._get(str(uuid.uuid4()))))["error"]["code"] == -32001

        served.runner.get_run.side_effect = NotFoundError(message="Run not found")
        assert (await _ask(served, self._get(str(uuid.uuid4()))))["error"]["code"] == -32001

    @pytest.mark.security
    async def test_somebody_else_s_task_is_not_found_unless_they_may_read_every_run(
        self,
    ) -> None:
        """A task id is not a bearer token: knowing one is not reading its answer."""
        agent = _agent()
        served = _Served(agent)
        served.runner.get_run.return_value = _run(agent_id=agent.id, user_id=uuid.uuid4())
        with patch.object(
            module.conversation_repo, "last_answer_of_run", AsyncMock(return_value=None)
        ):
            assert (await _ask(served, self._get(str(uuid.uuid4()))))["error"]["code"] == -32001

            operator = AuthContext(user_id=uuid.uuid4(), organization_id=ORG, role="operator")
            with served:
                answer = await A2AServerService(MagicMock()).handle(
                    operator, uuid.uuid4(), self._get(str(uuid.uuid4()))
                )
        assert answer["result"]["status"]["state"] == "completed"

    async def test_a_task_needs_an_id(self) -> None:
        assert (await _ask(_Served(_agent()), self._get(None)))["error"]["code"] == -32602

    async def test_an_id_this_server_never_issued_is_an_unknown_task(self) -> None:
        assert (await _ask(_Served(_agent()), self._get("t-1")))["error"]["code"] == -32001


class TestWhatIsNotOffered:
    @pytest.mark.parametrize(
        ("method", "code"),
        [("tasks/cancel", -32002), ("message/stream", -32004), ("agent/dance", -32601)],
    )
    async def test_it_is_refused_by_name(self, method: str, code: int) -> None:
        answer = await _ask(_Served(_agent()), {"jsonrpc": "2.0", "id": 3, "method": method})
        assert answer["error"]["code"] == code
