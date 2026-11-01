"""The Architect's Improve and eval tools: the wizard's own routes, read back compactly."""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from app.services.platform_mcp import platform_tool_catalog
from app.services.platform_mcp._tools import improvement_link, platform_tools

pytestmark = pytest.mark.anyio

AGENT = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
SESSION = uuid.UUID("00000000-0000-4000-8000-0000000000d1")
RUN = uuid.UUID("00000000-0000-4000-8000-0000000000c1")
DATASET = uuid.UUID("00000000-0000-4000-8000-0000000000e1")
BEST = "00000000-0000-4000-8000-0000000000f2"
TOPIC = "00000000-0000-4000-8000-0000000000b9"
OTHER_TOPIC = "00000000-0000-4000-8000-0000000000b8"

SESSION_READ: dict[str, Any] = {
    "id": str(SESSION),
    "agent_id": str(AGENT),
    "status": "ready",
    "stage": "judging",
    "iteration": 2,
    "max_iterations": 3,
    "stop_reason": None,
    "spent_usd": "0.03",
    "budget_usd": "0.05",
    "created_at": "2026-10-27T08:00:00Z",
    "finished_at": None,
    "best_iteration_id": BEST,
    "can_discard": True,
    "can_restart": False,
    "published_version": None,
    "deferred_topic_ids": [OTHER_TOPIC],
    "error": "only for runs:view",
    "iterations": [
        {
            "id": "00000000-0000-4000-8000-0000000000f1",
            "number": 1,
            "verdict": "regression",
            "verdict_detail": {
                "fixed": 2,
                "broken": 1,
                "baseline_pass_rate": 0.5,
                "candidate_pass_rate": 0.6,
            },
            "cost_usd": "0.01",
            "candidate_spec_hash": "a" * 64,
        },
        {
            "id": BEST,
            "number": 2,
            "verdict": "better",
            "verdict_detail": {
                "fixed": 3,
                "broken": 0,
                "held_out": 6,
                "baseline_pass_rate": 0.5,
                "candidate_pass_rate": 0.8,
            },
            "cost_usd": "0.02",
            "candidate_spec_hash": "b" * 64,
        },
    ],
}


def _permissions(*held: str) -> dict[str, Any]:
    return {"permissions": [{"permission": name, "scope": "all"} for name in held]}


def _miss(
    run_id: str, branch: str, topic_id: str | None = None, *, added: bool = False
) -> dict[str, Any]:
    """One conversation Understand sorted, as the evidence route lists it."""
    return {
        "run_id": run_id,
        "branch": branch,
        "topic_id": topic_id,
        "knowledge_added": {"document": "Shipping"} if added else None,
    }


UNPUBLISHED: dict[tuple[str, str], Any] = {
    ("GET", f"/agents/{AGENT}"): {"id": AGENT, "current_version_id": None},
    ("GET", f"/agents/{AGENT}/versions"): {"items": [], "total": 0},
}
"""The agent and its versions, for a test about something else: never published."""


def _responder(responses: dict[tuple[str, str], Any]) -> AsyncMock:
    async def respond(method: str, path: str, **_: Any) -> Any:
        return {**UNPUBLISHED, **responses}[(method, path)]

    return AsyncMock(side_effect=respond)


@pytest.fixture
def api() -> MagicMock:
    return MagicMock()


@pytest.fixture
def server(api: MagicMock) -> FastMCP:
    server = FastMCP(name="test")
    for tool in platform_tools(api):
        server.tool(tool.function)
    return server


async def _call(server: FastMCP, tool: str, **arguments: Any) -> Any:
    result = await server.call_tool(tool, {k: str(v) for k, v in arguments.items()})
    return result.structured_content


class TestReadingSessions:
    async def test_a_listing_names_each_session_and_its_wizard_page(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder({("GET", f"/agents/{AGENT}/improvements"): [SESSION_READ]})

        listing = await _call(server, "list_improvements", agent_id=AGENT)

        [item] = listing["items"]
        assert item["status"] == "ready"
        assert item["link"] == f"/agents/{AGENT}/improve/{SESSION}"
        assert "iterations" not in item
        assert "error" not in item

    async def test_a_session_reads_as_attempts_with_their_verdicts_and_the_best_marked(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                ("GET", f"/improvements/{SESSION}"): SESSION_READ,
                ("GET", "/me/permissions"): _permissions("agents:view"),
            }
        )

        session = await _call(server, "get_improvement", session_id=SESSION)

        assert [a["attempt"] for a in session["attempts"]] == [1, 2]
        best = session["attempts"][1]
        assert best == {
            "attempt": 2,
            "verdict": "better",
            "fixed": 3,
            "broken": 0,
            "change": 3,
            "held_out": 6,
            "details": {"pass_rate_before": 0.5, "pass_rate_after": 0.8},
            "cost_usd": "0.02",
            "chosen": True,
            "best": True,
        }
        assert session["attempts"][0]["change"] == 1
        assert not session["attempts"][0]["chosen"]
        assert not session["attempts"][0]["best"]
        assert session["link"] == improvement_link(AGENT, SESSION)

    async def test_knowledge_topics_are_read_only_with_runs_view(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        """The topics quote what people asked: a reader without `runs:view` gets none, and
        the evidence route is never called on their behalf."""
        api.request = _responder(
            {
                ("GET", f"/improvements/{SESSION}"): SESSION_READ,
                ("GET", "/me/permissions"): _permissions("agents:view"),
            }
        )

        session = await _call(server, "get_improvement", session_id=SESSION)

        assert "missing_knowledge" not in session
        paths = [call.args[1] for call in api.request.await_args_list]
        assert not any("evidence" in path or "knowledge-gaps" in path for path in paths)

    async def test_the_session_s_own_missing_knowledge_topics_are_listed(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        topic = {
            "id": TOPIC,
            "label": "Do you ship to Germany?",
            "knowledge_base_name": "Help center",
            "has_draft": True,
            "draft_stale": True,
        }
        api.request = _responder(
            {
                ("GET", f"/improvements/{SESSION}"): SESSION_READ,
                ("GET", "/me/permissions"): _permissions("agents:view", "runs:view"),
                ("GET", f"/agents/{AGENT}/improvements/{SESSION}/evidence"): {
                    "items": [
                        _miss("r1", "missing_knowledge", TOPIC),
                        _miss("r2", "missing_knowledge", OTHER_TOPIC),
                        _miss("r3", "agent"),
                    ]
                },
                ("GET", f"/knowledge-gaps/agents/{AGENT}"): {
                    "items": [
                        topic,
                        {**topic, "id": OTHER_TOPIC, "label": "Gift cards?"},
                        {**topic, "id": str(uuid.uuid4()), "label": "Another session's"},
                    ]
                },
            }
        )

        session = await _call(server, "get_improvement", session_id=SESSION)

        assert session["missing_knowledge"] == [
            {
                "topic_id": TOPIC,
                "label": "Do you ship to Germany?",
                "knowledge_base": "Help center",
                "state": "draft_stale",
            },
            {
                "topic_id": OTHER_TOPIC,
                "label": "Gift cards?",
                "knowledge_base": "Help center",
                "state": "draft_stale",
            },
        ]

    async def test_an_attempt_kept_by_hand_is_chosen_without_being_the_best(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        """Bartek kept attempt 1, which broke a question: it is the chosen attempt, not the best."""
        first = SESSION_READ["iterations"][0]["id"]
        kept = {
            **SESSION_READ,
            "best_iteration_id": first,
            "timeline": [
                {
                    "action": "improvement.round_selected",
                    "at": "2026-10-27T09:05:00Z",
                    "actor_user_id": "00000000-0000-4000-8000-0000000000ab",
                    "actor_name": "Bartek",
                }
            ],
        }
        api.request = _responder(
            {
                ("GET", f"/improvements/{SESSION}"): kept,
                ("GET", "/me/permissions"): _permissions("agents:view"),
            }
        )

        session = await _call(server, "get_improvement", session_id=SESSION)

        first_attempt, second_attempt = session["attempts"]
        assert (first_attempt["chosen"], first_attempt["best"]) == (True, False)
        assert (second_attempt["chosen"], second_attempt["best"]) == (False, True)
        assert session["chosen_by"] == "Bartek"

    async def test_an_attempt_the_session_kept_itself_has_nobody_behind_it(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                ("GET", f"/improvements/{SESSION}"): SESSION_READ,
                ("GET", "/me/permissions"): _permissions("agents:view"),
            }
        )

        session = await _call(server, "get_improvement", session_id=SESSION)

        assert session["chosen_by"] is None

    @pytest.mark.parametrize(
        ("topic", "deferred", "state"),
        [
            ({"status": "covered", "has_draft": True}, False, "covered"),
            ({"status": "dismissed"}, False, "dismissed"),
            ({"status": "open", "drafting": True, "has_draft": True}, False, "drafting"),
            ({"status": "open", "draft_failed": True}, False, "draft_failed"),
            ({"status": "open", "has_draft": True}, False, "draft_ready"),
            ({"status": "open", "has_draft": True, "draft_stale": True}, False, "draft_stale"),
            ({"status": "open"}, True, "deferred"),
            ({"status": "open"}, False, "missing"),
        ],
    )
    async def test_each_topic_reads_as_where_it_stands(
        self, server: FastMCP, api: MagicMock, topic: dict[str, Any], deferred: bool, state: str
    ) -> None:
        """A topic whose answer was added to the knowledge base is covered, never "a draft"."""
        api.request = _responder(
            {
                ("GET", f"/improvements/{SESSION}"): {
                    **SESSION_READ,
                    "deferred_topic_ids": [TOPIC] if deferred else [],
                },
                ("GET", "/me/permissions"): _permissions("agents:view", "runs:view"),
                ("GET", f"/agents/{AGENT}/improvements/{SESSION}/evidence"): {
                    "items": [_miss("r1", "missing_knowledge", TOPIC)]
                },
                ("GET", f"/knowledge-gaps/agents/{AGENT}"): {
                    "items": [
                        {
                            "id": TOPIC,
                            "label": "Do you ship to Germany?",
                            "knowledge_base_name": "Help center",
                            **topic,
                        }
                    ]
                },
            }
        )

        session = await _call(server, "get_improvement", session_id=SESSION)

        assert [t["state"] for t in session["missing_knowledge"]] == [state]


class TestTheNoise:
    async def test_a_noisy_test_reads_as_such_with_its_examples_cut_short(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        noise = {
            "noisy": True,
            "held_out": 10,
            "baseline_low": 0.5,
            "baseline_high": 0.7,
            "baseline_spread": 2,
            "unstable": 3,
            "by_attempt": [{"number": 1, "baseline_unstable": 2, "candidate_unstable": 1}],
            "examples": [
                {
                    "case_id": str(uuid.uuid4()),
                    "input": "y" * 400,
                    "attempts": [{"number": 1, "baseline": [True, False], "candidate": [True]}],
                }
            ],
        }
        api.request = _responder(
            {
                ("GET", f"/improvements/{SESSION}"): {**SESSION_READ, "measurement_noise": noise},
                ("GET", "/me/permissions"): _permissions("agents:view"),
            }
        )

        session = await _call(server, "get_improvement", session_id=SESSION)

        read = session["measurement_noise"]
        assert read["noisy"] is True
        assert (read["baseline_low"], read["baseline_high"]) == (0.5, 0.7)
        assert len(read["examples"][0]["input"]) == 200

    async def test_a_session_read_by_its_id_names_its_agent(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        """Nothing but the session id is needed, so a model cannot pair it with the wrong agent."""
        api.request = _responder(
            {
                ("GET", f"/improvements/{SESSION}"): SESSION_READ,
                ("GET", "/me/permissions"): _permissions("agents:view"),
            }
        )

        session = await _call(server, "get_improvement", session_id=SESSION)

        assert session["agent_id"] == str(AGENT)
        assert session["link"] == improvement_link(AGENT, SESSION)
        assert session["measurement_noise"] is None


class TestStepByStep:
    WAITING: dict[str, Any] = {
        **SESSION_READ,
        "status": "waiting",
        "stage": "classifying",
        "next_step": "propose",
    }

    @pytest.mark.parametrize(
        ("next_step", "after", "runs"),
        [("propose", "Understand", "propose changes"), ("check", "Changes", "test the changes")],
    )
    async def test_a_waiting_session_says_where_it_stopped_and_what_comes_next(
        self, server: FastMCP, api: MagicMock, next_step: str, after: str, runs: str
    ) -> None:
        waiting = {**self.WAITING, "next_step": next_step}
        quote = {
            "total_usd": "0.01",
            "expected_usd": "0.004",
            "budget_usd": "0.05",
            "affordable": True,
        }
        api.request = _responder(
            {
                ("GET", f"/agents/{AGENT}/improvements"): [waiting],
                ("POST", f"/agents/{AGENT}/improvements/{SESSION}/continue/estimate"): {
                    **quote,
                    "candidate_hash": "d" * 64,
                },
            }
        )

        [item] = (await _call(server, "list_improvements", agent_id=AGENT))["items"]

        assert item["waiting_for"] == {
            "after": after,
            "next_step": runs,
            "price": {**quote, "candidate_hash": "d" * 64},
        }
        assert item["next_actions"] == [f"Next step: {runs}", "End the session"]
        assert item["closed"] is False

    async def test_a_waiting_session_carries_its_next_step_s_price_and_what_understand_found(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        """At a stop the reply needs the finding and the price; neither is a second tool call."""
        quote = {
            "mode": "next_step",
            "number": 1,
            "total_usd": "0.01",
            "expected_usd": "0.004",
            "budget_usd": "0.05",
            "affordable": True,
            "candidate_hash": "d" * 64,
        }
        api.request = _responder(
            {
                ("GET", f"/improvements/{SESSION}"): self.WAITING,
                ("POST", f"/agents/{AGENT}/improvements/{SESSION}/continue/estimate"): quote,
                ("GET", "/me/permissions"): _permissions("agents:view", "runs:view"),
                ("GET", f"/agents/{AGENT}/improvements/{SESSION}/evidence"): {
                    "items": [
                        _miss("r1", "agent", TOPIC),
                        _miss("r2", "agent", TOPIC),
                        _miss("r3", "unknown"),
                        _miss("r4", "missing_knowledge", OTHER_TOPIC),
                        _miss("r5", "missing_knowledge", None, added=True),
                        _miss("r6", "not_a_problem"),
                    ]
                },
                ("GET", f"/knowledge-gaps/agents/{AGENT}"): {"items": []},
            }
        )

        session = await _call(server, "get_improvement", session_id=SESSION)

        assert session["waiting_for"] == {
            "after": "Understand",
            "next_step": "propose changes",
            "price": {
                "total_usd": "0.01",
                "expected_usd": "0.004",
                "budget_usd": "0.05",
                "affordable": True,
                "candidate_hash": "d" * 64,
            },
        }
        assert session["found"] == {
            "in_the_agent": 2,
            "missing_knowledge": 1,
            "knowledge_added_since": 1,
            "not_a_problem": 1,
        }

    async def test_a_price_that_cannot_be_quoted_says_why_and_still_reads_the_session(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        async def respond(method: str, path: str, **_: Any) -> Any:
            if path.endswith("/continue/estimate"):
                raise ToolError("400 BAD_REQUEST: The improvement session stopped")
            return {
                **UNPUBLISHED,
                ("GET", f"/improvements/{SESSION}"): self.WAITING,
                ("GET", "/me/permissions"): _permissions("agents:view"),
            }[(method, path)]

        api.request = AsyncMock(side_effect=respond)

        session = await _call(server, "get_improvement", session_id=SESSION)

        assert session["waiting_for"]["price"] == {"unavailable": "The improvement session stopped"}
        assert session["status"] == "waiting"

    async def test_a_session_not_waiting_waits_for_nothing(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder({("GET", f"/agents/{AGENT}/improvements"): [SESSION_READ]})

        [item] = (await _call(server, "list_improvements", agent_id=AGENT))["items"]

        assert item["waiting_for"] is None

    @pytest.mark.parametrize(
        ("budget", "sent"), [(None, "0.05"), ("0.08", "0.08")], ids=["session's", "raised"]
    )
    async def test_the_next_step_is_quoted_with_the_session_s_limit_or_a_raised_one(
        self, server: FastMCP, api: MagicMock, budget: str | None, sent: str
    ) -> None:
        quote = {"mode": "next_step", "total_usd": "0.01", "candidate_hash": "d" * 64}
        api.request = _responder(
            {
                ("GET", f"/improvements/{SESSION}"): {**self.WAITING, "next_step": "check"},
                ("POST", f"/agents/{AGENT}/improvements/{SESSION}/continue/estimate"): quote,
            }
        )
        arguments: dict[str, Any] = {"session_id": SESSION}
        if budget is not None:
            arguments["budget_usd"] = budget

        quoted = await _call(server, "estimate_next_improvement_step", **arguments)

        assert api.request.await_args.kwargs == {"json": {"budget_usd": sent}}
        assert quoted["waiting_for"]["next_step"] == "test the changes"
        assert quoted["candidate_hash"] == "d" * 64
        assert quoted["link"] == improvement_link(AGENT, SESSION)

    async def test_the_next_step_runs_on_the_quote_it_was_given(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        moved = {**self.WAITING, "status": "running", "stage": "proposing", "next_step": None}
        api.request = _responder(
            {
                ("GET", f"/improvements/{SESSION}"): self.WAITING,
                ("POST", f"/agents/{AGENT}/improvements/{SESSION}/continue"): moved,
            }
        )

        session = await _call(
            server,
            "run_next_improvement_step",
            session_id=SESSION,
            budget_usd="0.05",
            estimate_usd="0.01",
            candidate_hash="d" * 64,
        )

        assert api.request.await_args.kwargs == {
            "json": {
                "confirmed": True,
                "budget_usd": "0.05",
                "estimate_usd": "0.01",
                "candidate_hash": "d" * 64,
            }
        }
        assert (session["status"], session["stage"]) == ("running", "proposing")
        assert session["waiting_for"] is None


class TestAClosedSession:
    """A published session is history: the Architect reads what was decided, not an offer."""

    PUBLISHED: dict[str, Any] = {
        **SESSION_READ,
        "status": "published",
        "published_version": 7,
        "published_version_id": "00000000-0000-4000-8000-0000000000aa",
        "timeline": [
            {"action": "improvement.ready", "at": "2026-10-27T09:00:00Z", "actor_user_id": None},
            {
                "action": "improvement.round_selected",
                "at": "2026-10-27T09:05:00Z",
                "actor_user_id": "00000000-0000-4000-8000-0000000000ab",
                "actor_name": "Bartek",
            },
            {
                "action": "improvement.published",
                "at": "2026-10-27T09:10:00Z",
                "actor_user_id": "00000000-0000-4000-8000-0000000000ab",
                "actor_name": "Bartek",
            },
        ],
    }

    async def test_a_published_session_says_what_was_decided_and_offers_nothing(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                ("GET", f"/improvements/{SESSION}"): self.PUBLISHED,
                ("GET", "/me/permissions"): _permissions("agents:view"),
            }
        )

        session = await _call(server, "get_improvement", session_id=SESSION)

        assert session["closed"] is True
        assert session["can_accept"] is False
        assert session["outcome"] == {
            "status": "published",
            "attempt": 2,
            "published_version": 7,
            "published_version_id": "00000000-0000-4000-8000-0000000000aa",
            "decided_by": "Bartek",
            "decided_at": "2026-10-27T09:10:00Z",
        }

    async def test_a_listing_marks_closed_and_ready_sessions_apart(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        discarded = {**SESSION_READ, "id": str(uuid.uuid4()), "status": "rejected", "timeline": []}
        api.request = _responder(
            {("GET", f"/agents/{AGENT}/improvements"): [SESSION_READ, discarded, self.PUBLISHED]}
        )

        listing = await _call(server, "list_improvements", agent_id=AGENT, history=True)

        ready, rejected, published = listing["items"]
        assert (ready["closed"], ready["can_accept"], ready["outcome"]) == (False, True, None)
        assert rejected["closed"] is True
        assert rejected["outcome"]["attempt"] is None
        assert rejected["outcome"]["decided_by"] is None
        assert published["outcome"]["published_version"] == 7


V7, V8 = "00000000-0000-4000-8000-0000000000a7", "00000000-0000-4000-8000-0000000000a8"


def _published_as(live: str | None) -> dict[tuple[str, str], Any]:
    return {
        ("GET", f"/agents/{AGENT}"): {"id": AGENT, "current_version_id": live},
        ("GET", f"/agents/{AGENT}/versions"): {
            "items": [{"id": V8, "version": 8}, {"id": V7, "version": 7}],
            "total": 2,
        },
    }


class TestTheNewestSessionAndTheLiveVersion:
    """Asked how improving stands, it once took an older session's v7 for the live version
    and filed the newest session - outdated by a v8 published by hand - under history."""

    OLDER = {
        **SESSION_READ,
        "id": str(uuid.uuid4()),
        "status": "published",
        "created_at": "2026-10-26T08:00:00Z",
        "published_version": 7,
        "published_version_id": V7,
    }
    NEWEST = {
        **SESSION_READ,
        "status": "stale",
        "stop_reason": "stale",
        "created_at": "2026-10-27T08:00:00Z",
        "base_version_id": V7,
    }

    async def test_the_newest_session_comes_first_beside_the_version_live_now(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                **_published_as(V8),
                ("GET", f"/agents/{AGENT}/improvements"): [self.OLDER, self.NEWEST],
            }
        )

        listing = await _call(server, "list_improvements", agent_id=AGENT, history=True)

        newest, older = listing["items"]
        assert listing["current_published_version"] == 8
        assert (newest["id"], newest["newest"], older["newest"]) == (str(SESSION), True, False)
        assert newest["started_from_version"] == 7
        assert newest["why_stale"] == "The agent's published version changed from v7 to v8."
        assert older["outcome"]["published_version"] == 7
        assert older["why_stale"] is None

    async def test_one_session_read_says_what_is_live_and_why_it_is_outdated(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                **_published_as(V8),
                ("GET", f"/improvements/{SESSION}"): self.NEWEST,
                ("GET", "/me/permissions"): _permissions("agents:view"),
            }
        )

        session = await _call(server, "get_improvement", session_id=SESSION)

        assert session["current_published_version"] == 8
        assert session["why_stale"] == "The agent's published version changed from v7 to v8."

    @pytest.mark.parametrize(
        ("changes", "why"),
        [
            ({"stop_reason": "expired"}, "It waited too long for a person and expired."),
            (
                {"stop_reason": "superseded"},
                "A newer attempt or a person's own change replaced it.",
            ),
            (
                {"base_version_id": V8, "error": "The test questions changed"},
                "The test questions changed",
            ),
            (
                {"base_version_id": V8},
                "The agent, its test questions or how they are scored changed after it started.",
            ),
        ],
        ids=["expired", "superseded", "its own error", "something else changed"],
    )
    async def test_an_outdated_session_says_why_in_plain_words(
        self, server: FastMCP, api: MagicMock, changes: dict[str, Any], why: str
    ) -> None:
        stale = {**self.NEWEST, "error": None, **changes}
        api.request = _responder(
            {**_published_as(V8), ("GET", f"/agents/{AGENT}/improvements"): [stale]}
        )

        [item] = (await _call(server, "list_improvements", agent_id=AGENT))["items"]

        assert item["why_stale"] == why

    async def test_a_live_version_older_than_the_last_hundred_is_read_by_its_id(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        rolled_back = str(uuid.uuid4())
        api.request = _responder(
            {
                **_published_as(rolled_back),
                ("GET", f"/agents/{AGENT}/versions/{rolled_back}"): {
                    "id": rolled_back,
                    "version": 3,
                },
                ("GET", f"/agents/{AGENT}/improvements"): [self.NEWEST],
            }
        )

        listing = await _call(server, "list_improvements", agent_id=AGENT)

        assert listing["current_published_version"] == 3
        assert listing["items"][0]["why_stale"] == (
            "The agent's published version changed from v7 to v3."
        )


FIRST_ATTEMPT = {**SESSION_READ["iterations"][0], "number": 1, "verdict": "regression"}


class TestWhatCanBeDoneNow:
    """Asked how improving stood, it said a session stopped after a regression "cannot be
    accepted or continued", at attempt 1 of 3 with budget left - Try again was on offer."""

    REGRESSED = {
        **SESSION_READ,
        "status": "stopped",
        "stop_reason": "regression",
        "stage": "judging",
        "iteration": 1,
        "max_iterations": 3,
        "spent_usd": "0.078",
        "budget_usd": "0.89",
        "iterations": [FIRST_ATTEMPT],
        "can_restart": True,
    }

    async def test_a_regressed_first_attempt_offers_another_beside_the_live_version(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {**_published_as(V8), ("GET", f"/agents/{AGENT}/improvements"): [self.REGRESSED]}
        )

        [newest] = (await _call(server, "list_improvements", agent_id=AGENT))["items"]

        assert newest["live_version"] == 8
        assert (newest["attempt"], newest["max_attempts"]) == (1, 3)
        assert (newest["can_accept"], newest["can_try_again"]) == (False, True)
        assert newest["next_actions"] == ["Try again (attempt 2 of 3)", "End the session"]

    async def test_an_agent_never_improved_lists_no_sessions_beside_its_live_version(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {**_published_as(V8), ("GET", f"/agents/{AGENT}/improvements"): []}
        )

        listing = await _call(server, "list_improvements", agent_id=AGENT)

        assert listing == {"current_published_version": 8, "items": [], "earlier_sessions": 0}

    @pytest.mark.parametrize(
        ("changes", "actions"),
        [
            ({"status": "running", "stop_reason": None}, ["Stop the session"]),
            ({"status": "published", "stop_reason": None}, []),
            (
                {"status": "failed", "stage": "proposing", "stop_reason": "proposal"},
                ["Retry this step", "End the session"],
            ),
            (
                {"stop_reason": "budget", "stage": "evaluating"},
                ["Continue this step", "Try again (attempt 2 of 3)", "End the session"],
            ),
            (
                {"status": "ready", "stop_reason": None},
                ["Accept the chosen attempt", "Try again (attempt 2 of 3)", "End the session"],
            ),
            ({"stop_reason": "repeat_candidate"}, ["End the session"]),
            ({"iteration": 3, "max_iterations": 3}, ["End the session"]),
            ({"iterations": [{**FIRST_ATTEMPT, "verdict": None}]}, ["End the session"]),
            ({"can_restart": False}, ["End the session"]),
            ({"can_discard": False}, ["Try again (attempt 2 of 3)"]),
        ],
        ids=[
            "running",
            "closed",
            "failed step",
            "out of budget",
            "ready",
            "repeated changes",
            "no attempts left",
            "nothing measured",
            "someone else's to continue",
            "not theirs to end",
        ],
    )
    async def test_each_session_offers_what_the_wizard_offers_on_it(
        self,
        server: FastMCP,
        api: MagicMock,
        changes: dict[str, Any],
        actions: list[str],
    ) -> None:
        api.request = _responder(
            {("GET", f"/agents/{AGENT}/improvements"): [{**self.REGRESSED, **changes}]}
        )

        [item] = (await _call(server, "list_improvements", agent_id=AGENT))["items"]

        assert item["next_actions"] == actions


class TestTheWizardsWords:
    """It told the person a session was at stage "filtering" and quoted "400 BAD_REQUEST"."""

    @pytest.mark.parametrize(
        ("changes", "step"),
        [
            ({"status": "waiting", "next_step": "propose"}, "Understand"),
            ({"status": "waiting", "stage": "filtering", "next_step": "check"}, "Changes"),
            ({"status": "running", "stage": "classifying"}, "Understand"),
            ({"status": "running", "stage": "proposing"}, "Changes"),
            ({"status": "queued", "stage": "evaluating"}, "Check"),
            ({"status": "stopped", "stage": "judging"}, "Result"),
            ({"status": "ready", "stage": "judging"}, "Result"),
            ({"status": "published", "stage": "judging"}, "Accept"),
        ],
    )
    async def test_a_session_names_its_step_as_the_wizard_does(
        self, server: FastMCP, api: MagicMock, changes: dict[str, Any], step: str
    ) -> None:
        session = {**SESSION_READ, "stop_reason": None, **changes}
        api.request = _responder(
            {
                ("GET", f"/agents/{AGENT}/improvements"): [session],
                ("POST", f"/agents/{AGENT}/improvements/{SESSION}/continue/estimate"): {
                    "total_usd": "0.01",
                    "expected_usd": "0.004",
                    "budget_usd": "0.05",
                    "affordable": True,
                    "candidate_hash": "d" * 64,
                },
            }
        )

        [item] = (await _call(server, "list_improvements", agent_id=AGENT))["items"]

        assert item["step"] == step

    @pytest.mark.parametrize(
        ("reason", "words"),
        [
            ("regression", "The changes made some answers worse."),
            (
                "knowledge_only",
                "Every problem was missing knowledge, so there was nothing to change in the agent.",
            ),
            (None, None),
        ],
    )
    async def test_why_a_session_stopped_is_said_in_plain_words(
        self, server: FastMCP, api: MagicMock, reason: str | None, words: str | None
    ) -> None:
        api.request = _responder(
            {("GET", f"/agents/{AGENT}/improvements"): [{**SESSION_READ, "stop_reason": reason}]}
        )

        [item] = (await _call(server, "list_improvements", agent_id=AGENT))["items"]

        assert item["why_stopped"] == words


class TestTheSummary:
    """Told how improving stood, it left out the live version and that an attempt broke a
    question - the one fact that matters before accepting - and called an attempt "the one
    kept" before anybody had chosen one."""

    WORSE_KEPT = {
        **SESSION_READ,
        "status": "ready",
        "stop_reason": None,
        "can_restart": True,
        "best_iteration_id": SESSION_READ["iterations"][0]["id"],
    }

    async def test_a_ready_session_warns_of_a_worse_attempt_beside_the_live_version(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {**_published_as(V8), ("GET", f"/agents/{AGENT}/improvements"): [self.WORSE_KEPT]}
        )

        [newest] = (await _call(server, "list_improvements", agent_id=AGENT))["items"]

        assert newest["summary"] == (
            "v8 is live. The newest session has a result to decide on, after attempt 2 of 3. "
            "Warning: attempt 1 makes the agent worse - it breaks 1 question the agent "
            "answered well before, and fixes 2. Attempt 2 fixes 3 questions and breaks none. "
            "What can be done now: Accept attempt 1; Keep attempt 2; Try again (attempt 3 of "
            "3); End the session."
        )
        assert "kept" not in newest["summary"]

    async def test_one_session_read_carries_the_same_summary(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                **_published_as(V8),
                ("GET", f"/improvements/{SESSION}"): self.WORSE_KEPT,
                ("GET", "/me/permissions"): _permissions("agents:view"),
            }
        )

        session = await _call(server, "get_improvement", session_id=SESSION)

        assert session["summary"].startswith("v8 is live.")
        assert "Warning: attempt 1 makes the agent worse" in session["summary"]

    @pytest.mark.parametrize(
        ("changes", "live", "says"),
        [
            (
                {"status": "ready", "stop_reason": None},
                None,
                "No version of the agent is published yet.",
            ),
            (
                {"status": "ready", "stop_reason": None},
                V8,
                "Attempt 2 fixes 3 questions and breaks none.",
            ),
            (
                {"status": "published", "published_version": 7},
                V8,
                "The newest session is over: it published v7, since replaced by v8.",
            ),
            (
                {"status": "published", "published_version": 8},
                V8,
                "The newest session is over: it published v8.",
            ),
            ({"status": "accepted"}, V8, "its changes were accepted as a draft."),
            ({"status": "rejected"}, V8, "ended without changing the agent."),
            (
                {"status": "stale", "stop_reason": "expired"},
                V8,
                "can no longer be used: It waited too long for a person and expired.",
            ),
            (
                {"status": "running", "stage": "proposing"},
                V8,
                "is working on Changes, attempt 2 of 3.",
            ),
            (
                {"status": "stopped", "stop_reason": "budget", "stage": "evaluating"},
                V8,
                "stopped after attempt 2 of 3: It reached its spending limit.",
            ),
            (
                {"status": "failed", "stop_reason": None, "stage": "judging"},
                V8,
                "stopped after attempt 2 of 3: A step failed.",
            ),
            (
                {
                    "status": "ready",
                    "stop_reason": None,
                    "iterations": [{**FIRST_ATTEMPT, "verdict": "no_change", "verdict_detail": {}}],
                    "best_iteration_id": None,
                },
                V8,
                "Attempt 1 made no measurable difference.",
            ),
            (
                {
                    "status": "ready",
                    "stop_reason": None,
                    "iterations": [
                        {**FIRST_ATTEMPT, "verdict": "inconclusive", "verdict_detail": {}}
                    ],
                    "best_iteration_id": None,
                },
                V8,
                "The test could not tell whether attempt 1 helped.",
            ),
            (
                {
                    "status": "waiting",
                    "stop_reason": None,
                    "next_step": "propose",
                    "iterations": [],
                },
                V8,
                "waits at the Understand stop for a go-ahead. What can be done now: Next step: "
                "propose changes; End the session. The next step most likely costs about "
                "$0.004, at most $0.01.",
            ),
        ],
        ids=[
            "nothing published",
            "better kept",
            "published, since replaced",
            "published and live",
            "accepted",
            "rejected",
            "outdated",
            "running",
            "stopped",
            "failed",
            "no change",
            "inconclusive",
            "waiting with its price",
        ],
    )
    async def test_the_summary_says_where_the_newest_session_stands(
        self,
        server: FastMCP,
        api: MagicMock,
        changes: dict[str, Any],
        live: str | None,
        says: str,
    ) -> None:
        api.request = _responder(
            {
                **_published_as(live),
                ("GET", f"/agents/{AGENT}/improvements"): [{**SESSION_READ, **changes}],
                ("POST", f"/agents/{AGENT}/improvements/{SESSION}/continue/estimate"): {
                    "total_usd": "0.01",
                    "expected_usd": "0.004",
                    "budget_usd": "0.05",
                    "affordable": True,
                    "candidate_hash": "d" * 64,
                },
            }
        )

        [newest] = (await _call(server, "list_improvements", agent_id=AGENT))["items"]

        assert says in newest["summary"]


class TestOnlyTheNewestSessionAndAPersonsChoice:
    """It mixed an ended session into the newest one's state, said "the one kept" before
    anyone chose, and left out "Keep attempt 1 anyway" on the result."""

    STOPPED = {
        **SESSION_READ,
        "status": "stopped",
        "stop_reason": "regression",
        "can_restart": True,
        "best_iteration_id": SESSION_READ["iterations"][0]["id"],
        "timeline": [],
    }

    def _chose(self, at: str) -> dict[str, Any]:
        return {
            **self.STOPPED,
            "status": "ready",
            "timeline": [
                {"action": "improvement.verdict", "at": "2026-10-27T09:00:00Z"},
                {
                    "action": "improvement.round_selected",
                    "at": at,
                    "actor_user_id": "00000000-0000-4000-8000-0000000000ab",
                    "actor_name": "Bartek",
                },
            ],
        }

    async def _newest(self, api: MagicMock, server: FastMCP, *sessions: Any) -> Any:
        api.request = _responder({("GET", f"/agents/{AGENT}/improvements"): list(sessions)})
        return await _call(server, "list_improvements", agent_id=AGENT, history=True)

    async def test_a_stopped_result_offers_keeping_each_attempt_as_the_wizard_does(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        [newest] = (await self._newest(api, server, self.STOPPED))["items"]

        assert newest["next_actions"][:2] == ["Keep attempt 1 anyway", "Keep attempt 2"]

    async def test_one_attempt_or_no_access_offers_no_choice(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        one = {**self.STOPPED, "iterations": SESSION_READ["iterations"][:1]}
        [single] = (await self._newest(api, server, one))["items"]
        [locked] = (await self._newest(api, server, {**self.STOPPED, "can_restart": False}))[
            "items"
        ]

        assert not any(action.startswith("Keep") for action in single["next_actions"])
        assert not any(action.startswith("Keep") for action in locked["next_actions"])

    async def test_a_choice_a_person_made_after_the_verdict_is_said(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        [newest] = (await self._newest(api, server, self._chose("2026-10-27T09:05:00Z")))["items"]

        assert "Bartek chose attempt 1 to accept." in newest["summary"]

    async def test_a_choice_older_than_the_verdict_is_not_said(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        [newest] = (await self._newest(api, server, self._chose("2026-10-27T08:55:00Z")))["items"]

        assert "chose" not in newest["summary"]

    async def test_older_sessions_are_records_without_offers(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        older = {
            **SESSION_READ,
            "id": str(uuid.uuid4()),
            "status": "rejected",
            "created_at": "2026-10-20T08:00:00Z",
        }

        newest, earlier = (await self._newest(api, server, older, self.STOPPED))["items"]

        assert newest["next_actions"]
        assert set(earlier) == {
            "id",
            "status",
            "created_at",
            "finished_at",
            "closed",
            "outcome",
            "why_stale",
            "started_from_version",
            "link",
            "newest",
        }


class TestTheLastRound:
    """After the newest session it still listed older ones with links, offered Try again
    where a session had nothing left to learn from, and asked its question in prose."""

    MIXED = {
        **SESSION_READ,
        "status": "ready",
        "stop_reason": None,
        "can_restart": True,
        "timeline": [],
    }

    async def test_only_the_newest_session_is_listed_unless_history_is_asked_for(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        older = {
            **SESSION_READ,
            "id": str(uuid.uuid4()),
            "status": "rejected",
            "created_at": "2026-10-20T08:00:00Z",
        }
        api.request = _responder({("GET", f"/agents/{AGENT}/improvements"): [older, self.MIXED]})

        listing = await _call(server, "list_improvements", agent_id=AGENT)
        everything = await _call(server, "list_improvements", agent_id=AGENT, history=True)

        assert [item["id"] for item in listing["items"]] == [str(SESSION)]
        assert listing["earlier_sessions"] == 1
        assert [item["id"] for item in everything["items"]] == [str(SESSION), older["id"]]

    @pytest.mark.parametrize(
        ("blocked", "why"),
        [
            (
                {"reason": "nothing_to_learn"},
                "Another attempt has nothing to learn from: no answer this session reads "
                "still fails.",
            ),
            (
                {"reason": "missing_holdout", "needed": 3},
                "Another attempt can't be checked: 3 more questions kept aside would be "
                "needed, and this session's questions are fixed.",
            ),
            (
                {"reason": "missing_holdout", "needed": 1},
                "Another attempt can't be checked: 1 more question kept aside would be needed",
            ),
        ],
        ids=["nothing to learn", "too few kept aside", "one too few"],
    )
    async def test_a_blocked_try_again_is_not_offered_and_the_summary_says_why(
        self, server: FastMCP, api: MagicMock, blocked: dict[str, Any], why: str
    ) -> None:
        api.request = _responder(
            {
                ("GET", f"/agents/{AGENT}/improvements"): [
                    {**self.MIXED, "try_again_blocked": blocked}
                ]
            }
        )

        [newest] = (await _call(server, "list_improvements", agent_id=AGENT))["items"]

        assert newest["can_try_again"] is False
        assert not any(action.startswith("Try again") for action in newest["next_actions"])
        assert f"Trying again is not offered: {why}" in newest["summary"]

    async def test_the_closing_question_is_ready_as_ask_user_question_arguments(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder({("GET", f"/agents/{AGENT}/improvements"): [self.MIXED]})

        [newest] = (await _call(server, "list_improvements", agent_id=AGENT))["items"]

        [question] = newest["ask"]["questions"]
        assert [option["label"] for option in question["options"]] == newest["next_actions"]
        assert question["question"] == "What would you like to do?"

    @pytest.mark.parametrize(
        ("changes", "labels"),
        [
            ({"status": "running"}, ["Stop the session", "Not now"]),
            ({"status": "published"}, None),
        ],
        ids=["one action", "closed"],
    )
    async def test_a_single_action_still_offers_two_choices_and_a_closed_one_none(
        self,
        server: FastMCP,
        api: MagicMock,
        changes: dict[str, Any],
        labels: list[str] | None,
    ) -> None:
        api.request = _responder(
            {("GET", f"/agents/{AGENT}/improvements"): [{**self.MIXED, **changes}]}
        )

        [newest] = (await _call(server, "list_improvements", agent_id=AGENT))["items"]

        ask = newest["ask"]
        assert (ask and [o["label"] for o in ask["questions"][0]["options"]]) == labels


class TestFindingSessionsWithoutAnId:
    """With no agent id to hand, it made one up, the call failed, and it said nothing was
    waiting - while one session waited after Understand and another had a result."""

    async def test_with_no_agent_it_lists_every_open_session_by_agent_name(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        waiting = {
            **SESSION_READ,
            "status": "waiting",
            "stage": "classifying",
            "next_step": "propose",
            "created_at": "2026-10-27T10:00:00Z",
        }
        published = {**SESSION_READ, "id": str(uuid.uuid4()), "status": "published"}
        quote = {
            "total_usd": "0.01",
            "expected_usd": "0.004",
            "budget_usd": "0.05",
            "affordable": True,
            "candidate_hash": "d" * 64,
        }
        api.request = _responder(
            {
                ("GET", "/improvements"): [
                    {"id": str(SESSION), "agent_id": str(AGENT), "agent_name": "Refund desk"}
                ],
                ("GET", f"/agents/{AGENT}/improvements"): [published, waiting],
                ("POST", f"/agents/{AGENT}/improvements/{SESSION}/continue/estimate"): quote,
            }
        )

        listing = await _call(server, "list_improvements")

        [found] = listing["open_sessions"]
        assert (found["id"], found["agent_name"], found["status"]) == (
            str(SESSION),
            "Refund desk",
            "waiting",
        )
        assert found["next_actions"] == ["Next step: propose changes", "End the session"]
        assert found["waiting_for"]["price"]["total_usd"] == "0.01"
        assert api.request.await_args_list[0].kwargs == {"params": {"open": "true"}}

    @pytest.mark.parametrize("name", ["refund desk", "  Refund Desk ", "refund"])
    async def test_an_agent_can_be_named_instead_of_identified(
        self, server: FastMCP, api: MagicMock, name: str
    ) -> None:
        api.request = _responder(
            {
                ("GET", "/agents"): {
                    "items": [
                        {"id": str(AGENT), "name": "Refund desk"},
                        {"id": str(uuid.uuid4()), "name": "Sales"},
                    ]
                },
                ("GET", f"/agents/{AGENT}/improvements"): [SESSION_READ],
            }
        )

        listing = await _call(server, "list_improvements", agent_name=name)

        assert (listing["agent_id"], listing["agent_name"]) == (str(AGENT), "Refund desk")
        assert [item["id"] for item in listing["items"]] == [str(SESSION)]

    @pytest.mark.parametrize(
        ("name", "refusal"),
        [
            ("desk", "Several agents match 'desk': Refund desk"),
            ("Billing", "No agent is named 'Billing'. This is not an empty result"),
        ],
        ids=["ambiguous", "unknown"],
    )
    async def test_a_name_that_is_not_one_agent_is_refused_not_answered_with_nothing(
        self, server: FastMCP, api: MagicMock, name: str, refusal: str
    ) -> None:
        api.request = _responder(
            {
                ("GET", "/agents"): {
                    "items": [
                        {"id": str(AGENT), "name": "Refund desk"},
                        {"id": str(uuid.uuid4()), "name": "Help desk"},
                    ]
                }
            }
        )
        api.refuse = MagicMock(side_effect=ToolError("refused"))

        with pytest.raises(ToolError):
            await _call(server, "list_improvements", agent_name=name)

        assert api.refuse.call_args.args[0].startswith(refusal)


QUOTE = {"total_usd": "0.01", "per_round_usd": "0.03", "max_iterations": 3}


class TestEstimatingAndDatasets:
    async def test_an_estimate_names_one_target(self, server: FastMCP, api: MagicMock) -> None:
        api.request = AsyncMock(return_value=QUOTE)

        await _call(server, "estimate_improvement", agent_id=AGENT, dataset_id=DATASET)

        assert api.request.await_args.args == ("POST", f"/agents/{AGENT}/improvements/estimate")
        assert api.request.await_args.kwargs == {
            "json": {"max_iterations": 3, "dataset_id": str(DATASET)}
        }

    async def test_an_estimate_can_name_a_suite_instead(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = AsyncMock(return_value=QUOTE)

        await _call(server, "estimate_improvement", agent_id=AGENT, suite_id=DATASET)

        assert api.request.await_args.kwargs == {
            "json": {"max_iterations": 3, "suite_id": str(DATASET)}
        }

    @pytest.mark.parametrize(
        ("total", "per_round", "rounds", "limit"),
        [
            ("0.012", "0.0333", 3, "0.12"),
            ("0.01", "0.03", 3, "0.10"),
            ("0", "0.001", 1, "0.01"),
        ],
        ids=["rounded up to the cent", "exact", "never below a cent"],
    )
    async def test_an_estimate_offers_the_wizard_s_limit_for_the_whole_session(
        self,
        server: FastMCP,
        api: MagicMock,
        total: str,
        per_round: str,
        rounds: int,
        limit: str,
    ) -> None:
        """The start is priced only up to Understand; the limit covers every attempt after it."""
        api.request = AsyncMock(
            return_value={"total_usd": total, "per_round_usd": per_round, "max_iterations": rounds}
        )

        estimate = await _call(server, "estimate_improvement", agent_id=AGENT, dataset_id=DATASET)

        assert estimate["limit_usd"] == limit
        assert estimate["total_usd"] == total

    async def test_every_dataset_is_listed_when_no_agent_is_named(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = AsyncMock(return_value={"total": 0, "items": []})

        await _call(server, "list_datasets")

        assert api.request.await_args.kwargs == {"params": {"limit": 50, "skip": 0}}

    async def test_datasets_are_listed_by_name_size_and_whether_they_can_run(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = AsyncMock(
            return_value={
                "total": 1,
                "items": [
                    {
                        "id": str(DATASET),
                        "name": "Refund questions",
                        "case_count": 12,
                        "latest_version": 3,
                        "can_run": True,
                        "scoring": {"judge": {"criteria": ["long"]}},
                    }
                ],
            }
        )

        listing = await _call(server, "list_datasets", agent_id=AGENT)

        assert api.request.await_args.kwargs == {
            "params": {"limit": 50, "skip": 0, "agent": str(AGENT)}
        }
        assert listing["items"] == [
            {
                "id": str(DATASET),
                "name": "Refund questions",
                "case_count": 12,
                "latest_version": 3,
                "can_run": True,
            }
        ]


class TestReadingAnEvalRun:
    RUN_READ: dict[str, Any] = {
        "id": str(RUN),
        "agent_id": str(AGENT),
        "dataset_name": "Refund questions",
        "status": "completed",
        "paired": True,
        "cases": 12,
        "cost_usd": "0.02",
        "outcome": {
            "verdict": "mixed",
            "baseline_pass_rate": 0.5,
            "candidate_pass_rate": 0.7,
            "regressions_confirmed": 1,
            "fixed_confirmed": 3,
        },
    }

    async def test_a_run_names_a_few_broken_and_fixed_questions_with_the_grader_s_reason(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        candidate, baseline = str(uuid.uuid4()), str(uuid.uuid4())
        canada, masked = str(uuid.uuid4()), str(uuid.uuid4())
        cases = [
            {"case_id": str(uuid.uuid4()), "input": "x" * 500, "flip": "fixed", "confirmed": True}
            for _ in range(6)
        ] + [
            {
                "case_id": masked,
                "input": "From a conversation you cannot open",
                "flip": "fixed",
                "confirmed": True,
            },
            {"case_id": canada, "input": "Canada?", "flip": "regression", "confirmed": False},
            {
                "case_id": str(uuid.uuid4()),
                "input": "Same",
                "flip": "unchanged",
                "confirmed": False,
            },
        ]

        def attempts(reason: str | None) -> list[dict[str, Any]]:
            return [
                {
                    "arm_id": baseline,
                    "attempt": 0,
                    "score": {"results": [{"scorer": "judge", "reason": "the old answer"}]},
                },
                {
                    "arm_id": candidate,
                    "attempt": 1,
                    "score": {"results": [{"scorer": "judge", "reason": "a rerun"}]},
                },
                {
                    "arm_id": candidate,
                    "attempt": 0,
                    "score": None
                    if reason is None
                    else {
                        "results": [
                            {"scorer": "check", "reason": "contains 'ship'"},
                            {"scorer": "judge", "reason": reason},
                        ]
                    },
                },
            ]

        listing = {
            "items": [
                {
                    "case_id": canada,
                    "attempts": attempts("Says we ship to Canada; we do not. " * 10),
                },
                {"case_id": masked, "attempts": attempts(None)},
            ]
        }
        api.request = _responder(
            {
                ("GET", f"/eval-runs/{RUN}"): self.RUN_READ,
                ("GET", f"/eval-runs/{RUN}/comparison"): {
                    "cases": cases,
                    "candidate": {"arm_id": candidate},
                },
                ("GET", f"/eval-runs/{RUN}/cases"): listing,
            }
        )

        run = await _call(server, "get_eval_run", run_id=RUN)

        assert run["verdict"] == "mixed"
        assert run["pass_rate"] == {"baseline": 0.5, "candidate": 0.7}
        [broken] = run["broken"]
        assert broken["input"] == "Canada?"
        assert broken["judge_reason"].startswith("Says we ship to Canada")
        assert len(broken["judge_reason"]) == 150
        assert len(run["fixed"]) == 5
        assert all(
            len(case["input"]) == 200 for case in run["fixed"][:5] if case["case_id"] != masked
        )
        listed = api.request.await_args_list[-1]
        assert listed.args == ("GET", f"/eval-runs/{RUN}/cases")
        assert set(listed.kwargs["params"]["case_id"]) == {
            c["case_id"] for c in run["broken"] + run["fixed"]
        }

    async def test_a_question_from_a_conversation_the_caller_cannot_open_has_no_reason(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        """The API leaves a masked case's score out; the tool never fills a reason in."""
        candidate, masked = str(uuid.uuid4()), str(uuid.uuid4())
        api.request = _responder(
            {
                ("GET", f"/eval-runs/{RUN}"): self.RUN_READ,
                ("GET", f"/eval-runs/{RUN}/comparison"): {
                    "cases": [
                        {
                            "case_id": masked,
                            "input": "From a conversation you cannot open",
                            "flip": "fixed",
                            "confirmed": True,
                        }
                    ],
                    "candidate": {"arm_id": candidate},
                },
                ("GET", f"/eval-runs/{RUN}/cases"): {
                    "items": [
                        {
                            "case_id": masked,
                            "attempts": [{"arm_id": candidate, "attempt": 0, "score": None}],
                        }
                    ]
                },
            }
        )

        run = await _call(server, "get_eval_run", run_id=RUN)

        assert run["fixed"][0]["judge_reason"] is None

    async def test_a_run_that_changed_nothing_reads_no_cases(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                ("GET", f"/eval-runs/{RUN}"): self.RUN_READ,
                ("GET", f"/eval-runs/{RUN}/comparison"): {
                    "cases": [],
                    "candidate": {"arm_id": "a"},
                },
            }
        )

        run = await _call(server, "get_eval_run", run_id=RUN)

        assert (run["broken"], run["fixed"]) == ([], [])
        assert api.request.await_count == 2

    @pytest.mark.parametrize(("status", "paired"), [("running", True), ("completed", False)])
    async def test_a_run_without_a_finished_comparison_reads_without_one(
        self, server: FastMCP, api: MagicMock, status: str, paired: bool
    ) -> None:
        api.request = _responder(
            {("GET", f"/eval-runs/{RUN}"): {**self.RUN_READ, "status": status, "paired": paired}}
        )

        run = await _call(server, "get_eval_run", run_id=RUN)

        assert "broken" not in run
        assert api.request.await_count == 1


class TestActingOnASession:
    async def test_a_session_starts_with_the_estimate_as_its_cap(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        closed = {**SESSION_READ, "status": "published"}
        api.request = AsyncMock(side_effect=[[closed], SESSION_READ])

        started = await _call(
            server, "start_improvement", agent_id=AGENT, budget_usd="0.04", suite_id=DATASET
        )

        assert api.request.await_args.args == ("POST", f"/agents/{AGENT}/improvements")
        assert api.request.await_args.kwargs == {
            "json": {"max_iterations": 3, "budget_usd": "0.04", "suite_id": str(DATASET)}
        }
        assert started["link"] == improvement_link(AGENT, SESSION)

    async def test_a_session_can_start_on_test_questions(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = AsyncMock(side_effect=[[], SESSION_READ])

        await _call(
            server, "start_improvement", agent_id=AGENT, budget_usd="0.04", dataset_id=DATASET
        )

        assert api.request.await_args.kwargs == {
            "json": {"max_iterations": 3, "budget_usd": "0.04", "dataset_id": str(DATASET)}
        }

    async def test_trying_again_is_quoted_first(self, server: FastMCP, api: MagicMock) -> None:
        quote = {"mode": "next_round", "total_usd": "0.02", "candidate_hash": "c" * 64}
        api.request = AsyncMock(return_value=quote)

        quoted = await _call(
            server, "estimate_improve_again", agent_id=AGENT, session_id=SESSION, budget_usd="0.05"
        )

        assert api.request.await_args.args == (
            "POST",
            f"/agents/{AGENT}/improvements/{SESSION}/continue/estimate",
        )
        assert api.request.await_args.kwargs == {"json": {"budget_usd": "0.05"}}
        assert quoted == quote

    async def test_a_second_open_session_is_refused_with_a_link_to_the_first(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        """One open session per agent: the Architect names it rather than failing on a 409."""
        waiting = {**SESSION_READ, "status": "waiting", "stage": "filtering"}
        api.request = AsyncMock(return_value=[waiting])
        api.refuse = MagicMock(side_effect=ToolError("refused"))

        with pytest.raises(ToolError):
            await _call(
                server, "start_improvement", agent_id=AGENT, budget_usd="0.04", dataset_id=DATASET
            )

        [message] = api.refuse.call_args.args
        assert improvement_link(AGENT, SESSION) in message
        assert "end_improvement" in message
        assert api.request.await_count == 1

    async def test_trying_again_carries_the_person_s_note(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = AsyncMock(return_value=SESSION_READ)

        await _call(
            server,
            "improve_again",
            agent_id=AGENT,
            session_id=SESSION,
            budget_usd="0.05",
            estimate_usd="0.02",
            candidate_hash="c" * 64,
            note="Keep the refund window at 30 days",
        )

        assert api.request.await_args.kwargs["json"]["note"] == "Keep the refund window at 30 days"

    async def test_an_attempt_is_chosen_by_its_number(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = AsyncMock(return_value=SESSION_READ)

        await _call(server, "use_attempt", agent_id=AGENT, session_id=SESSION, attempt=2)

        assert api.request.await_args.args == (
            "POST",
            f"/agents/{AGENT}/improvements/{SESSION}/rounds/2/select",
        )

    @pytest.mark.parametrize("publish", [True, False])
    async def test_accepting_is_one_confirmed_finish_publishing_only_when_asked(
        self, server: FastMCP, api: MagicMock, publish: bool
    ) -> None:
        api.request = AsyncMock(
            return_value={"session": {**SESSION_READ, "status": "published"}, "version": 4}
        )

        accepted = await server.call_tool(
            "accept_improvement",
            {"agent_id": str(AGENT), "session_id": str(SESSION), "publish": publish},
        )

        assert api.request.await_args.args == (
            "POST",
            f"/agents/{AGENT}/improvements/{SESSION}/finish",
        )
        assert api.request.await_args.kwargs == {
            "json": {"confirmed": True, "publish": publish, "automatic_check": False}
        }
        assert accepted.structured_content["version"] == 4

    @pytest.mark.parametrize(
        ("status", "action", "body"),
        [
            ("running", "cancel", {}),
            ("queued", "cancel", {}),
            ("ready", "discard", {"json": {"confirmed": True}}),
            ("stopped", "discard", {"json": {"confirmed": True}}),
            ("waiting", "discard", {"json": {"confirmed": True}}),
            ("failed", "discard", {"json": {"confirmed": True}}),
        ],
    )
    async def test_ending_stops_a_running_session_and_discards_a_finished_one(
        self, server: FastMCP, api: MagicMock, status: str, action: str, body: dict[str, Any]
    ) -> None:
        path = f"/agents/{AGENT}/improvements/{SESSION}"
        api.request = AsyncMock(
            side_effect=[{**SESSION_READ, "status": status}, {**SESSION_READ, "status": "rejected"}]
        )

        ended = await _call(server, "end_improvement", agent_id=AGENT, session_id=SESSION)

        assert api.request.await_args.args == ("POST", f"{path}/{action}")
        assert api.request.await_args.kwargs == body
        assert ended["status"] == "rejected"

    async def test_trying_again_passes_on_the_estimate_it_was_quoted(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = AsyncMock(return_value=SESSION_READ)

        await _call(
            server,
            "improve_again",
            agent_id=AGENT,
            session_id=SESSION,
            budget_usd="0.05",
            estimate_usd="0.02",
            candidate_hash="c" * 64,
        )

        assert api.request.await_args.args == (
            "POST",
            f"/agents/{AGENT}/improvements/{SESSION}/continue",
        )
        assert api.request.await_args.kwargs == {
            "json": {
                "confirmed": True,
                "budget_usd": "0.05",
                "estimate_usd": "0.02",
                "candidate_hash": "c" * 64,
            }
        }


class TestDraftingKnowledge:
    async def test_the_estimate_is_the_topic_s_draft_estimate(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = AsyncMock(return_value={"total_usd": None})

        estimate = await _call(server, "estimate_knowledge_draft", topic_id=TOPIC)

        assert api.request.await_args.args == ("GET", f"/knowledge-gaps/{TOPIC}/draft/estimate")
        assert estimate == {"total_usd": None}

    async def test_a_draft_is_asked_for_and_read_back_as_its_state(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = AsyncMock(
            return_value={
                "id": TOPIC,
                "label": "Do you ship to Germany?",
                "knowledge_base_name": "Help center",
                "drafting": True,
                "draft_failed": False,
                "draft_stale": False,
                "questions": [{"question": "a person's words"}],
            }
        )

        topic = await _call(server, "draft_knowledge_topic", topic_id=TOPIC)

        assert api.request.await_args.args == ("POST", f"/knowledge-gaps/{TOPIC}/draft")
        assert topic["drafting"] is True
        assert "questions" not in topic


READS = {
    "list_improvements",
    "get_improvement",
    "estimate_improvement",
    "estimate_improve_again",
    "list_datasets",
    "get_eval_run",
    "estimate_knowledge_draft",
    "estimate_next_improvement_step",
}
WRITES = {
    "start_improvement",
    "use_attempt",
    "accept_improvement",
    "end_improvement",
    "improve_again",
    "draft_knowledge_topic",
    "run_next_improvement_step",
}


@pytest.mark.security
def test_the_reads_never_wait_for_approval() -> None:
    catalog = {tool.name: tool for tool in platform_tool_catalog()}
    assert all(not catalog[name].writes and not catalog[name].held for name in READS)


@pytest.mark.security
def test_every_write_waits_for_the_person_s_approval() -> None:
    """Starting, choosing, accepting, publishing and ending all reach a card first: none is
    ungated, so no binding's policy lets one through unseen."""
    catalog = {tool.name: tool for tool in platform_tool_catalog()}
    assert all(catalog[name].writes and not catalog[name].ungated for name in WRITES)


PATHS = [
    ("GET", f"/agents/{AGENT}/improvements"),
    ("GET", f"/agents/{AGENT}/improvements/{SESSION}"),
    ("GET", f"/agents/{AGENT}/improvements/{SESSION}/evidence"),
    ("POST", f"/agents/{AGENT}/improvements/estimate"),
    ("POST", f"/agents/{AGENT}/improvements"),
    ("POST", f"/agents/{AGENT}/improvements/{SESSION}/rounds/2/select"),
    ("POST", f"/agents/{AGENT}/improvements/{SESSION}/finish"),
    ("POST", f"/agents/{AGENT}/improvements/{SESSION}/cancel"),
    ("POST", f"/agents/{AGENT}/improvements/{SESSION}/discard"),
    ("POST", f"/agents/{AGENT}/improvements/{SESSION}/continue/estimate"),
    ("POST", f"/agents/{AGENT}/improvements/{SESSION}/continue"),
    ("GET", f"/knowledge-gaps/agents/{AGENT}"),
    ("GET", f"/agents/{AGENT}"),
    ("GET", f"/agents/{AGENT}/versions"),
    ("GET", f"/agents/{AGENT}/versions/{SESSION}"),
    ("GET", "/improvements"),
    ("GET", "/agents"),
    ("GET", "/datasets"),
    ("GET", f"/eval-runs/{RUN}"),
    ("GET", f"/eval-runs/{RUN}/comparison"),
    ("GET", f"/eval-runs/{RUN}/cases"),
    ("GET", f"/improvements/{SESSION}"),
    ("GET", f"/knowledge-gaps/{TOPIC}/draft/estimate"),
    ("POST", f"/knowledge-gaps/{TOPIC}/draft"),
]


@pytest.mark.parametrize(("method", "path"), PATHS)
def test_every_route_the_improve_tools_call_admits_the_tools_key(method: str, path: str) -> None:
    from tests.test_platform_mcp_tools import _reachable

    assert _reachable(method, path), f"no public or assistant route answers {method} {path}"
