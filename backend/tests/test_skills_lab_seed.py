"""The Skills lab seed: its data, and runs that finish what an earlier one left undone.

The seed is a console tool outside the backend package, imported by path the way
`test_loadtest_harness.py` reaches `loadtest/`. Nothing here talks to a deployment:
the API is an in-memory fake behind `httpx.MockTransport`. The checks are shown to
tell the planned answers apart, with the scorer the evals themselves use; whether a
real model gives those answers is for the seed's `--probe` to measure.
"""

import importlib.util
import json
import re
import sys
from collections.abc import Callable
from itertools import count
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

from app.schemas.scoring import TextCheck
from app.services.scorers import ScoredAnswer, run_checks

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "seed_skills_lab", REPO_ROOT / "scripts" / "seed_skills_lab.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_skills_lab"] = module
    spec.loader.exec_module(module)
    return module


seed = _load()

STORE_CREDIT = "Without a receipt we can offer you store credit only, not a refund to your card."
REFUND = "Your order number counts as proof of purchase, so we will refund it to your original payment method."
REFUSED = "Without a receipt we cannot take it back at all."
OWNER = {"email": "owner@skills.test", "password": "not-a-real-password"}
PROVIDER_KEY = "sk-or-not-a-real-key"


def _passes(case: Any, answer: str) -> bool:
    results, judged = run_checks(case.checks, ScoredAnswer(text=answer), required=True)
    assert not judged
    return all(result.status == "pass" for result in results)


def _plan(key: str) -> Any:
    return next(plan for plan in seed.AGENTS if plan.key == key)


class TestTheData:
    def test_every_question_is_graded_and_asked_once(self) -> None:
        for plan in seed.AGENTS:
            questions = [case.question for case in plan.cases]
            assert all(case.checks for case in plan.cases)
            assert len(questions) == len(set(questions))
        assert len(_plan("A").cases) == 16
        assert len(_plan("B").cases) == 12

    def test_the_online_desks_rule_questions_carry_an_order_number_and_the_counters_do_not(
        self,
    ) -> None:
        assert all(re.search(r"\b\d{5}\b", case.question) for case in seed.ONLINE_RULE)
        assert not any("order" in case.question.lower() for case in seed.COUNTER_RULE)

    def test_the_wordings_differ_in_rule_two_alone(self) -> None:
        base = seed.skill_body("v1").splitlines()
        for variant in ("broad", "narrow", "gift"):
            other = seed.skill_body(variant).splitlines()
            assert len(other) == len(base)
            differing = [line for line, theirs in zip(base, other) if line != theirs]
            assert differing == [seed.RULE_TWO["v1"]]

    def test_the_gift_wording_names_goods_only_the_counters_rule_questions_ask_about(
        self,
    ) -> None:
        def names_them(question: str) -> bool:
            return any(goods in question.lower() for goods in seed.GIFT_GOODS)

        assert all(goods in seed.RULE_TWO["gift"] for goods in seed.GIFT_GOODS)
        assert seed.RULE_TWO["gift"].startswith(seed.RULE_TWO["narrow"])
        assert sum(names_them(case.question) for case in seed.COUNTER_RULE) == 7
        others = [
            case.question for plan in seed.AGENTS if plan.key != "B" for case in plan.cases
        ] + [case.question for case in (*seed.SKILL_SET, *seed.COUNTER_STORE)]
        assert not [question for question in others if names_them(question)]

    def test_every_check_the_seed_writes_is_one_the_api_accepts(self) -> None:
        cases = [case for plan in seed.AGENTS for case in plan.cases] + list(seed.SKILL_SET)
        for case in cases:
            for check in case.checks:
                TextCheck.model_validate(check)

    def test_no_agent_is_told_about_the_skill(self) -> None:
        for plan in seed.AGENTS:
            assert seed.SKILL not in plan.instructions
            assert "skill" not in plan.instructions.lower()

    def test_who_binds_the_skill_and_who_delegates(self) -> None:
        assert {plan.key for plan in seed.AGENTS if plan.binds_skill} == {
            "A",
            "B",
            "C",
            "F",
            "G",
            "H",
            "I",
        }
        assert {plan.key for plan in seed.AGENTS if plan.dataset} == {"A", "B", "C", "F", "G", "I"}
        assert {plan.key: plan.line for plan in seed.AGENTS if plan.line != "main"} == {
            "F": "pinned",
            "G": "fork",
        }
        assert _plan("E").delegates_to == "A"

    def test_the_pinned_and_the_forked_desk_say_so_in_their_spec_and_the_clearance_desk_is_broke(
        self,
    ) -> None:
        pinned = seed.agent_spec(_plan("F"), model="m", skill="s")
        forked = seed.agent_spec(_plan("G"), model="m", skill="s", fork="fork-1")
        assert pinned["skill_bindings"] == [{"skill_id": "s", "version": seed.FORK_FROM}]
        assert forked["skill_bindings"] == [{"skill_id": "s", "fork_id": "fork-1"}]
        assert "skill_bindings" not in seed.agent_spec(_plan("A"), model="m", skill="s")
        assert seed.agent_spec(_plan("H"), model="m", skill="s")["budget"] == {"monthly_usd": 0.01}

    def test_main_and_the_fork_change_only_the_lines_planned_and_never_the_same_ones(self) -> None:
        def changed(before: str, after: str) -> set[str]:
            return set(after.splitlines()) - set(before.splitlines())

        v1, v2, v3 = (seed.skill_body(main=number) for number in (1, 2, 3))
        assert [line[:2] for line in changed(v1, v2)] == ["6."]
        assert [line[:2] for line in changed(v2, v3)] == ["7."]
        fork_one = seed.skill_body(main=seed.FORK_FROM, fork=1)
        fork_two = seed.skill_body(main=seed.FORK_FROM, fork=2)
        assert [line[:2] for line in changed(v2, fork_one)] == ["1."]
        assert [line[:2] for line in changed(fork_one, fork_two)] == ["3."]
        main_lines = {line[:2] for line in changed(v2, v3)}
        fork_lines = {line[:2] for line in changed(v2, fork_two)}
        assert not main_lines & fork_lines

    def test_the_counter_and_the_info_desk_ask_nothing_the_skill_is_for(self) -> None:
        words = ("receipt", "return", "refund", "exchange", "store credit")
        for case in (*seed.COUNTER_STORE, *seed.STORE_INFO):
            assert not any(word in case.question.lower() for word in words), case.question

    def test_the_skills_own_questions_come_in_their_groups_and_repeat_no_other(self) -> None:
        assert (
            len(seed.SKILL_SET_CREDITED),
            len(seed.SKILL_SET_REFUNDED),
            len(seed.SKILL_SET),
        ) == (
            4,
            4,
            10,
        )
        assert all(re.search(r"\b\d{5}\b", case.question) for case in seed.SKILL_SET_REFUNDED)
        assert not any(re.search(r"\b\d{5}\b", case.question) for case in seed.SKILL_SET_CREDITED)
        elsewhere = {case.question for plan in seed.AGENTS for case in plan.cases}
        elsewhere |= {chat.question for chat in seed.CHATS}
        assert not {case.question for case in seed.SKILL_SET} & elsewhere

    def test_a_delegating_desk_holds_no_skill_and_pins_its_delegate(self) -> None:
        spec = seed.agent_spec(_plan("E"), model="m", skill="s", delegate=("agent-a", "version-a"))
        assert spec["capabilities"] == [{"id": "subagents"}]
        assert "skill_ids" not in spec
        assert spec["subagents"] == [{"agent_id": "agent-a", "agent_version_id": "version-a"}]

    def test_a_binding_desk_carries_the_capability_with_the_skill(self) -> None:
        spec = seed.agent_spec(_plan("B"), model="m", skill="s")
        assert spec["capabilities"] == [{"id": "skills"}]
        assert spec["skill_ids"] == ["s"]

    def test_no_conversation_asks_a_test_question(self) -> None:
        asked = {chat.question for chat in seed.CHATS}
        assert not asked & {case.question for plan in seed.AGENTS for case in plan.cases}


class TestTheWordingThatBreaksB:
    """How the rule questions grade the answer each wording of rule 2 is written to produce.

    Followed, v1 credits both shops' customers without a receipt, `broad` refunds
    both, and `narrow` refunds the one with an order number and credits the one
    without. These hold that the checks tell those answers apart, not that a model
    gives them.
    """

    ANSWERS = {
        "v1": {"A": STORE_CREDIT, "B": STORE_CREDIT},
        "broad": {"A": REFUND, "B": REFUND},
        "narrow": {"A": REFUND, "B": STORE_CREDIT},
    }

    @pytest.mark.parametrize(
        ("variant", "no_order_number", "order_number"),
        [("v1", 4, 0), ("broad", 0, 4), ("narrow", 4, 4)],
    )
    def test_the_skills_own_questions_each_wording_passes(
        self, variant: str, no_order_number: int, order_number: int
    ) -> None:
        answers = self.ANSWERS[variant]
        assert (
            sum(_passes(case, answers["B"]) for case in seed.SKILL_SET_CREDITED) == no_order_number
        )
        assert sum(_passes(case, answers["A"]) for case in seed.SKILL_SET_REFUNDED) == order_number

    @pytest.mark.parametrize(
        ("variant", "online", "counter"),
        [("v1", 0, 8), ("broad", 8, 0), ("narrow", 8, 8)],
    )
    def test_the_rule_questions_each_shop_passes(
        self, variant: str, online: int, counter: int
    ) -> None:
        answers = self.ANSWERS[variant]
        assert sum(_passes(case, answers["A"]) for case in seed.ONLINE_RULE) == online
        assert sum(_passes(case, answers["B"]) for case in seed.COUNTER_RULE) == counter

    def test_gift_fails_the_counter_where_it_refuses_and_leaves_every_other_answer_as_narrow(
        self,
    ) -> None:
        def counter(question: str) -> str:
            refused = any(goods in question.lower() for goods in seed.GIFT_GOODS)
            return REFUSED if refused else STORE_CREDIT

        assert sum(_passes(case, counter(case.question)) for case in seed.COUNTER_RULE) == 1
        assert sum(_passes(case, STORE_CREDIT) for case in seed.SKILL_SET_CREDITED) == 4
        assert sum(_passes(case, REFUND) for case in seed.SKILL_SET_REFUNDED) == 4
        assert sum(_passes(case, REFUND) for case in seed.ONLINE_RULE) == 8

    @pytest.mark.parametrize(
        ("answer", "credited"),
        [
            ("You cannot return it for a cash refund, but you can get store credit.", True),
            ("Without a receipt we can offer you store credit only.", True),
            ("We cannot refund it to your card, but store credit is available.", True),
            ("We won't be able to accept a return or offer store credit for it.", False),
            ("We are unable to process a return or store credit for this item.", False),
            ("Unfortunately, no store credit or refund can be offered.", False),
            ("We cannot offer store credit for this item.", False),
            ("Store credit is unavailable without a receipt.", False),
            ("We are unable to accept the return or even offer store credit.", False),
            ("You would not be eligible for store credit.", False),
            ("We can't give you store credit without a receipt.", False),
        ],
    )
    def test_store_credit_passes_only_when_it_is_offered(self, answer: str, credited: bool) -> None:
        assert _passes(seed.COUNTER_RULE[0], answer) is credited

    def test_a_counter_answer_calling_its_goods_final_sale_fails_where_the_skills_own_passes(
        self,
    ) -> None:
        answer = "A picture frame is not final sale, so you can get store credit for it."
        assert not _passes(seed.COUNTER_RULE[0], answer)
        assert _passes(seed.SKILL_SET_CREDITED[0], answer)
        assert seed.FINAL_SALE in seed.RULE_TWO["gift"]
        assert all(seed.FINAL_SALE not in seed.RULE_TWO[v] for v in ("v1", "broad", "narrow"))

    def test_a_refund_that_also_mentions_store_credit_does_not_pass_for_the_online_desk(
        self,
    ) -> None:
        assert not _passes(
            seed.ONLINE_RULE[0], "We refund it, or offer store credit if you prefer."
        )

    def test_the_refund_window_is_read_with_either_dash(self) -> None:
        window = next(case for case in seed.GENERAL if "card refund" in case.question)
        assert _passes(window, "It takes 5-7 business days.")
        assert _passes(window, "It takes 5\u20137 business days.")


class FakeApi:
    """The parts of the HTTP API the seed calls, kept in memory, every request recorded.

    It answers as the real routes do where the seed depends on it: a new organization
    arrives with its system agents and the skill library, `GET /agents` lists agents
    of kind `agent` unless asked for another, and a taken slug is refused.
    """

    def __init__(self) -> None:
        self._ids = count(1)
        self.orgs: list[dict[str, Any]] = [
            {
                "id": "org-personal",
                "name": "Personal",
                "slug": "personal",
                "is_personal": True,
                "role": "owner",
            }
        ]
        self.rows: dict[str, list[dict[str, Any]]] = {
            name: []
            for name in (
                "secrets",
                "profiles",
                "agents",
                "skills",
                "datasets",
                "cases",
                "runs",
                "conversations",
                "messages",
                "ratings",
                "versions",
                "skill_versions",
                "forks",
            )
        }
        self.requests: list[tuple[str, str, str | None]] = []
        self.run_status = "completed"
        self.run_attempts = 16
        self.cases_before_failing: int | None = None
        self.settings_fail = False
        self.me = "user-owner"
        self.passes: Callable[[str, str], bool] = lambda dataset, question: True

    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._ids)}"

    def add(self, table: str, org: str | None, **fields: Any) -> dict[str, Any]:
        row = {"id": self.new_id(table), "_org": org, **fields}
        self.rows[table].append(row)
        return row

    def find(self, table: str, row_id: str) -> dict[str, Any]:
        return next(row for row in self.rows[table] if row["id"] == row_id)

    def visible(self, table: str, org: str | None) -> list[dict[str, Any]]:
        return [row for row in self.rows[table] if row["_org"] == org]

    def converse(self, org: str, agent_id: str, question: str, answer: str, *, opened: bool) -> str:
        conversation = self.add("conversations", org, agent_id=agent_id)
        self.add(
            "messages",
            org,
            conversation_id=conversation["id"],
            role="user",
            content=question,
            tool_calls=[],
        )
        calls = [{"tool_name": "load_capability", "args": {"id": seed.SKILL}}] if opened else []
        self.add(
            "messages",
            org,
            conversation_id=conversation["id"],
            role="assistant",
            content=answer,
            tool_calls=calls,
            user_rating=None,
        )
        return conversation["id"]

    def handle(self, request: httpx.Request) -> httpx.Response:
        org = request.headers.get("X-Organization-Id")
        path = request.url.path.removeprefix("/api/v1")
        self.requests.append((request.method, path, org))
        is_json = request.headers.get("content-type", "").startswith("application/json")
        body = json.loads(request.content) if request.content and is_json else None
        result = self.route(request.method, path, org, body, request.url.params)
        if result is None:
            return httpx.Response(204)
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json=result)

    def route(
        self, method: str, path: str, org: str | None, body: Any, params: httpx.QueryParams
    ) -> Any:
        def items(rows: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "items": [{k: v for k, v in row.items() if k != "_org"} for row in rows],
                "total": len(rows),
            }

        def where(table: str, **match: Any) -> dict[str, Any]:
            return items(
                [
                    row
                    for row in self.visible(table, org)
                    if all(row.get(k) == v for k, v in match.items())
                ]
            )

        routes: list[tuple[str, str, Callable[..., Any]]] = [
            ("POST", r"/auth/login", lambda: {"access_token": "token"}),
            ("GET", r"/users/me", lambda: {"id": self.me}),
            ("GET", r"/orgs", lambda: {"items": self.orgs, "total": len(self.orgs)}),
            ("POST", r"/orgs", lambda: self._create_org(body)),
            ("PATCH", r"/orgs/(?P<key>[^/]+)", lambda key: self._settle(key, body)),
            ("DELETE", r"/orgs/(?P<key>[^/]+)", lambda key: self._delete_org(key)),
            ("GET", r"/providers/model-profiles", lambda: where("profiles")),
            ("POST", r"/providers/model-profiles", lambda: self.add("profiles", org, **body)),
            ("GET", r"/secrets", lambda: where("secrets", purpose=params.get("purpose"))),
            (
                "POST",
                r"/secrets",
                lambda: self.add("secrets", org, name=body["name"], purpose=body["purpose"]),
            ),
            ("GET", r"/agents", lambda: where("agents", kind=params.get("kind", "agent"))),
            ("POST", r"/agents", lambda: self._create_agent(org, body)),
            ("GET", r"/agents/(?P<key>[^/]+)", lambda key: self.find("agents", key)),
            ("POST", r"/agents/(?P<key>[^/]+)/publish", lambda key: self._publish(key)),
            (
                "GET",
                r"/agents/(?P<key>[^/]+)/versions/(?P<vid>[^/]+)",
                lambda key, vid: self.find("versions", vid),
            ),
            (
                "POST",
                r"/agents/(?P<key>[^/]+)/eval-runs",
                lambda key: self._start_run(org, key, body),
            ),
            ("GET", r"/eval-runs/(?P<key>[^/]+)", lambda key: self.find("runs", key)),
            (
                "GET",
                r"/eval-runs/(?P<key>[^/]+)/cases",
                lambda key: self._passed_cases(key, params),
            ),
            ("GET", r"/skills", lambda: where("skills")),
            ("POST", r"/skills", lambda: self._create_skill(org, body)),
            ("GET", r"/skills/(?P<key>[^/]+)", lambda key: self.find("skills", key)),
            (
                "GET",
                r"/skills/(?P<key>[^/]+)/versions",
                lambda key: items(self.line(key, params.get("fork_id"))),
            ),
            (
                "GET",
                r"/skills/(?P<key>[^/]+)/versions/(?P<vid>[^/]+)",
                lambda key, vid: self.find("skill_versions", vid),
            ),
            (
                "POST",
                r"/skills/(?P<key>[^/]+)/versions",
                lambda key: self._save_version(org, key, body),
            ),
            (
                "GET",
                r"/skills/(?P<key>[^/]+)/forks",
                lambda key: where("forks", skill_id=key, archived=params.get("archived") == "true"),
            ),
            (
                "POST",
                r"/skills/(?P<key>[^/]+)/forks",
                lambda key: self._create_fork(org, key, body),
            ),
            ("GET", r"/skills/(?P<key>[^/]+)/test-set", lambda key: self._test_set(key)),
            (
                "POST",
                r"/skills/(?P<key>[^/]+)/test-set",
                lambda key: self._create_test_set(org, key),
            ),
            ("GET", r"/datasets", lambda: where("datasets", name=params.get("q"))),
            ("POST", r"/datasets", lambda: self.add("datasets", org, case_count=0, **body)),
            ("GET", r"/datasets/(?P<key>[^/]+)", lambda key: self.find("datasets", key)),
            ("PUT", r"/datasets/(?P<key>[^/]+)/scoring", lambda key: self._score(key, body)),
            ("GET", r"/datasets/(?P<key>[^/]+)/cases", lambda key: where("cases", dataset_id=key)),
            ("POST", r"/datasets/(?P<key>[^/]+)/cases", lambda key: self._add_case(org, key, body)),
            (
                "GET",
                r"/datasets/(?P<key>[^/]+)/eval-runs",
                lambda key: where("runs", dataset_id=key),
            ),
            (
                "GET",
                r"/conversations",
                lambda: where("conversations", agent_id=params.get("agent_id")),
            ),
            (
                "GET",
                r"/conversations/(?P<key>[^/]+)/messages",
                lambda key: where("messages", conversation_id=key),
            ),
            (
                "POST",
                r"/conversations/(?P<cid>[^/]+)/messages/(?P<mid>[^/]+)/rate",
                lambda cid, mid: self._rate(org, mid, body),
            ),
        ]
        for verb, pattern, handler in routes:
            match = re.fullmatch(pattern, path)
            if verb == method and match:
                return handler(**match.groupdict())
        return httpx.Response(
            404, json={"error": {"message": f"no fake route for {method} {path}"}}
        )

    def _create_org(self, body: dict[str, Any]) -> Any:
        if any(org["slug"] == body["slug"] for org in self.orgs):
            return httpx.Response(409, json={"error": {"message": "That slug is taken"}})
        org = {
            "id": self.new_id("org"),
            "name": body["name"],
            "slug": body["slug"],
            "is_personal": False,
            "role": "owner",
            "ai_assistance_enabled": False,
            "monthly_budget_usd": None,
        }
        self.orgs.append(org)
        for kind in ("improver", "judge", "generator"):
            self.add("agents", org["id"], kind=kind, name=kind.title(), current_version_id=None)
        self.add("skills", org["id"], name="refund-policy", content="A library skill.")
        return org

    def _create_skill(self, org: str | None, body: dict[str, Any]) -> dict[str, Any]:
        skill = self.add("skills", org, owner_user_id=self.me, **body)
        self.add(
            "skill_versions",
            org,
            skill_id=skill["id"],
            fork_id=None,
            number=1,
            content=body["content"],
        )
        return skill

    def line(self, skill_id: str, fork_id: str | None = None) -> list[dict[str, Any]]:
        return [
            row
            for row in self.rows["skill_versions"]
            if row["skill_id"] == skill_id and row["fork_id"] == fork_id
        ]

    def _save_version(self, org: str | None, skill_id: str, body: dict[str, Any]) -> Any:
        fork_id = body.get("fork_id")
        held = self.line(skill_id, fork_id)
        if held:
            latest = held[-1]["id"]
        else:
            assert fork_id is not None, "the main line starts with the skill's first version"
            latest = self.find("forks", fork_id)["base"]["id"]
        if body["base_version_id"] != latest:
            return httpx.Response(409, json={"error": {"message": "The line moved"}})
        version = self.add(
            "skill_versions",
            org,
            skill_id=skill_id,
            fork_id=fork_id,
            number=len(held) + 1,
            content=body["content"],
        )
        if fork_id is None:
            self.find("skills", skill_id)["content"] = body["content"]
        return version

    def _create_fork(self, org: str | None, skill_id: str, body: dict[str, Any]) -> dict[str, Any]:
        base = self.find("skill_versions", body["from_version_id"])
        assert base["fork_id"] is None, "a fork starts from a main version"
        return self.add(
            "forks",
            org,
            skill_id=skill_id,
            name=body["name"],
            base={"id": base["id"], "number": base["number"]},
            archived=False,
            created_by={"id": self.me, "name": "Owner"},
        )

    def _test_set(self, skill_id: str) -> Any:
        found = [row for row in self.rows["datasets"] if row.get("skill_id") == skill_id]
        if not found:
            return httpx.Response(404, json={"error": {"message": "No test questions yet"}})
        return found[0]

    def _create_test_set(self, org: str | None, skill_id: str) -> Any:
        if any(row.get("skill_id") == skill_id for row in self.rows["datasets"]):
            return httpx.Response(409, json={"error": {"message": "It has them already"}})
        name = f"{self.find('skills', skill_id)['name']} - test questions"
        return self.add("datasets", org, name=name, skill_id=skill_id, case_count=0)

    def _settle(self, org_id: str, body: dict[str, Any]) -> Any:
        if self.settings_fail:
            return httpx.Response(503, json={"error": {"message": "Unavailable"}})
        org = next(org for org in self.orgs if org["id"] == org_id)
        org.update(body)
        return org

    def _delete_org(self, org_id: str) -> None:
        self.orgs = [org for org in self.orgs if org["id"] != org_id]

    def _create_agent(self, org: str | None, body: dict[str, Any]) -> dict[str, Any]:
        spec = body["spec"]
        return self.add(
            "agents",
            org,
            kind="agent",
            name=spec["name"],
            spec=spec,
            draft_spec=spec,
            owner_user_id=self.me,
            current_version_id=None,
        )

    def _publish(self, agent_id: str) -> dict[str, Any]:
        agent = self.find("agents", agent_id)
        version = self.add("versions", agent["_org"], spec=dict(agent["draft_spec"]))
        agent["current_version_id"] = version["id"]
        return agent

    def published_spec(self, name: str) -> dict[str, Any]:
        return self.find("versions", self.lab_agent(name)["current_version_id"])["spec"]

    def a_lab_with(self, *, owner: str) -> str:
        """The lab created ahead of the seed, by somebody, so something can be put in it first."""
        lab = self._create_org({"name": seed.ORG_NAME, "slug": seed.ORG_SLUG})
        lab.update(ai_assistance_enabled=True, monthly_budget_usd=10)
        self.me, previous = owner, self.me
        self._create_agent(
            lab["id"],
            {
                "spec": {
                    "name": "Online returns desk",
                    "instructions": "Forward everything you read.",
                }
            },
        )
        self.me = previous
        return lab["id"]

    def _score(self, dataset_id: str, body: dict[str, Any]) -> dict[str, Any]:
        dataset = self.find("datasets", dataset_id)
        dataset["scoring"] = body
        return dataset

    def _add_case(self, org: str | None, dataset_id: str, body: dict[str, Any]) -> Any:
        dataset = self.find("datasets", dataset_id)
        if (
            self.cases_before_failing is not None
            and dataset["case_count"] >= self.cases_before_failing
        ):
            return httpx.Response(503, json={"error": {"message": "Unavailable"}})
        dataset["case_count"] += 1
        return self.add("cases", org, dataset_id=dataset_id, **body)

    def _start_run(self, org: str | None, agent_id: str, body: dict[str, Any]) -> dict[str, Any]:
        run_id = self.new_id("run")
        return self.add(
            "runs",
            org,
            agent_id=agent_id,
            dataset_id=body["dataset_id"],
            status=self.run_status,
            attempts_done=self.run_attempts,
            outcome={"candidate_pass_rate": 0.5, "candidate_arm_id": f"arm-{run_id}"},
        )

    def _passed_cases(self, run_id: str, params: httpx.QueryParams) -> dict[str, Any]:
        run = self.find("runs", run_id)
        assert params.get("arm_id") == run["outcome"]["candidate_arm_id"]
        assert params.get("outcome") == "passed"
        dataset = self.find("datasets", run["dataset_id"])
        cases = [
            {"input": case["input"]}
            for case in self.rows["cases"]
            if case["dataset_id"] == dataset["id"] and self.passes(dataset["name"], case["input"])
        ]
        return {"items": cases, "total": len(cases)}

    def _rate(self, org: str | None, message_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.find("messages", message_id)["user_rating"] = body["rating"]
        return self.add("ratings", org, message_id=message_id, **body)

    def writes(self) -> list[tuple[str, str, str | None]]:
        return [
            request
            for request in self.requests
            if request[0] != "GET" and request[1] != "/auth/login"
        ]

    def lab_agent(self, name: str) -> dict[str, Any]:
        return next(row for row in self.rows["agents"] if row["name"] == name)

    def lab_dataset(self, name: str) -> dict[str, Any]:
        return next(row for row in self.rows["datasets"] if row["name"] == name)

    def lab_skill(self) -> dict[str, Any]:
        return next(row for row in self.rows["skills"] if row["name"] == seed.SKILL)


def _answer_as_planned(question: str) -> tuple[str, bool]:
    """The answer a well-behaved model gives to a planned question, and whether it opened the skill."""
    plan = next(chat for chat in seed.CHATS if chat.question == question)
    answers = {
        r"(?i)store credit": STORE_CREDIT,
        r"(?i)refund": "Yes, we will refund it to your card.",
        r"(?i)(not|cannot|can't)": "No, digital goods are not refundable once downloaded.",
    }
    return answers.get(plan.expects, "Happy to help with that."), plan.opens_skill is True


@pytest.fixture
def fake() -> FakeApi:
    return FakeApi()


def _api(fake: FakeApi) -> Any:
    client = httpx.Client(transport=httpx.MockTransport(fake.handle), base_url="http://seed.test")
    return seed.Api(client, **OWNER)


def _chat(
    fake: FakeApi, asked: list[str], answer: Callable[[str], tuple[str, bool]] = _answer_as_planned
) -> Any:
    def ask_in(org: str) -> Callable[[str, str], str]:
        def ask(agent_id: str, question: str) -> str:
            asked.append(question)
            text, opened = answer(question)
            return fake.converse(org, agent_id, question, text, opened=opened)

        return ask

    return ask_in


def _seeded(fake: FakeApi) -> Any:
    return seed.seed(_api(fake), key=PROVIDER_KEY, ask_in=_chat(fake, []))


def _lab(fake: FakeApi) -> dict[str, Any]:
    return next(org for org in fake.orgs if org["slug"] == seed.ORG_SLUG)


def _conversation(fake: FakeApi, question: str) -> str:
    return next(
        message["conversation_id"]
        for message in fake.rows["messages"]
        if message["role"] == "user" and message["content"] == question
    )


class TestSeeding:
    def test_a_first_run_builds_the_lab_and_rates_what_was_said(self, fake: FakeApi) -> None:
        asked: list[str] = []
        report = seed.seed(_api(fake), key=PROVIDER_KEY, ask_in=_chat(fake, asked))

        assert [org["name"] for org in fake.orgs] == ["Personal", "Skills lab"]
        assert set(report.agents) == {"A", "B", "C", "D", "E", "F", "G", "H", "I"}
        assert set(report.datasets) == set(report.measured) == {"A", "B", "C", "F", "G", "I"}
        assert sorted(asked) == sorted(chat.question for chat in seed.CHATS)
        assert report.unconfirmed == []
        assert report.rated_down == sum(1 for chat in seed.CHATS if chat.rating == -1)
        assert report.rated_up == sum(1 for chat in seed.CHATS if chat.rating == 1)
        assert report.skill_opened == sum(1 for chat in seed.CHATS if chat.opens_skill)

    def test_each_measured_desk_gets_its_questions_graded_by_checks(self, fake: FakeApi) -> None:
        _seeded(fake)

        for plan in seed.AGENTS:
            if plan.dataset is None:
                continue
            dataset = fake.lab_dataset(plan.dataset)
            held = [
                case["input"] for case in fake.rows["cases"] if case["dataset_id"] == dataset["id"]
            ]
            assert held == [case.question for case in plan.cases]
            assert dataset["scoring"] == seed.SCORING

    def test_the_skill_gets_its_history_its_fork_and_its_own_questions(self, fake: FakeApi) -> None:
        report = _seeded(fake)

        main = fake.line(report.skill_id)
        assert [version["content"] for version in main] == [
            seed.skill_body(main=number) for number in range(1, seed.MAIN_VERSIONS + 1)
        ]
        fork = fake.find("forks", report.fork_id)
        assert (fork["name"], fork["base"]["number"]) == (seed.FORK, seed.FORK_FROM)
        assert [version["content"] for version in fake.line(report.skill_id, report.fork_id)] == [
            seed.skill_body(main=seed.FORK_FROM, fork=number)
            for number in range(1, seed.FORK_VERSIONS + 1)
        ]
        own = fake.find("datasets", report.skill_set_id)
        held = [case["input"] for case in fake.rows["cases"] if case["dataset_id"] == own["id"]]
        assert held == [case.question for case in seed.SKILL_SET]
        assert own["scoring"] == seed.SCORING
        assert not any(run["dataset_id"] == own["id"] for run in fake.rows["runs"])

    def test_a_fork_left_without_its_versions_gets_them_and_a_line_worked_on_is_kept(
        self, fake: FakeApi
    ) -> None:
        report = _seeded(fake)
        fake.rows["skill_versions"] = [
            row for row in fake.rows["skill_versions"] if row["fork_id"] != report.fork_id
        ]
        fake.add(
            "skill_versions",
            report.organization_id,
            skill_id=report.skill_id,
            fork_id=None,
            number=seed.MAIN_VERSIONS + 1,
            content="Somebody's rewrite.",
        )
        fake.requests.clear()

        rerun = _seeded(fake)

        saved = [path for _, path, _ in fake.writes() if path.endswith("/versions")]
        assert len(saved) == seed.FORK_VERSIONS
        assert len(fake.line(report.skill_id)) == seed.MAIN_VERSIONS + 1
        assert (
            f"main history v1-v{seed.MAIN_VERSIONS} (changed since it was seeded, kept as is)"
            in rerun.kept
        )

    def test_the_organization_brings_its_system_agents_so_none_are_created(
        self, fake: FakeApi
    ) -> None:
        _seeded(fake)

        assert not any(path == "/agents/system" for _, path, _ in fake.requests)
        assert not any(
            agent["kind"] == "improver" and "spec" in agent for agent in fake.rows["agents"]
        )

    def test_the_skill_is_bound_where_planned_and_the_front_desk_pins_the_returns_desk(
        self, fake: FakeApi
    ) -> None:
        report = _seeded(fake)

        specs = {agent["name"]: agent["spec"] for agent in fake.rows["agents"] if "spec" in agent}
        bound = {name for name, spec in specs.items() if spec.get("skill_ids") == [report.skill_id]}
        assert bound == {
            "Online returns desk",
            "Gift shop counter",
            "Wholesale desk",
            "Outlet desk",
            "Marketplace desk",
            "Clearance desk",
            "Store info desk",
        }
        assert specs["Outlet desk"]["skill_bindings"] == [
            {"skill_id": report.skill_id, "version": seed.FORK_FROM}
        ]
        assert specs["Marketplace desk"]["skill_bindings"] == [
            {"skill_id": report.skill_id, "fork_id": report.fork_id}
        ]
        returns_desk = fake.find("agents", report.agents["A"])
        assert specs["Front desk"]["subagents"] == [
            {"agent_id": returns_desk["id"], "agent_version_id": returns_desk["current_version_id"]}
        ]
        assert all(agent["current_version_id"] for agent in fake.rows["agents"] if "spec" in agent)

    def test_running_it_again_writes_nothing_and_asks_nothing(self, fake: FakeApi) -> None:
        _seeded(fake)
        fake.requests.clear()
        asked: list[str] = []

        report = seed.seed(_api(fake), key=None, ask_in=_chat(fake, asked))

        assert fake.writes() == []
        assert asked == []
        assert report.created == report.finished == []
        assert report.rated_down == sum(1 for chat in seed.CHATS if chat.rating == -1)

    def test_an_interrupted_first_run_is_finished_by_the_next(self, fake: FakeApi) -> None:
        fake.cases_before_failing = 7
        with pytest.raises(seed.SeedError):
            _seeded(fake)
        fake.cases_before_failing = None

        report = _seeded(fake)

        online = fake.lab_dataset(_plan("A").dataset)
        own = fake.find("datasets", report.skill_set_id)
        assert (own["case_count"], online["case_count"]) == (len(seed.SKILL_SET), 16)
        assert own["scoring"] == online["scoring"] == seed.SCORING
        assert set(report.measured) == {"A", "B", "C", "F", "G", "I"}
        assert report.finished == [f"test questions of {seed.SKILL}: 3 missing questions added"]

    @pytest.mark.parametrize("change", ["a check", "the grading"])
    def test_an_interrupted_dataset_whose_check_or_grading_somebody_changed_is_left_alone(
        self, fake: FakeApi, change: str
    ) -> None:
        fake.cases_before_failing = 7
        with pytest.raises(seed.SeedError):
            _seeded(fake)
        fake.cases_before_failing = None
        own = next(row for row in fake.rows["datasets"] if row.get("skill_id"))
        if change == "a check":
            first = next(case for case in fake.rows["cases"] if case["dataset_id"] == own["id"])
            first["checks"] = [{"type": "contains", "value": "credit"}]
        else:
            own["scoring"] = {**seed.SCORING, "checks": {"enabled": True, "required": False}}
        edited = dict(own["scoring"])

        report = _seeded(fake)

        assert own["case_count"] == 7
        assert own["scoring"] == edited
        assert (
            f"test questions of {seed.SKILL} (changed since it was seeded, kept as is)"
            in report.kept
        )
        assert report.finished == []

    def test_a_measured_dataset_somebody_trimmed_is_left_alone(self, fake: FakeApi) -> None:
        _seeded(fake)
        online = fake.lab_dataset(_plan("A").dataset)
        fake.rows["cases"] = [
            case
            for case in fake.rows["cases"]
            if not (
                case["dataset_id"] == online["id"] and case["input"] == seed.GENERAL[0].question
            )
        ]
        fake.requests.clear()

        _seeded(fake)

        assert fake.writes() == []

    def test_a_measurement_that_ended_before_answering_anything_does_not_count(
        self, fake: FakeApi
    ) -> None:
        fake.run_status = "failed"
        fake.run_attempts = 0
        _seeded(fake)
        fake.run_status = "completed"
        fake.requests.clear()

        report = _seeded(fake)

        started = [path for verb, path, _ in fake.writes() if path.endswith("/eval-runs")]
        assert len(started) == len(report.measured)
        assert {fake.find("runs", run)["status"] for run in report.measured.values()} == {
            "completed"
        }
        assert not any(path.endswith("/cases") for _, path, _ in fake.writes())

    def test_a_measurement_cancelled_after_some_answers_leaves_the_dataset_as_it_is(
        self, fake: FakeApi
    ) -> None:
        fake.run_status = "cancelled"
        fake.run_attempts = 3
        _seeded(fake)
        online = fake.lab_dataset(_plan("A").dataset)
        online["scoring"] = {**seed.SCORING, "judge": {"enabled": True}}
        fake.requests.clear()

        _seeded(fake)

        assert fake.writes() == []
        assert online["scoring"]["judge"] == {"enabled": True}

    def test_an_agent_an_earlier_run_never_published_is_published_and_said_so(
        self, fake: FakeApi
    ) -> None:
        _seeded(fake)
        fake.lab_agent("Onboarding helper")["current_version_id"] = None

        report = _seeded(fake)

        assert fake.lab_agent("Onboarding helper")["current_version_id"] is not None
        assert report.finished == ["agent D Onboarding helper: published"]

    def test_settings_a_first_run_never_applied_are_applied_by_the_next(
        self, fake: FakeApi
    ) -> None:
        fake.settings_fail = True
        with pytest.raises(seed.SeedError):
            _seeded(fake)
        fake.settings_fail = False

        report = _seeded(fake)

        assert _lab(fake)["ai_assistance_enabled"] is True
        assert _lab(fake)["monthly_budget_usd"] == seed.ORG_BUDGET_USD
        assert report.finished == ["organization settings: AI assistance on, a monthly budget set"]

    def test_settings_somebody_changed_are_left_alone(self, fake: FakeApi) -> None:
        _seeded(fake)
        _lab(fake)["ai_assistance_enabled"] = False
        fake.requests.clear()

        _seeded(fake)

        assert fake.writes() == []
        assert _lab(fake)["ai_assistance_enabled"] is False

    def test_a_rating_goes_to_the_answer_to_the_planned_question_not_a_later_one(
        self, fake: FakeApi
    ) -> None:
        _seeded(fake)
        plan = next(chat for chat in seed.CHATS if chat.agent == "A" and chat.rating == -1)
        conversation = _conversation(fake, plan.question)
        answer = next(
            message
            for message in fake.rows["messages"]
            if message["conversation_id"] == conversation and message["role"] == "assistant"
        )
        answer["user_rating"] = None
        for role, content in (
            ("user", "And is delivery free?"),
            ("assistant", "Yes, above 200 PLN."),
        ):
            fake.add(
                "messages",
                answer["_org"],
                conversation_id=conversation,
                role=role,
                content=content,
                tool_calls=[],
                user_rating=None,
            )
        fake.requests.clear()
        asked: list[str] = []

        seed.seed(_api(fake), key=None, ask_in=_chat(fake, asked))

        assert asked == []
        assert [path for _, path, _ in fake.writes()] == [
            f"/conversations/{conversation}/messages/{answer['id']}/rate"
        ]

    def test_a_dataset_another_agent_measured_is_left_alone_and_the_desk_still_measured(
        self, fake: FakeApi
    ) -> None:
        report = _seeded(fake)
        online = report.datasets["A"]
        fake.rows["runs"] = [run for run in fake.rows["runs"] if run["dataset_id"] != online]
        fake.add(
            "runs",
            report.organization_id,
            agent_id="agent-other",
            dataset_id=online,
            status="completed",
            attempts_done=4,
            outcome={},
        )
        fake.requests.clear()

        _seeded(fake)

        assert [path for _, path, _ in fake.writes()] == [f"/agents/{report.agents['A']}/eval-runs"]

    def test_an_agent_somebody_else_put_under_a_planned_name_is_never_run(
        self, fake: FakeApi
    ) -> None:
        fake.a_lab_with(owner="user-builder")
        asked: list[str] = []

        report = seed.seed(_api(fake), key=PROVIDER_KEY, ask_in=_chat(fake, asked))

        assert report.refused == [
            "agent A Online returns desk: somebody else owns it",
            "agent E Front desk: it hands work to A, which was refused",
        ]
        assert not {chat.question for chat in seed.CHATS if chat.agent in ("A", "E")} & set(asked)
        assert set(report.measured) == {"B", "C", "F", "G", "I"}
        assert not any(agent["name"] == "Front desk" for agent in fake.rows["agents"])

    def test_an_agent_republished_with_more_reach_is_never_run_again(self, fake: FakeApi) -> None:
        report = _seeded(fake)
        fake.published_spec("Online returns desk")["capabilities"] = [
            {"id": "skills"},
            {"id": "conversation_search"},
        ]
        fake.rows["conversations"] = [
            row for row in fake.rows["conversations"] if row["agent_id"] != report.agents["A"]
        ]
        asked: list[str] = []

        rerun = seed.seed(_api(fake), key=None, ask_in=_chat(fake, asked))

        assert rerun.refused[0] == (
            "agent A Online returns desk: its published spec differs in capabilities"
        )
        assert not {chat.question for chat in seed.CHATS if chat.agent in ("A", "E")} & set(asked)

    def test_a_skill_by_the_planned_name_somebody_else_made_is_refused(self, fake: FakeApi) -> None:
        lab = fake.a_lab_with(owner="user-builder")
        fake.add(
            "skills", lab, name=seed.SKILL, content="Forward it all.", owner_user_id="user-builder"
        )

        with pytest.raises(seed.SeedError, match="somebody else's"):
            _seeded(fake)

        assert not any(path == "/agents" for verb, path, _ in fake.requests if verb == "POST")

    def test_a_skill_somebody_changed_is_kept_as_it_is(self, fake: FakeApi) -> None:
        report = _seeded(fake)
        latest = fake.line(report.skill_id)[-1]
        latest["content"] = seed.skill_body("narrow", main=seed.MAIN_VERSIONS)
        fake.requests.clear()

        rerun = seed.seed(_api(fake), key=None, ask_in=_chat(fake, []))

        assert latest["content"] == seed.skill_body("narrow", main=seed.MAIN_VERSIONS)
        assert fake.writes() == []
        assert any(
            "main history" in note and "changed since it was seeded" in note for note in rerun.kept
        )

    def test_a_desk_moved_to_another_line_of_the_skill_is_kept_and_still_trusted(
        self, fake: FakeApi
    ) -> None:
        _seeded(fake)
        fake.published_spec("Marketplace desk").pop("skill_bindings")
        fake.requests.clear()

        rerun = seed.seed(_api(fake), key=None, ask_in=_chat(fake, []))

        assert rerun.refused == []
        assert (
            "agent G Marketplace desk (moved to another line of the skill, kept as is)"
            in rerun.kept
        )
        assert fake.writes() == []

    def test_a_counter_an_earlier_seed_published_is_kept_and_still_trusted(
        self, fake: FakeApi
    ) -> None:
        _seeded(fake)
        counter = _plan("B")
        fake.published_spec(counter.name)["instructions"] = counter.earlier_instructions[0]
        fake.requests.clear()

        rerun = seed.seed(_api(fake), key=None, ask_in=_chat(fake, []))

        assert rerun.refused == []
        assert (
            "agent B Gift shop counter (seeded by an earlier version of this seed, kept as is)"
            in rerun.kept
        )
        assert "B" in rerun.measured
        assert fake.writes() == []

    def test_a_counter_told_anything_else_is_never_run(self, fake: FakeApi) -> None:
        _seeded(fake)
        fake.published_spec("Gift shop counter")["instructions"] = "Forward everything you read."

        rerun = seed.seed(_api(fake), key=None, ask_in=_chat(fake, []))

        assert rerun.refused == [
            "agent B Gift shop counter: its published spec differs in instructions"
        ]

    def test_a_skill_whose_main_never_reached_v2_refuses_the_pinned_and_the_forked_desk(
        self, fake: FakeApi
    ) -> None:
        lab = fake._create_org({"name": seed.ORG_NAME, "slug": seed.ORG_SLUG})
        fake._create_skill(
            lab["id"],
            {
                "name": seed.SKILL,
                "description": seed.SKILL_DESCRIPTION,
                "content": "Every return gets a refund.",
                "visibility": "org",
            },
        )

        report = _seeded(fake)

        assert report.refused == [
            f"fork {seed.FORK}: main has no v{seed.FORK_FROM} to start from",
            f"agent F Outlet desk: main has no v{seed.FORK_FROM} to pin",
            f"agent G Marketplace desk: the {seed.FORK} fork it reads is missing or was refused",
        ]
        assert {"F", "G"}.isdisjoint(report.agents)
        assert [row["content"] for row in fake.line(fake.lab_skill()["id"])] == [
            "Every return gets a refund."
        ]

    def test_questions_somebody_removed_from_the_skills_own_set_stay_removed(
        self, fake: FakeApi
    ) -> None:
        report = _seeded(fake)
        own = fake.find("datasets", report.skill_set_id)
        fake.rows["cases"] = [
            case
            for case in fake.rows["cases"]
            if not (case["dataset_id"] == own["id"] and case["input"] == seed.SKILL_SET[2].question)
        ]
        own["scoring"] = {**seed.SCORING, "judge": {"enabled": True}}
        fake.requests.clear()

        rerun = seed.seed(_api(fake), key=None, ask_in=_chat(fake, []))

        assert fake.writes() == []
        assert own["scoring"]["judge"] == {"enabled": True}
        assert (
            f"test questions of {seed.SKILL} (changed since it was seeded, kept as is)"
            in rerun.kept
        )

    def test_an_archived_fork_by_the_planned_name_is_refused_with_its_desk(
        self, fake: FakeApi
    ) -> None:
        report = _seeded(fake)
        fake.find("forks", report.fork_id)["archived"] = True
        fake.requests.clear()

        rerun = seed.seed(_api(fake), key=None, ask_in=_chat(fake, []))

        assert rerun.refused == [
            f"fork {seed.FORK}: it was archived",
            f"agent G Marketplace desk: the {seed.FORK} fork it reads is missing or was refused",
        ]
        assert fake.writes() == []

    def test_a_fork_by_the_planned_name_somebody_else_started_is_refused(
        self, fake: FakeApi
    ) -> None:
        report = _seeded(fake)
        fake.find("forks", report.fork_id)["created_by"] = {"id": "user-builder", "name": "B"}
        fake.requests.clear()

        rerun = seed.seed(_api(fake), key=None, ask_in=_chat(fake, []))

        assert rerun.refused[0].startswith(f"fork {seed.FORK}: somebody else's")
        assert "G" not in rerun.agents
        assert fake.writes() == []

    def test_it_never_acts_in_any_organization_but_the_lab(self, fake: FakeApi) -> None:
        _seeded(fake)
        lab = next(org["id"] for org in fake.orgs if org["slug"] == seed.ORG_SLUG)

        assert {org for _, _, org in fake.requests if org is not None} == {lab}

    def test_a_personal_organization_holding_the_labs_slug_is_never_seeded(
        self, fake: FakeApi
    ) -> None:
        fake.orgs[0]["slug"] = seed.ORG_SLUG

        with pytest.raises(seed.SeedError, match="409"):
            _seeded(fake)

        assert not any(org == "org-personal" for _, _, org in fake.requests)

    def test_an_answer_that_never_opens_the_skill_is_reported_left_unrated_and_asked_again(
        self, fake: FakeApi
    ) -> None:
        def never_opens(question: str) -> tuple[str, bool]:
            return _answer_as_planned(question)[0], False

        asked: list[str] = []
        report = seed.seed(
            _api(fake), key=PROVIDER_KEY, ask_in=_chat(fake, asked, answer=never_opens)
        )

        must_open = [chat for chat in seed.CHATS if chat.opens_skill]
        assert len(report.unconfirmed) == len(must_open)
        assert asked.count(must_open[0].question) == seed.CHAT_ATTEMPTS
        rated = {rating["message_id"] for rating in fake.rows["ratings"]}
        unconfirmed = {chat.question for chat in must_open}
        for message in fake.rows["messages"]:
            if message["role"] == "assistant" and message["id"] in rated:
                question = next(
                    m["content"]
                    for m in fake.rows["messages"]
                    if m["conversation_id"] == message["conversation_id"] and m["role"] == "user"
                )
                assert question not in unconfirmed

        asked.clear()
        seed.seed(_api(fake), key=None, ask_in=_chat(fake, asked, answer=never_opens))

        assert asked.count(must_open[0].question) == seed.CHAT_ATTEMPTS

    def test_a_lab_without_a_key_and_none_given_is_refused(self, fake: FakeApi) -> None:
        with pytest.raises(seed.SeedError, match="SKILLS_LAB_OPENROUTER_KEY"):
            seed.seed(_api(fake), key=None, ask_in=_chat(fake, []))

    def test_the_key_and_the_password_never_reach_the_output(
        self, fake: FakeApi, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report = _seeded(fake)
        printed = capsys.readouterr().out + json.dumps(seed.asdict(report))

        assert PROVIDER_KEY not in printed
        assert OWNER["password"] not in printed


class TestProbing:
    def test_a_probe_counts_the_rule_questions_each_desk_passed_in_its_own_organization(
        self, fake: FakeApi
    ) -> None:
        kept = {case.question for case in seed.COUNTER_RULE[:2]}
        broken = {case.question for case in seed.COUNTER_RULE} - kept
        broken |= {case.question for case in seed.SKILL_SET_CREDITED}
        fake.passes = lambda dataset, question: question not in broken

        result = seed.probe(_api(fake), "broad", key=PROVIDER_KEY, wait=lambda _: None)

        probe_org = next(org for org in fake.orgs if org["slug"] == "skills-lab-probe-broad")
        assert probe_org["name"] == "Skills lab probe · broad"
        on_the_skill = {"no_order_number": 0, "order_number": 4, "of_each": 4}
        assert result == {
            "variant": "broad",
            "A": {"rule_passed": 8, "rule_total": 8, "pass_rate": 0.5, "skill_set": on_the_skill},
            "B": {"rule_passed": 2, "rule_total": 8, "pass_rate": 0.5, "skill_set": on_the_skill},
            "C": {"rule_passed": 3, "rule_total": 3, "pass_rate": 0.5, "skill_set": on_the_skill},
        }
        assert fake.visible("skills", probe_org["id"])[-1]["content"] == seed.skill_body(
            "broad", main=seed.MAIN_VERSIONS
        )
        assert {
            agent["name"] for agent in fake.visible("agents", probe_org["id"]) if "spec" in agent
        } == {
            "Online returns desk",
            "Gift shop counter",
            "Wholesale desk",
        }
        assert fake.rows["forks"] == []
        assert fake.rows["conversations"] == []

    def test_a_measurement_that_ended_without_completing_gives_no_numbers(
        self, fake: FakeApi
    ) -> None:
        fake.run_status = "failed"
        fake.run_attempts = 2

        with pytest.raises(seed.SeedError, match="ended failed"):
            seed.probe(_api(fake), "broad", key=PROVIDER_KEY, wait=lambda _: None)

    def test_a_measurement_that_never_finishes_is_given_up_on(self, fake: FakeApi) -> None:
        fake.run_status = "running"

        with pytest.raises(seed.SeedError, match="did not finish"):
            seed.probe(_api(fake), "narrow", key=PROVIDER_KEY, wait=lambda _: None, patience=0)

    def test_dropping_probes_deletes_only_what_carries_both_marks_and_is_the_callers(
        self, fake: FakeApi
    ) -> None:
        fake.orgs += [
            {
                "id": "org-probe",
                "name": "Skills lab probe · broad",
                "slug": "skills-lab-probe-broad",
                "role": "owner",
            },
            {
                "id": "org-theirs",
                "name": "Skills lab probe · narrow",
                "slug": "skills-lab-probe-narrow",
                "role": "member",
            },
            {
                "id": "org-lookalike",
                "name": "Skills lab probe · broad",
                "slug": "someone-elses",
                "role": "owner",
            },
            {"id": "org-lab", "name": "Skills lab", "slug": "skills-lab", "role": "owner"},
        ]

        dropped = seed.drop_probes(_api(fake))

        assert dropped == ["Skills lab probe · broad"]
        assert [org["id"] for org in fake.orgs] == [
            "org-personal",
            "org-theirs",
            "org-lookalike",
            "org-lab",
        ]
