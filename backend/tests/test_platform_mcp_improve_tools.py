"""The Architect's Improve and eval tools: the wizard's own routes, read back compactly."""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP

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


def _responder(responses: dict[tuple[str, str], Any]) -> AsyncMock:
    async def respond(method: str, path: str, **_: Any) -> Any:
        return responses[(method, path)]

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
                ("GET", f"/agents/{AGENT}/improvements/{SESSION}"): SESSION_READ,
                ("GET", "/me/permissions"): _permissions("agents:view"),
            }
        )

        session = await _call(server, "get_improvement", agent_id=AGENT, session_id=SESSION)

        assert [a["attempt"] for a in session["attempts"]] == [1, 2]
        best = session["attempts"][1]
        assert best == {
            "attempt": 2,
            "verdict": "better",
            "fixed": 3,
            "broken": 0,
            "held_out_pass_rate": {"before": 0.5, "after": 0.8},
            "cost_usd": "0.02",
            "best": True,
        }
        assert not session["attempts"][0]["best"]
        assert session["link"] == improvement_link(AGENT, SESSION)

    async def test_knowledge_topics_are_read_only_with_runs_view(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        """The topics quote what people asked: a reader without `runs:view` gets none, and
        the evidence route is never called on their behalf."""
        api.request = _responder(
            {
                ("GET", f"/agents/{AGENT}/improvements/{SESSION}"): SESSION_READ,
                ("GET", "/me/permissions"): _permissions("agents:view"),
            }
        )

        session = await _call(server, "get_improvement", agent_id=AGENT, session_id=SESSION)

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
                ("GET", f"/agents/{AGENT}/improvements/{SESSION}"): SESSION_READ,
                ("GET", "/me/permissions"): _permissions("agents:view", "runs:view"),
                ("GET", f"/agents/{AGENT}/improvements/{SESSION}/evidence"): {
                    "items": [{"topic_id": TOPIC}, {"topic_id": OTHER_TOPIC}, {"topic_id": None}]
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

        session = await _call(server, "get_improvement", agent_id=AGENT, session_id=SESSION)

        assert session["missing_knowledge"] == [
            {
                "topic_id": TOPIC,
                "label": "Do you ship to Germany?",
                "knowledge_base": "Help center",
                "has_draft": True,
                "draft_stale": True,
                "not_now": False,
            },
            {
                "topic_id": OTHER_TOPIC,
                "label": "Gift cards?",
                "knowledge_base": "Help center",
                "has_draft": True,
                "draft_stale": True,
                "not_now": True,
            },
        ]


class TestEstimatingAndDatasets:
    async def test_an_estimate_names_one_target(self, server: FastMCP, api: MagicMock) -> None:
        api.request = AsyncMock(return_value={"total_usd": "0.04"})

        await _call(server, "estimate_improvement", agent_id=AGENT, dataset_id=DATASET)

        assert api.request.await_args.args == ("POST", f"/agents/{AGENT}/improvements/estimate")
        assert api.request.await_args.kwargs == {
            "json": {"max_iterations": 3, "dataset_id": str(DATASET)}
        }

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

    async def test_a_run_names_a_few_broken_and_fixed_questions(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        cases = [
            {"case_id": str(uuid.uuid4()), "input": "x" * 500, "flip": "fixed", "confirmed": True}
            for _ in range(7)
        ] + [
            {
                "case_id": str(uuid.uuid4()),
                "input": "Canada?",
                "flip": "regression",
                "confirmed": False,
            },
            {
                "case_id": str(uuid.uuid4()),
                "input": "Same",
                "flip": "unchanged",
                "confirmed": False,
            },
        ]
        api.request = _responder(
            {
                ("GET", f"/eval-runs/{RUN}"): self.RUN_READ,
                ("GET", f"/eval-runs/{RUN}/comparison"): {"cases": cases},
            }
        )

        run = await _call(server, "get_eval_run", run_id=RUN)

        assert run["verdict"] == "mixed"
        assert run["pass_rate"] == {"baseline": 0.5, "candidate": 0.7}
        assert [case["input"] for case in run["broken"]] == ["Canada?"]
        assert len(run["fixed"]) == 5
        assert all(len(case["input"]) == 200 for case in run["fixed"])

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
        api.request = AsyncMock(return_value=SESSION_READ)

        started = await _call(
            server, "start_improvement", agent_id=AGENT, budget_usd="0.04", suite_id=DATASET
        )

        assert api.request.await_args.args == ("POST", f"/agents/{AGENT}/improvements")
        assert api.request.await_args.kwargs == {
            "json": {"max_iterations": 3, "budget_usd": "0.04", "suite_id": str(DATASET)}
        }
        assert started["link"] == improvement_link(AGENT, SESSION)

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


READS = {
    "list_improvements",
    "get_improvement",
    "estimate_improvement",
    "estimate_improve_again",
    "list_datasets",
    "get_eval_run",
}
WRITES = {
    "start_improvement",
    "use_attempt",
    "accept_improvement",
    "end_improvement",
    "improve_again",
}


def test_the_reads_never_wait_for_approval() -> None:
    catalog = {tool.name: tool for tool in platform_tool_catalog()}
    assert all(not catalog[name].writes and not catalog[name].held for name in READS)


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
    ("GET", "/datasets"),
    ("GET", f"/eval-runs/{RUN}"),
    ("GET", f"/eval-runs/{RUN}/comparison"),
]


@pytest.mark.parametrize(("method", "path"), PATHS)
def test_every_route_the_improve_tools_call_admits_the_tools_key(method: str, path: str) -> None:
    from tests.test_platform_mcp_tools import _reachable

    assert _reachable(method, path), f"no public or assistant route answers {method} {path}"
