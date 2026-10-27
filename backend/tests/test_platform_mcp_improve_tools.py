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


def test_the_reads_never_wait_for_approval() -> None:
    reads = {
        "list_improvements",
        "get_improvement",
        "estimate_improvement",
        "list_datasets",
        "get_eval_run",
    }
    catalog = {tool.name: tool for tool in platform_tool_catalog()}
    assert all(not catalog[name].writes and not catalog[name].held for name in reads)
