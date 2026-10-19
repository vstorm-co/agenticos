"""The child's side of the pipe, in this process (#2219).

`tests/test_worker_child_pool.py` spawns real children and kills them; what a
child answers for each way a job can end is pinned here, where it can be read
line by line.
"""

import io
from unittest.mock import patch

import pytest

from app.worker.child import READY, ChildReply, ChildRequest, load_handlers, run_one, serve
from tests import worker_handlers

pytestmark = pytest.mark.anyio

HANDLERS = worker_handlers.handlers()


def test_the_handlers_are_loaded_from_a_module_and_attribute() -> None:
    assert load_handlers("tests.worker_handlers:handlers").keys() == HANDLERS.keys()


@pytest.mark.parametrize(
    ("request_", "reply"),
    [
        (
            ChildRequest(kind="test-answer", payload={"text": "forty-two"}),
            ChildReply(ok=True, result={"text": "forty-two"}),
        ),
        (ChildRequest(kind="test-ok", payload={}), ChildReply(ok=True)),
    ],
)
async def test_a_job_that_finishes_says_so_with_what_it_answered(
    request_: ChildRequest, reply: ChildReply
) -> None:
    assert await run_one(HANDLERS, request_) == reply


async def test_a_kind_nobody_handles_and_a_payload_that_does_not_validate_are_for_good() -> None:
    unknown = await run_one(HANDLERS, ChildRequest(kind="test-nope", payload={}))
    malformed = await run_one(HANDLERS, ChildRequest(kind="test-ok", payload={"seconds": "soon"}))

    assert (unknown.ok, unknown.permanent) == (False, True)
    assert (malformed.ok, malformed.permanent) == (False, True)
    assert malformed.error is not None
    assert malformed.error.startswith("ValidationError")


async def test_a_job_that_raises_is_retried_with_why() -> None:
    reply = await run_one(HANDLERS, ChildRequest(kind="test-fail", payload={"text": "no"}))

    assert (reply.ok, reply.permanent) == (False, False)
    assert reply.error is not None
    assert reply.error.startswith("RuntimeError: no")


async def test_the_child_says_ready_then_answers_a_line_per_request() -> None:
    requests = io.StringIO(
        ChildRequest(kind="test-ok", payload={}).model_dump_json()
        + "\n"
        + ChildRequest(kind="test-nope", payload={}).model_dump_json()
        + "\n"
    )
    replies = io.StringIO()

    with patch("app.db.session.claim_pooled_engines") as claim:
        await serve(HANDLERS, requests, replies)

    claim.assert_called_once()
    ready, first, second = replies.getvalue().splitlines()
    assert ready == READY
    assert ChildReply.model_validate_json(first).ok is True
    assert ChildReply.model_validate_json(second).permanent is True
