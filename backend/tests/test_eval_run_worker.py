"""Whose failure a failed eval attempt was - the agent's fails the case, the provider's leaves it open.

Also what an attempt's trajectory lists.
"""

from unittest.mock import MagicMock

import pytest
from pydantic_ai.exceptions import (
    FallbackExceptionGroup,
    ModelAPIError,
    ModelHTTPError,
    UsageLimitExceeded,
)

from app.db.models.eval_run import AttemptFault
from app.services.eval_run_worker import run_failure, trajectory
from app.services.transcript import RecordedToolCall


@pytest.mark.parametrize(
    "exc",
    [
        ModelHTTPError(503, "gpt-test"),
        ModelHTTPError(429, "gpt-test"),
        ModelHTTPError(408, "gpt-test"),
        ModelAPIError("gpt-test", "Connection timed out"),
        FallbackExceptionGroup(
            "every model failed", [ModelHTTPError(502, "a"), ModelAPIError("b", "timed out")]
        ),
    ],
)
def test_a_provider_that_failed_after_its_retries_is_the_infrastructure(exc) -> None:
    assert run_failure(exc)[1] is AttemptFault.INFRASTRUCTURE


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("the lookup tool exploded"),
        UsageLimitExceeded("The next request would exceed the request_limit of 5"),
        ModelHTTPError(400, "gpt-test"),
        FallbackExceptionGroup(
            "every model failed", [ModelHTTPError(503, "a"), RuntimeError("a tool raised")]
        ),
    ],
)
def test_anything_else_is_the_agent(exc) -> None:
    assert run_failure(exc)[1] is AttemptFault.AGENT


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_credentials_are_said_plainly(status: int) -> None:
    error, fault = run_failure(ModelHTTPError(status, "gpt-test"))
    assert fault is AttemptFault.AGENT
    assert error.startswith(f"The model provider rejected the credentials (HTTP {status})")


def test_a_scripts_calls_follow_it_in_the_trajectory_each_with_its_outcome() -> None:
    script = RecordedToolCall(
        tool_call_id="c9",
        tool_name="run_code",
        args={"code": "..."},
        result="done",
        script_calls={
            "calls": [
                {
                    "tool_call_id": f"c9__{n}",
                    "tool_name": tool,
                    "args": {},
                    "result": "r",
                    "outcome": "success",
                }
                for n, tool in ((1, "list_context"), (2, "web_fetch"))
            ],
            "omitted": 0,
        },
    )
    held = MagicMock(tool_call_id="c9__2", outcome="blocked", reason="external")

    rows = trajectory([script, RecordedToolCall("c2", "answer", {})], [held])

    assert [(row["tool"], row["outcome"], row.get("parent")) for row in rows] == [
        ("run_code", "executed", None),
        ("list_context", "executed", "c9"),
        ("web_fetch", "blocked", "c9"),
        ("answer", "executed", None),
    ]
    assert rows[0]["script"] is True
    assert rows[2]["reason"] == "external"
    assert "script" not in rows[3]
