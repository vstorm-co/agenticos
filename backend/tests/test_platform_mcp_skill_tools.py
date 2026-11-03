"""The Architect's skill tools: a skill's agents and versions, and improving a skill line."""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from app.services.platform_mcp import platform_tool_catalog
from app.services.platform_mcp._tools import platform_tools, skill_improvement_link, skill_link

pytestmark = pytest.mark.anyio

SKILL = uuid.UUID("00000000-0000-4000-8000-0000000005a1")
FORK = "00000000-0000-4000-8000-0000000005f1"
SESSION = uuid.UUID("00000000-0000-4000-8000-0000000005d1")
ONLINE = "00000000-0000-4000-8000-0000000005b1"
COUNTER = "00000000-0000-4000-8000-0000000005b2"
WHOLESALE = "00000000-0000-4000-8000-0000000005b3"
VERSION = "00000000-0000-4000-8000-0000000005c1"
BASE = f"/skills/{SKILL}"
SESSIONS = f"{BASE}/improvements"
SESSION_PATH = f"{SESSIONS}/{SESSION}"


def _agent(agent_id: str, name: str) -> dict[str, Any]:
    return {"id": agent_id, "name": name, "slug": name.lower(), "has_avatar": False}


def _usage(agent_id: str, name: str, binding: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "agent": _agent(agent_id, name),
        "via_specialist": None,
        "draft_only": False,
        "binding": binding,
        "agent_version": 3,
        "environments": [],
        "draft_differs": False,
        "can_change": True,
        "can_publish": True,
        "checked": None,
        **extra,
    }


MAIN = {"state": "main", "version": {"id": VERSION, "number": 3}, "fork": None, "behind_main": 0}
PINNED = {
    "state": "pinned",
    "version": {"id": VERSION, "number": 1},
    "fork": None,
    "behind_main": 2,
}
ON_FORK = {
    "state": "fork",
    "version": {"id": VERSION, "number": 2},
    "fork": {"id": FORK, "name": "Wholesale", "base_number": 1, "changes": 1},
    "behind_main": 2,
}
FORK_READ = {
    "id": FORK,
    "skill_id": str(SKILL),
    "name": "Wholesale",
    "base": {"id": VERSION, "number": 1},
    "latest": {"id": VERSION, "number": 2},
    "changes": 1,
    "behind_main": 2,
    "agents": 1,
    "archive_candidate": False,
}


def _checked(agent_id: str, name: str, state: str, **row: Any) -> dict[str, Any]:
    return {
        "agent": {"id": agent_id, "name": name},
        "state": state,
        "unknown_reason": None,
        "sample": "own_questions",
        "stages": [],
        "fixed": 0,
        "broken": 0,
        "held_out": 8,
        "fixed_confirmed": 0,
        "regressions_confirmed": 0,
        "noisy": False,
        "expected_usd": "0.01",
        "at_most_usd": "0.02",
        **row,
    }


BLOCKED = {
    "verdict": "blocked",
    "warnings": [],
    "agents": [
        _checked(ONLINE, "Online returns desk", "better", fixed=8),
        _checked(COUNTER, "Gift shop counter", "worse", broken=8, regressions_confirmed=8),
    ],
    "hidden": 0,
    "hidden_unknown": 0,
    "outcomes": ["improve_further", "apply_and_pin", "fork_for_helped", "discard"],
}


def _session(status: str = "ready", **fields: Any) -> dict[str, Any]:
    return {
        "id": str(SESSION),
        "skill_id": str(SKILL),
        "fork_id": None,
        "line_name": "main",
        "base_version": {"id": VERSION, "number": 1},
        "status": status,
        "stage": "judging",
        "iteration": 1,
        "max_iterations": 3,
        "next_step": None,
        "spent_usd": "0.04",
        "budget_usd": "1.00",
        "stop_reason": None,
        "expires_at": "2026-11-09T08:00:00Z",
        "created_at": "2026-11-02T08:00:00Z",
        "check": BLOCKED if status == "ready" else None,
        "outcomes": BLOCKED["outcomes"] if status == "ready" else [],
        "outcome": None,
        "applied_version_id": None,
        "try_again_blocked": None,
        "can_discard": True,
        **fields,
    }


QUOTE = {
    "total_usd": "0.05",
    "expected_usd": "0.02",
    "budget_usd": "1.00",
    "affordable": True,
    "candidate_hash": "c" * 64,
}
EVIDENCE = {
    "problems": [{"title": "Order numbers are not taken as receipts"}],
    "not_the_skill": 2,
    "not_a_problem": 1,
}


def _responder(responses: dict[tuple[str, str], Any]) -> AsyncMock:
    async def respond(method: str, path: str, **_: Any) -> Any:
        answer = responses[(method, path)]
        if isinstance(answer, Exception):
            raise answer
        return answer

    return AsyncMock(side_effect=respond)


@pytest.fixture
def api() -> MagicMock:
    api = MagicMock()
    api.refuse = MagicMock(side_effect=ToolError("refused"))
    return api


@pytest.fixture
def server(api: MagicMock) -> FastMCP:
    server = FastMCP(name="test")
    for tool in platform_tools(api):
        server.tool(tool.function)
    return server


async def _call(server: FastMCP, tool: str, **arguments: Any) -> Any:
    sent = {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in arguments.items()}
    result = await server.call_tool(tool, sent)
    return result.structured_content


def _sent(api: MagicMock, method: str, path: str) -> dict[str, Any]:
    """The JSON body of the one call to `method path`."""
    [call] = [c for c in api.request.await_args_list if c.args == (method, path)]
    return call.kwargs.get("json") or call.kwargs.get("params") or {}


class TestReadingASkill:
    async def test_each_agent_reads_as_the_skill_page_writes_its_version(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                ("GET", BASE): {
                    "id": str(SKILL),
                    "name": "returns-policy",
                    "description": "d",
                    "can_edit": True,
                },
                ("GET", f"{BASE}/forks"): {"items": [FORK_READ], "total": 1},
                ("GET", f"{BASE}/agents"): {
                    "main_latest": {"id": VERSION, "number": 3},
                    "items": [
                        _usage(
                            ONLINE,
                            "Online returns desk",
                            MAIN,
                            checked={"state": "better", "check_id": "x"},
                        ),
                        _usage(
                            COUNTER, "Gift shop counter", PINNED, environments=[{"name": "Staging"}]
                        ),
                        _usage(WHOLESALE, "Wholesale desk", ON_FORK),
                        _usage(WHOLESALE, "Draft desk", MAIN, draft_only=True),
                    ],
                    "hidden": 2,
                },
            }
        )

        skill = await _call(server, "get_skill", skill_id=SKILL)

        assert [agent["uses"] for agent in skill["agents"]] == [
            "v3 · main",
            "v1 · pinned · 2 behind main",
            'Fork "Wholesale" · from v1 · 1 change · 2 behind main',
        ]
        assert [agent["checked"] for agent in skill["agents"]] == ["better", "unknown", "unknown"]
        assert skill["agents"][1]["other_environments"] == ["Staging"]
        assert skill["agents"][2]["fork_id"] == FORK
        assert skill["only_in_drafts"] == ["Draft desk"]
        assert skill["hidden_agents"] == 2
        assert skill["main_version"] == 3
        assert skill["forks"] == [
            {
                "fork_id": FORK,
                "name": "Wholesale",
                "from_version": 1,
                "changes": 1,
                "behind_main": 2,
                "agents": 1,
                "archive_candidate": False,
            }
        ]
        assert skill["link"] == skill_link(SKILL)

    async def test_a_fork_with_several_changes_says_so(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        caught_up = {**ON_FORK, "behind_main": 0, "fork": {**ON_FORK["fork"], "changes": 3}}
        api.request = _responder(
            {
                ("GET", BASE): {"id": str(SKILL), "name": "r", "description": "d"},
                ("GET", f"{BASE}/forks"): {"items": [], "total": 0},
                ("GET", f"{BASE}/agents"): {
                    "main_latest": {"id": VERSION, "number": 3},
                    "items": [_usage(WHOLESALE, "Wholesale desk", caught_up)],
                    "hidden": 0,
                },
            }
        )

        skill = await _call(server, "get_skill", skill_id=SKILL)

        assert skill["agents"][0]["uses"] == 'Fork "Wholesale" · from v1 · 3 changes'
        assert skill["can_edit"] is False

    @pytest.mark.parametrize(
        ("fork_id", "params"), [(None, {"limit": 20}), (FORK, {"limit": 20, "fork_id": FORK})]
    )
    async def test_a_line_s_history_names_what_made_each_version(
        self, server: FastMCP, api: MagicMock, fork_id: str | None, params: dict[str, Any]
    ) -> None:
        restored = {
            "id": VERSION,
            "number": 4,
            "source": "restore",
            "restored_from": {"number": 2},
            "created_by": {"name": "Bartek"},
            "created_at": "2026-11-02T08:00:00Z",
            "agents": 2,
        }
        synced = {
            **restored,
            "number": 3,
            "source": "library",
            "restored_from": None,
            "created_by": None,
        }
        api.request = _responder(
            {("GET", f"{BASE}/versions"): {"items": [restored, synced], "total": 4}}
        )

        history = await _call(server, "list_skill_versions", skill_id=SKILL, fork_id=fork_id)

        assert _sent(api, "GET", f"{BASE}/versions") == params
        assert [
            (v["number"], v["source"], v["restored_from"], v["created_by"])
            for v in history["items"]
        ] == [(4, "restore", 2, "Bartek"), (3, "library", None, None)]
        assert history["total"] == 4

    async def test_one_version_reads_with_its_text_and_file_names(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                ("GET", f"{BASE}/versions/{VERSION}"): {
                    "number": 2,
                    "fork_id": FORK,
                    "source": "improve",
                    "description": "d",
                    "content": "body",
                    "resources": [{"name": "form.md", "digest": "x"}],
                }
            }
        )

        version = await _call(server, "get_skill_version", skill_id=SKILL, version_id=VERSION)

        assert version == {
            "number": 2,
            "fork_id": FORK,
            "source": "improve",
            "description": "d",
            "content": "body",
            "files": ["form.md"],
        }


class TestReadingSessions:
    async def test_without_a_skill_it_lists_the_sessions_waiting_for_a_person(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                ("GET", "/skill-improvements/awaiting"): [
                    {"id": str(SESSION), "skill_id": str(SKILL), "skill_name": "returns-policy"}
                ]
            }
        )

        listed = await _call(server, "list_skill_improvements")

        assert listed["waiting"][0]["link"] == skill_improvement_link(SKILL, SESSION)

    async def test_the_newest_session_carries_its_summary_and_earlier_ones_are_counted(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        older = {
            **_session("cancelled"),
            "id": str(uuid.uuid4()),
            "created_at": "2026-11-01T08:00:00Z",
        }
        waiting = _session("waiting", next_step="propose")
        api.request = _responder(
            {
                ("GET", SESSIONS): [older, waiting],
                ("POST", f"{SESSION_PATH}/continue/estimate"): QUOTE,
            }
        )

        listed = await _call(server, "list_skill_improvements", skill_id=SKILL)

        [newest] = listed["items"]
        assert listed["earlier_sessions"] == 1
        assert newest["waiting_for"] == {
            "after": "Understand",
            "next_step": "propose changes",
            "price": {k: QUOTE[k] for k in QUOTE},
        }
        assert newest["summary"] == (
            "Improving the main line, started from v1. It stopped after Understand; next it "
            "will propose changes."
        )
        assert newest["next_actions"] == ["Next step: propose changes", "End the session"]
        assert newest["ask"]["questions"][0]["options"][0] == {
            "label": "Next step: propose changes"
        }

    async def test_history_lists_every_session_and_an_unwaiting_one_is_not_priced(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder({("GET", SESSIONS): [_session("running", stage="proposing")]})

        listed = await _call(server, "list_skill_improvements", skill_id=SKILL, history=True)

        [item] = listed["items"]
        assert item["next_actions"] == ["Stop the session"]
        assert item["summary"].endswith("It is working (proposing).")
        assert "earlier_sessions" not in listed

    async def test_a_skill_with_no_sessions_lists_none(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder({("GET", SESSIONS): []})

        assert await _call(server, "list_skill_improvements", skill_id=SKILL) == {
            "items": [],
            "earlier_sessions": 0,
        }

    async def test_a_check_with_a_worse_agent_offers_pinning_it_or_a_fork_for_the_others(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {("GET", SESSION_PATH): _session(), ("GET", f"{SESSION_PATH}/evidence"): EVIDENCE}
        )

        session = await _call(server, "get_skill_improvement", skill_id=SKILL, session_id=SESSION)

        assert session["next_actions"] == [
            "Apply to main and keep Gift shop counter on v1",
            "Make a fork for Online returns desk",
            "Improve further (attempt 2 of 3)",
            "End the session",
        ]
        assert "Gift shop counter worse" in session["summary"]
        assert "An agent got worse, so it cannot simply be applied" in session["summary"]
        assert session["check"]["agents"][1] == {
            "name": "Gift shop counter",
            "state": "worse",
            "why_unknown": None,
            "sample": "own_questions",
            "fixed": 0,
            "broken": 8,
            "broken_confirmed": 8,
            "held_out": 8,
            "noisy": False,
            "expected_usd": "0.01",
            "at_most_usd": "0.02",
        }
        assert session["found"] == {
            "problems": ["Order numbers are not taken as receipts"],
            "not_the_skill": 2,
            "not_a_problem": 1,
        }
        assert session["waiting_for"] is None

    async def test_unchecked_agents_are_named_with_why_and_hidden_ones_only_counted(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        check = {
            **BLOCKED,
            "verdict": "needs_ack",
            "warnings": ["within_noise"],
            "agents": [
                _checked(ONLINE, "Online returns desk", "better", fixed=8),
                _checked(WHOLESALE, "Wholesale desk", "unknown", unknown_reason="no_questions"),
            ],
            "hidden": 3,
            "hidden_unknown": 1,
            "outcomes": ["apply", "discard"],
        }
        api.request = _responder(
            {
                ("GET", SESSION_PATH): _session(check=check, outcomes=check["outcomes"]),
                ("GET", f"{SESSION_PATH}/evidence"): EVIDENCE,
            }
        )

        session = await _call(server, "get_skill_improvement", skill_id=SKILL, session_id=SESSION)

        assert "Wholesale desk unknown (no_questions)" in session["summary"]
        assert "3 more agents use it that you cannot see." in session["summary"]
        assert "acknowledges them before it is applied" in session["summary"]
        assert "within noise" in session["summary"]
        assert session["check"]["hidden_unknown"] == 1
        assert session["next_actions"] == ["Apply to main", "End the session"]

    async def test_a_fork_line_applies_to_the_fork_and_an_exhausted_one_cannot_go_further(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        check = {**BLOCKED, "verdict": "passed", "outcomes": ["apply", "improve_further"]}
        session = _session(
            fork_id=FORK,
            line_name="Wholesale",
            check=check,
            outcomes=check["outcomes"],
            try_again_blocked={"reason": "last_attempt"},
            can_discard=False,
        )
        api.request = _responder(
            {("GET", SESSION_PATH): session, ("GET", f"{SESSION_PATH}/evidence"): EVIDENCE}
        )

        read = await _call(server, "get_skill_improvement", skill_id=SKILL, session_id=SESSION)

        assert read["next_actions"] == ['Apply to the fork "Wholesale"']
        assert read["ask"]["questions"][0]["options"] == [
            {"label": 'Apply to the fork "Wholesale"'},
            {"label": "Not now"},
        ]
        assert read["summary"].startswith("Improving the Wholesale line, started from v1.")
        assert "so it can be applied" in read["summary"]

    async def test_a_check_still_without_a_verdict_lists_its_agents_and_judges_nothing(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        check = {**BLOCKED, "verdict": None, "outcomes": []}
        api.request = _responder(
            {
                ("GET", SESSION_PATH): _session(check=check, outcomes=[]),
                ("GET", f"{SESSION_PATH}/evidence"): EVIDENCE,
            }
        )

        read = await _call(server, "get_skill_improvement", skill_id=SKILL, session_id=SESSION)

        assert read["summary"].endswith(
            "The check: Online returns desk better, Gift shop counter worse."
        )
        assert read["next_actions"] == ["End the session"]

    async def test_a_stale_result_is_checked_again_before_anything_is_applied(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                ("GET", SESSION_PATH): _session(stale=True),
                ("GET", f"{SESSION_PATH}/evidence"): EVIDENCE,
            }
        )

        session = await _call(server, "get_skill_improvement", skill_id=SKILL, session_id=SESSION)

        assert session["stale"] is True
        assert session["next_actions"] == [
            "Check again on the line as it is now",
            "End the session",
        ]
        assert "moved on since this session read it" in session["summary"]

    async def test_checking_again_is_priced_and_run_on_its_own_routes(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                ("GET", SESSION_PATH): _session(stale=True),
                ("POST", f"{SESSION_PATH}/recheck/estimate"): {**QUOTE, "check_estimate": None},
                ("POST", f"{SESSION_PATH}/recheck"): _session("running", stage="evaluating"),
            }
        )

        quote = await _call(
            server,
            "estimate_next_skill_improvement_step",
            skill_id=SKILL,
            session_id=SESSION,
            recheck=True,
        )
        moved = await _call(
            server,
            "run_next_skill_improvement_step",
            skill_id=SKILL,
            session_id=SESSION,
            budget_usd="1",
            estimate_usd=quote["total_usd"],
            candidate_hash=quote["candidate_hash"],
            recheck=True,
        )

        assert _sent(api, "POST", f"{SESSION_PATH}/recheck")["candidate_hash"] == "c" * 64
        assert moved["status"] == "running"

    async def test_a_waiting_session_whose_step_cannot_be_priced_says_why(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                ("GET", SESSION_PATH): _session("waiting", next_step="check"),
                ("GET", f"{SESSION_PATH}/evidence"): EVIDENCE,
                ("POST", f"{SESSION_PATH}/continue/estimate"): ToolError(
                    "400 BUDGET: The org has $0.01 left"
                ),
            }
        )

        session = await _call(server, "get_skill_improvement", skill_id=SKILL, session_id=SESSION)

        assert session["waiting_for"]["price"] == {"unavailable": "The org has $0.01 left"}

    @pytest.mark.parametrize(
        ("status", "fields", "sentence", "actions"),
        [
            ("accepted", {"outcome": "applied_pinned"}, "It is accepted.", []),
            (
                "stopped",
                {"stop_reason": "no_data"},
                "There were no rated answers",
                ["End the session"],
            ),
            ("failed", {}, "started from v1.", ["Retry this step", "End the session"]),
        ],
    )
    async def test_a_stopped_or_decided_session_says_where_it_stands(
        self,
        server: FastMCP,
        api: MagicMock,
        status: str,
        fields: dict[str, Any],
        sentence: str,
        actions: list[str],
    ) -> None:
        api.request = _responder({("GET", SESSION_PATH): _session(status, **fields)})

        session = await _call(server, "get_skill_improvement", skill_id=SKILL, session_id=SESSION)

        assert sentence in session["summary"]
        assert session["next_actions"] == actions
        assert session["closed"] is (status == "accepted")


class TestStartingAndSteps:
    @pytest.mark.parametrize(
        ("arguments", "sent"),
        [
            ({}, {"fork_id": None, "max_iterations": 3}),
            (
                {"fork_id": FORK, "from_run": str(SESSION)},
                {"fork_id": FORK, "max_iterations": 3, "from_run": str(SESSION)},
            ),
        ],
    )
    async def test_the_estimate_names_the_line_and_a_limit_for_the_whole_session(
        self, server: FastMCP, api: MagicMock, arguments: dict[str, Any], sent: dict[str, Any]
    ) -> None:
        api.request = _responder(
            {
                ("POST", f"{SESSIONS}/estimate"): {
                    "total_usd": "0.012",
                    "per_round_usd": "0.05",
                    "max_iterations": 3,
                }
            }
        )

        estimate = await _call(server, "estimate_skill_improvement", skill_id=SKILL, **arguments)

        assert _sent(api, "POST", f"{SESSIONS}/estimate") == sent
        assert estimate["limit_usd"] == "0.17"

    async def test_a_second_open_session_on_the_same_line_is_refused_with_a_link(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder({("GET", SESSIONS): [_session("waiting")]})

        with pytest.raises(ToolError):
            await _call(server, "start_skill_improvement", skill_id=SKILL, budget_usd="1")

        [message] = api.refuse.call_args.args
        assert skill_improvement_link(SKILL, SESSION) in message
        assert ("POST", SESSIONS) not in [c.args for c in api.request.await_args_list]

    async def test_a_session_open_on_another_line_does_not_stop_one_on_a_fork(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                ("GET", SESSIONS): [_session("waiting")],
                ("POST", SESSIONS): _session("queued", fork_id=FORK, line_name="Wholesale"),
            }
        )

        started = await _call(
            server,
            "start_skill_improvement",
            skill_id=SKILL,
            budget_usd="1.5",
            fork_id=FORK,
            from_run=str(SESSION),
        )

        assert _sent(api, "POST", SESSIONS) == {
            "fork_id": FORK,
            "budget_usd": "1.5",
            "max_iterations": 3,
            "from_run": str(SESSION),
        }
        assert started["line"] == "Wholesale"
        assert started["link"] == skill_improvement_link(SKILL, SESSION)

    async def test_main_starts_beside_a_fork_s_open_session(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        on_fork = _session("waiting", fork_id=FORK, line_name="Wholesale")
        api.request = _responder(
            {("GET", SESSIONS): [on_fork], ("POST", SESSIONS): _session("queued")}
        )

        started = await _call(server, "start_skill_improvement", skill_id=SKILL, budget_usd="1")

        assert _sent(api, "POST", SESSIONS) == {
            "fork_id": None,
            "budget_usd": "1",
            "max_iterations": 3,
        }
        assert started["line"] == "main"

    async def test_the_step_estimate_names_who_the_check_runs_and_who_it_cannot(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        check = {
            "agents": [
                _checked(WHOLESALE, "Wholesale desk", "unknown", unknown_reason="no_budget")
            ],
            "hidden": 1,
        }
        api.request = _responder(
            {
                ("GET", SESSION_PATH): _session("waiting", next_step="check"),
                ("POST", f"{SESSION_PATH}/continue/estimate"): {**QUOTE, "check_estimate": check},
            }
        )

        estimate = await _call(
            server,
            "estimate_next_skill_improvement_step",
            skill_id=SKILL,
            session_id=SESSION,
            thorough=True,
        )

        assert _sent(api, "POST", f"{SESSION_PATH}/continue/estimate") == {"mode": "thorough"}
        assert estimate["agents"][0]["why_unknown"] == "no_budget"
        assert estimate["hidden_agents"] == 1
        assert estimate["waiting_for"]["next_step"] == "test the changes"
        assert "check_estimate" not in estimate

    async def test_the_step_estimate_before_a_proposal_has_no_check(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                ("GET", SESSION_PATH): _session("waiting", next_step="propose"),
                ("POST", f"{SESSION_PATH}/continue/estimate"): {**QUOTE, "check_estimate": None},
            }
        )

        estimate = await _call(
            server, "estimate_next_skill_improvement_step", skill_id=SKILL, session_id=SESSION
        )

        assert _sent(api, "POST", f"{SESSION_PATH}/continue/estimate") == {}
        assert estimate["agents"] is None
        assert estimate["hidden_agents"] == 0

    @pytest.mark.parametrize(
        ("extra", "sent"),
        [
            ({}, {}),
            (
                {"note": "Keep store credit for the counter", "thorough": True},
                {"note": "Keep store credit for the counter", "mode": "thorough"},
            ),
        ],
    )
    async def test_a_step_runs_with_the_priced_consent_and_the_person_s_note(
        self, server: FastMCP, api: MagicMock, extra: dict[str, Any], sent: dict[str, Any]
    ) -> None:
        api.request = _responder(
            {("POST", f"{SESSION_PATH}/continue"): _session("running", stage="proposing")}
        )

        moved = await _call(
            server,
            "run_next_skill_improvement_step",
            skill_id=SKILL,
            session_id=SESSION,
            budget_usd="1",
            estimate_usd="0.05",
            candidate_hash="c" * 64,
            **extra,
        )

        assert _sent(api, "POST", f"{SESSION_PATH}/continue") == {
            "confirmed": True,
            "budget_usd": "1",
            "estimate_usd": "0.05",
            "candidate_hash": "c" * 64,
            **sent,
        }
        assert moved["status"] == "running"


class TestDeciding:
    @pytest.mark.parametrize(("outcome", "pin"), [("apply", False), ("apply_and_pin", True)])
    async def test_applying_pins_the_worse_agents_only_when_asked(
        self, server: FastMCP, api: MagicMock, outcome: str, pin: bool
    ) -> None:
        api.request = _responder(
            {
                ("POST", f"{SESSION_PATH}/apply"): {
                    "session": _session("accepted"),
                    "version_id": VERSION,
                    "version": 2,
                    "pinned": [{"id": COUNTER, "name": "Gift shop counter"}] if pin else [],
                }
            }
        )

        applied = await _call(
            server, "accept_skill_improvement", skill_id=SKILL, session_id=SESSION, outcome=outcome
        )

        assert _sent(api, "POST", f"{SESSION_PATH}/apply") == {
            "confirmed": True,
            "acknowledge_unknown": False,
            "pin_worse": pin,
        }
        assert applied["version"] == 2
        assert applied["pinned"] == (["Gift shop counter"] if pin else [])

    async def test_a_fork_for_the_helped_agents_needs_a_name(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = AsyncMock()

        with pytest.raises(ToolError):
            await _call(
                server,
                "accept_skill_improvement",
                skill_id=SKILL,
                session_id=SESSION,
                outcome="fork_for_helped",
            )

        api.request.assert_not_awaited()

    async def test_a_fork_for_the_helped_agents_moves_them_and_leaves_main(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                ("POST", f"{SESSION_PATH}/fork"): {
                    "session": _session("accepted"),
                    "fork": FORK_READ,
                    "moved": [{"id": ONLINE, "name": "Online returns desk"}],
                    "draft_only": [{"id": WHOLESALE, "name": "Draft desk"}],
                }
            }
        )

        forked = await _call(
            server,
            "accept_skill_improvement",
            skill_id=SKILL,
            session_id=SESSION,
            outcome="fork_for_helped",
            fork_name="Online",
            acknowledge_unknown=True,
        )

        assert _sent(api, "POST", f"{SESSION_PATH}/fork") == {
            "confirmed": True,
            "name": "Online",
            "acknowledge_unknown": True,
        }
        assert forked["moved"] == ["Online returns desk"]
        assert forked["only_in_drafts"] == ["Draft desk"]
        assert forked["fork"]["name"] == "Wholesale"

    @pytest.mark.parametrize(("status", "route"), [("running", "cancel"), ("ready", "discard")])
    async def test_ending_stops_a_running_session_and_discards_any_other(
        self, server: FastMCP, api: MagicMock, status: str, route: str
    ) -> None:
        api.request = _responder(
            {
                ("GET", SESSION_PATH): _session(status),
                ("POST", f"{SESSION_PATH}/{route}"): _session("cancelled"),
            }
        )

        ended = await _call(server, "end_skill_improvement", skill_id=SKILL, session_id=SESSION)

        assert ended["status"] == "cancelled"


class TestChangingAVersion:
    @pytest.mark.parametrize(
        ("arguments", "sent"),
        [
            ({"state": "main"}, {"state": "main"}),
            ({"state": "pinned", "version": 1}, {"state": "pinned", "version": 1}),
            (
                {"state": "fork", "fork_id": FORK, "note": "Returns team"},
                {"state": "fork", "fork_id": FORK, "note": "Returns team"},
            ),
        ],
    )
    async def test_an_agent_moves_to_the_version_named(
        self, server: FastMCP, api: MagicMock, arguments: dict[str, Any], sent: dict[str, Any]
    ) -> None:
        path = f"{BASE}/agents/{COUNTER}/binding"
        api.request = _responder(
            {
                ("PUT", path): {
                    "published": True,
                    "agent_version": 4,
                    "environments": ["Production"],
                    "usage": _usage(COUNTER, "Gift shop counter", PINNED),
                }
            }
        )

        moved = await _call(
            server, "change_skill_version", skill_id=SKILL, agent_id=COUNTER, **arguments
        )

        assert _sent(api, "PUT", path) == sent
        assert moved["agent"]["uses"] == "v1 · pinned · 2 behind main"
        assert moved["environments"] == ["Production"]

    async def test_a_change_without_publish_lands_in_the_draft_and_may_leave_no_row(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                ("PUT", f"{BASE}/agents/{COUNTER}/binding"): {
                    "published": False,
                    "agent_version": None,
                    "environments": [],
                    "usage": None,
                }
            }
        )

        moved = await _call(
            server, "change_skill_version", skill_id=SKILL, agent_id=COUNTER, state="main"
        )

        assert moved["published"] is False
        assert moved["agent"] is None

    @pytest.mark.parametrize("arguments", [{"state": "pinned"}, {"state": "fork"}])
    async def test_a_pin_without_a_version_or_a_fork_without_an_id_is_refused_unsent(
        self, server: FastMCP, api: MagicMock, arguments: dict[str, Any]
    ) -> None:
        api.request = AsyncMock()

        with pytest.raises(ToolError):
            await _call(
                server, "change_skill_version", skill_id=SKILL, agent_id=COUNTER, **arguments
            )

        api.request.assert_not_awaited()

    async def test_another_organization_s_skill_is_refused_not_answered_with_nothing(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder(
            {
                ("PUT", f"{BASE}/agents/{COUNTER}/binding"): ToolError(
                    "404 NOT_FOUND: Skill not found"
                )
            }
        )

        with pytest.raises(ToolError, match="NOT_FOUND"):
            await _call(
                server, "change_skill_version", skill_id=SKILL, agent_id=COUNTER, state="main"
            )


CHECK_READ = {
    **BLOCKED,
    "id": "00000000-0000-4000-8000-0000000005e1",
    "status": "done",
    "verdict": "passed",
    "agents": [_checked(COUNTER, "Gift shop counter", "no_change")],
    "outcomes": ["apply", "discard"],
}
MERGE = f"{BASE}/merges/{VERSION}"


class TestCatchingUp:
    async def test_pinned_agents_and_forks_behind_main_say_how_each_catches_up(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        skill = {"id": str(SKILL), "name": "returns-policy"}
        api.request = _responder(
            {
                ("GET", "/skills/behind-main"): {
                    "items": [
                        {
                            "skill": skill,
                            "kind": "pinned",
                            "agent": _agent(COUNTER, "Gift shop counter"),
                            "fork": None,
                            "agents": 1,
                            "version": {"id": VERSION, "number": 1},
                            "main_latest": {"id": VERSION, "number": 3},
                            "behind_main": 2,
                            "can_act": True,
                        },
                        {
                            "skill": skill,
                            "kind": "fork",
                            "agent": None,
                            "fork": ON_FORK["fork"],
                            "agents": 1,
                            "version": {"id": VERSION, "number": 1},
                            "main_latest": {"id": VERSION, "number": 3},
                            "behind_main": 2,
                            "can_act": False,
                        },
                    ],
                    "hidden": 1,
                    "total": 3,
                }
            }
        )

        behind = await _call(server, "list_skills_behind_main")

        pinned, fork = behind["items"]
        assert (pinned["agent_id"], pinned["fork_id"], pinned["catch_up"]) == (
            COUNTER,
            None,
            "Update Gift shop counter to v3",
        )
        assert (fork["agent_id"], fork["fork_id"], fork["catch_up"]) == (
            None,
            FORK,
            'Catch the fork "Wholesale" up',
        )
        assert fork["can_act"] is False
        assert behind["hidden_agents"] == 1
        assert pinned["link"] == skill_link(SKILL)

    @pytest.mark.parametrize(("thorough", "mode"), [(False, "quick"), (True, "thorough")])
    async def test_an_update_check_runs_main_on_the_one_pinned_agent(
        self, server: FastMCP, api: MagicMock, thorough: bool, mode: str
    ) -> None:
        path = f"{BASE}/agents/{COUNTER}/update-check"
        api.request = _responder({("POST", path): {**CHECK_READ, "status": "running"}})

        check = await _call(
            server,
            "start_skill_update_check",
            skill_id=SKILL,
            agent_id=COUNTER,
            thorough=thorough,
        )

        assert _sent(api, "POST", path) == {"mode": mode}
        assert check["check_id"] == CHECK_READ["id"]
        assert check["agents"][0]["name"] == "Gift shop counter"

    async def test_a_check_reads_with_its_verdict_and_what_it_allows(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request = _responder({("GET", f"{BASE}/checks/{CHECK_READ['id']}"): CHECK_READ})

        check = await _call(server, "get_skill_check", skill_id=SKILL, check_id=CHECK_READ["id"])

        assert (check["verdict"], check["outcomes"]) == ("passed", ["apply", "discard"])

    @pytest.mark.parametrize(("to_main", "route"), [(False, "catch-up"), (True, "to-main")])
    async def test_a_fork_catches_up_or_moves_to_main_as_a_session(
        self, server: FastMCP, api: MagicMock, to_main: bool, route: str
    ) -> None:
        purpose = "to_main" if to_main else "catch_up"
        api.request = _responder(
            {
                ("POST", f"{BASE}/forks/{FORK}/{route}"): _session(
                    "queued",
                    purpose=purpose,
                    fork_id=FORK,
                    line_name="Wholesale",
                    merge_id=VERSION,
                )
            }
        )

        session = await _call(
            server, "start_skill_catch_up", skill_id=SKILL, fork_id=FORK, to_main=to_main
        )

        assert session["purpose"] == purpose
        assert session["merge_id"] == VERSION
        assert session["summary"].startswith(
            'Moving the fork "Wholesale" to main'
            if to_main
            else 'Catching the fork "Wholesale" up with main'
        )

    async def test_a_caught_up_result_offers_the_merge_and_dropping_the_fork(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        check = {**BLOCKED, "verdict": "passed", "outcomes": ["catch_up", "return_to_main"]}
        api.request = _responder(
            {
                ("GET", SESSION_PATH): _session(
                    purpose="catch_up",
                    fork_id=FORK,
                    line_name="Wholesale",
                    check=check,
                    outcomes=check["outcomes"],
                ),
                ("GET", f"{SESSION_PATH}/evidence"): EVIDENCE,
            }
        )

        session = await _call(server, "get_skill_improvement", skill_id=SKILL, session_id=SESSION)

        assert session["next_actions"] == [
            'Catch the fork "Wholesale" up with main',
            'Drop the fork "Wholesale" and return its agents to main',
            "End the session",
        ]

    async def test_moving_a_fork_to_main_applies_to_main(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        check = {**BLOCKED, "verdict": "passed", "outcomes": ["apply"]}
        api.request = _responder(
            {
                ("GET", SESSION_PATH): _session(
                    purpose="to_main",
                    fork_id=FORK,
                    line_name="Wholesale",
                    check=check,
                    outcomes=check["outcomes"],
                ),
                ("GET", f"{SESSION_PATH}/evidence"): EVIDENCE,
            }
        )

        session = await _call(server, "get_skill_improvement", skill_id=SKILL, session_id=SESSION)

        assert session["next_actions"][0] == "Apply to main"

    @pytest.mark.parametrize(
        ("outcome", "answer", "version"),
        [
            ("catch_up", {"session": _session("accepted"), "version_id": VERSION, "version": 3}, 3),
            ("return_to_main", {"session": _session("accepted")}, None),
        ],
    )
    async def test_a_catch_up_is_accepted_or_dropped_through_the_session(
        self,
        server: FastMCP,
        api: MagicMock,
        outcome: str,
        answer: dict[str, Any],
        version: int | None,
    ) -> None:
        api.request = _responder({("POST", f"{SESSION_PATH}/apply"): answer})

        applied = await _call(
            server,
            "accept_skill_improvement",
            skill_id=SKILL,
            session_id=SESSION,
            outcome=outcome,
        )

        assert _sent(api, "POST", f"{SESSION_PATH}/apply") == {
            "confirmed": True,
            "acknowledge_unknown": False,
            "outcome": outcome,
        }
        assert (applied["version"], applied["pinned"]) == (version, [])

    async def test_a_merge_shows_only_its_conflicts_and_counts_the_rest(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        conflict = {
            "state": "conflict",
            "base": "b",
            "fork": "f",
            "main": "m",
            "result": "r",
            "edited": True,
        }
        same = {"state": "main", "base": "b", "fork": "b", "main": "m", "result": "m"}
        api.request = _responder(
            {
                ("GET", MERGE): {
                    "parts": [same, conflict, {**same, "state": "both_same"}],
                    "unresolved": 0,
                }
            }
        )

        merge = await _call(server, "get_skill_merge", skill_id=SKILL, merge_id=VERSION)

        assert merge == {
            "conflicts": [{"index": 1, "fork": "f", "main": "m", "result": "r", "edited": True}],
            "merged_by_themselves": 2,
            "unresolved": 0,
        }

    async def test_a_part_takes_the_person_s_text(self, server: FastMCP, api: MagicMock) -> None:
        path = f"{MERGE}/parts/1"
        api.request = _responder(
            {("PATCH", path): {"fork": "f", "main": "m", "result": "mine", "edited": True}}
        )

        part = await _call(
            server,
            "edit_skill_merge_part",
            skill_id=SKILL,
            merge_id=VERSION,
            index=1,
            result="mine",
        )

        assert _sent(api, "PATCH", path) == {"result": "mine"}
        assert part["edited"] is True

    @pytest.mark.parametrize(
        ("agent_ids", "sent"), [(None, {}), ([COUNTER], {"agent_ids": [COUNTER]})]
    )
    async def test_dropping_a_fork_returns_all_its_agents_or_those_named(
        self,
        server: FastMCP,
        api: MagicMock,
        agent_ids: list[str] | None,
        sent: dict[str, Any],
    ) -> None:
        path = f"{BASE}/forks/{FORK}/return-to-main"
        api.request = _responder({("POST", path): {"moved": ["Wholesale desk"]}})

        returned = await _call(
            server, "return_fork_to_main", skill_id=SKILL, fork_id=FORK, agent_ids=agent_ids
        )

        assert api.request.await_args_list[0].kwargs["json"] == sent
        assert returned["link"] == skill_link(SKILL)

    async def test_an_updated_pinned_agent_carries_its_check(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        path = f"{BASE}/agents/{COUNTER}/binding"
        api.request = _responder(
            {
                ("PUT", path): {
                    "published": True,
                    "agent_version": 5,
                    "environments": [],
                    "usage": _usage(COUNTER, "Gift shop counter", MAIN),
                }
            }
        )

        await _call(
            server,
            "change_skill_version",
            skill_id=SKILL,
            agent_id=COUNTER,
            state="main",
            check_id=CHECK_READ["id"],
        )

        assert _sent(api, "PUT", path) == {"state": "main", "check_id": CHECK_READ["id"]}


READS = {
    "get_skill",
    "list_skill_versions",
    "get_skill_version",
    "list_skill_improvements",
    "get_skill_improvement",
    "estimate_skill_improvement",
    "estimate_next_skill_improvement_step",
    "list_skills_behind_main",
    "get_skill_check",
    "get_skill_merge",
}
WRITES = {
    "start_skill_improvement",
    "run_next_skill_improvement_step",
    "accept_skill_improvement",
    "end_skill_improvement",
    "change_skill_version",
    "start_skill_update_check",
    "start_skill_catch_up",
    "edit_skill_merge_part",
    "return_fork_to_main",
}


@pytest.mark.security
def test_the_skill_reads_never_wait_for_approval() -> None:
    catalog = {tool.name: tool for tool in platform_tool_catalog()}
    assert all(not catalog[name].writes and not catalog[name].held for name in READS)


@pytest.mark.security
def test_every_skill_write_waits_for_the_person_s_approval() -> None:
    """Starting, stepping, accepting, ending and moving an agent all reach a card first."""
    catalog = {tool.name: tool for tool in platform_tool_catalog()}
    assert all(catalog[name].writes and not catalog[name].ungated for name in WRITES)


PATHS = [
    ("GET", BASE),
    ("GET", f"{BASE}/forks"),
    ("GET", f"{BASE}/agents"),
    ("GET", f"{BASE}/versions"),
    ("GET", f"{BASE}/versions/{VERSION}"),
    ("PUT", f"{BASE}/agents/{COUNTER}/binding"),
    ("GET", "/skill-improvements/awaiting"),
    ("GET", SESSIONS),
    ("POST", f"{SESSIONS}/estimate"),
    ("POST", SESSIONS),
    ("GET", SESSION_PATH),
    ("GET", f"{SESSION_PATH}/evidence"),
    ("POST", f"{SESSION_PATH}/continue/estimate"),
    ("POST", f"{SESSION_PATH}/continue"),
    ("POST", f"{SESSION_PATH}/recheck/estimate"),
    ("POST", f"{SESSION_PATH}/recheck"),
    ("POST", f"{SESSION_PATH}/apply"),
    ("POST", f"{SESSION_PATH}/fork"),
    ("POST", f"{SESSION_PATH}/discard"),
    ("POST", f"{SESSION_PATH}/cancel"),
    ("GET", f"{BASE}/checks/{VERSION}"),
]


@pytest.mark.parametrize(("method", "path"), PATHS)
def test_every_route_the_skill_tools_call_admits_the_tools_key(method: str, path: str) -> None:
    from tests.test_platform_mcp_tools import _reachable

    assert _reachable(method, path), f"no public or assistant route answers {method} {path}"
