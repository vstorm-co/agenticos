"""The Skills lab seed: its data says what the shared-skill journey needs, and running it twice changes nothing.

The seed is a console tool outside the backend package, imported by path the way
`test_loadtest_harness.py` reaches `loadtest/`. Nothing here talks to a deployment:
the API is an in-memory fake behind `httpx.MockTransport`, and the claim that one
wording of the skill breaks agent B is held by the scorer the evals themselves use.
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
        assert len(_plan("A").cases) == len(_plan("B").cases) == 16

    def test_the_online_desks_rule_questions_carry_an_order_number_and_the_counters_do_not(
        self,
    ) -> None:
        assert all(re.search(r"\b\d{5}\b", case.question) for case in seed.ONLINE_RULE)
        assert not any("order" in case.question.lower() for case in seed.COUNTER_RULE)

    def test_the_wordings_differ_in_rule_two_alone(self) -> None:
        base = seed.skill_body("v1").splitlines()
        for variant in ("broad", "narrow"):
            other = seed.skill_body(variant).splitlines()
            assert len(other) == len(base)
            differing = [line for line, theirs in zip(base, other) if line != theirs]
            assert differing == [seed.RULE_TWO["v1"]]

    def test_no_agent_is_told_about_the_skill(self) -> None:
        for plan in seed.AGENTS:
            assert seed.SKILL not in plan.instructions
            assert "skill" not in plan.instructions.lower()

    def test_who_binds_the_skill_and_who_delegates(self) -> None:
        assert {plan.key for plan in seed.AGENTS if plan.binds_skill} == {"A", "B", "C"}
        assert {plan.key for plan in seed.AGENTS if plan.dataset} == {"A", "B"}
        assert _plan("E").delegates_to == "A"

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
    """What each wording of rule 2 does to A and B, scored as an eval scores it.

    A model following v1 answers both shops' receiptless customers with store
    credit; `broad` refunds both; `narrow` refunds the customer with an order
    number and still credits the one without.
    """

    ANSWERS = {
        "v1": {"A": STORE_CREDIT, "B": STORE_CREDIT},
        "broad": {"A": REFUND, "B": REFUND},
        "narrow": {"A": REFUND, "B": STORE_CREDIT},
    }

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
    """The parts of the HTTP API the seed calls, kept in memory, every request recorded."""

    def __init__(self) -> None:
        self._ids = count(1)
        self.orgs: list[dict[str, Any]] = [
            {"id": "org-personal", "name": "Personal", "slug": "personal"}
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
            )
        }
        self.requests: list[tuple[str, str, str | None]] = []
        self.pass_rate = 0.5

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

        routes: list[tuple[str, str, Callable[..., Any]]] = [
            ("POST", r"/auth/login", lambda: {"access_token": "token"}),
            ("GET", r"/orgs", lambda: {"items": self.orgs, "total": len(self.orgs)}),
            ("POST", r"/orgs", lambda: self._create_org(body)),
            ("PATCH", r"/orgs/(?P<key>[^/]+)", lambda key: {"id": key}),
            ("DELETE", r"/orgs/(?P<key>[^/]+)", lambda key: self._delete_org(key)),
            ("GET", r"/providers/model-profiles", lambda: items(self.visible("profiles", org))),
            ("POST", r"/providers/model-profiles", lambda: self.add("profiles", org, **body)),
            (
                "GET",
                r"/secrets",
                lambda: items(
                    [
                        r
                        for r in self.visible("secrets", org)
                        if r["purpose"] == params.get("purpose")
                    ]
                ),
            ),
            (
                "POST",
                r"/secrets",
                lambda: self.add("secrets", org, name=body["name"], purpose=body["purpose"]),
            ),
            ("GET", r"/agents", lambda: items(self._agents(org, params.get("kind")))),
            (
                "POST",
                r"/agents/system",
                lambda: self.add("agents", org, kind=body["kind"], name=body["name"]),
            ),
            ("POST", r"/agents", lambda: self._create_agent(org, body)),
            ("GET", r"/agents/(?P<key>[^/]+)", lambda key: self.find("agents", key)),
            ("POST", r"/agents/(?P<key>[^/]+)/publish", lambda key: self._publish(key)),
            (
                "POST",
                r"/agents/(?P<key>[^/]+)/eval-runs",
                lambda key: self._start_run(org, key, body),
            ),
            ("GET", r"/eval-runs/(?P<key>[^/]+)", lambda key: self.find("runs", key)),
            ("GET", r"/skills", lambda: items(self.visible("skills", org))),
            ("POST", r"/skills", lambda: self.add("skills", org, **body)),
            ("GET", r"/skills/(?P<key>[^/]+)", lambda key: self.find("skills", key)),
            (
                "GET",
                r"/datasets",
                lambda: items(
                    [r for r in self.visible("datasets", org) if r["name"] == params.get("q")]
                ),
            ),
            ("POST", r"/datasets", lambda: self.add("datasets", org, case_count=0, **body)),
            ("PUT", r"/datasets/(?P<key>[^/]+)/scoring", lambda key: self.find("datasets", key)),
            ("POST", r"/datasets/(?P<key>[^/]+)/cases", lambda key: self._add_case(org, key, body)),
            (
                "GET",
                r"/datasets/(?P<key>[^/]+)/eval-runs",
                lambda key: items([r for r in self.visible("runs", org) if r["dataset_id"] == key]),
            ),
            (
                "GET",
                r"/conversations",
                lambda: items(
                    [
                        r
                        for r in self.visible("conversations", org)
                        if r["agent_id"] == params.get("agent_id")
                    ]
                ),
            ),
            (
                "GET",
                r"/conversations/(?P<key>[^/]+)/messages",
                lambda key: items(
                    [r for r in self.visible("messages", org) if r["conversation_id"] == key]
                ),
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

    def _create_org(self, body: dict[str, Any]) -> dict[str, Any]:
        org = {"id": self.new_id("org"), "name": body["name"], "slug": body["slug"]}
        self.orgs.append(org)
        return org

    def _delete_org(self, org_id: str) -> None:
        self.orgs = [org for org in self.orgs if org["id"] != org_id]

    def _agents(self, org: str | None, kind: str | None) -> list[dict[str, Any]]:
        return [
            row for row in self.visible("agents", org) if kind is None or row.get("kind") == kind
        ]

    def _create_agent(self, org: str | None, body: dict[str, Any]) -> dict[str, Any]:
        spec = body["spec"]
        return self.add(
            "agents", org, kind="agent", name=spec["name"], spec=spec, current_version_id=None
        )

    def _publish(self, agent_id: str) -> dict[str, Any]:
        agent = self.find("agents", agent_id)
        agent["current_version_id"] = self.new_id("version")
        return agent

    def _add_case(self, org: str | None, dataset_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.find("datasets", dataset_id)["case_count"] += 1
        return self.add("cases", org, dataset_id=dataset_id, **body)

    def _start_run(self, org: str | None, agent_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.add(
            "runs",
            org,
            agent_id=agent_id,
            dataset_id=body["dataset_id"],
            status="completed",
            outcome={"candidate_pass_rate": self.pass_rate},
        )

    def _rate(self, org: str | None, message_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.find("messages", message_id)["user_rating"] = body["rating"]
        return self.add("ratings", org, message_id=message_id, **body)

    def writes(self) -> list[tuple[str, str, str | None]]:
        return [
            request
            for request in self.requests
            if request[0] != "GET" and request[1] != "/auth/login"
        ]


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


class TestSeeding:
    def test_a_first_run_builds_the_lab_and_rates_what_was_said(self, fake: FakeApi) -> None:
        asked: list[str] = []
        report = seed.seed(_api(fake), key=PROVIDER_KEY, ask_in=_chat(fake, asked))

        assert [org["name"] for org in fake.orgs] == ["Personal", "Skills lab"]
        assert set(report.agents) == {"A", "B", "C", "D", "E"}
        assert set(report.datasets) == set(report.measured) == {"A", "B"}
        assert sorted(asked) == sorted(chat.question for chat in seed.CHATS)
        assert report.unconfirmed == []
        assert report.rated_down == sum(1 for chat in seed.CHATS if chat.rating == -1)
        assert report.rated_up == sum(1 for chat in seed.CHATS if chat.rating == 1)
        assert report.skill_opened == sum(1 for chat in seed.CHATS if chat.opens_skill)

    def test_the_skill_is_bound_where_planned_and_the_front_desk_pins_the_returns_desk(
        self, fake: FakeApi
    ) -> None:
        report = seed.seed(_api(fake), key=PROVIDER_KEY, ask_in=_chat(fake, []))

        specs = {agent["name"]: agent["spec"] for agent in fake.rows["agents"] if "spec" in agent}
        bound = {name for name, spec in specs.items() if spec.get("skill_ids") == [report.skill_id]}
        assert bound == {"Online returns desk", "Gift shop counter", "Wholesale desk"}
        returns_desk = fake.find("agents", report.agents["A"])
        assert specs["Front desk"]["subagents"] == [
            {"agent_id": returns_desk["id"], "agent_version_id": returns_desk["current_version_id"]}
        ]
        assert all(agent["current_version_id"] for agent in fake.rows["agents"] if "spec" in agent)

    def test_running_it_again_writes_nothing_and_asks_nothing(self, fake: FakeApi) -> None:
        seed.seed(_api(fake), key=PROVIDER_KEY, ask_in=_chat(fake, []))
        fake.requests.clear()
        asked: list[str] = []

        report = seed.seed(_api(fake), key=None, ask_in=_chat(fake, asked))

        assert fake.writes() == []
        assert asked == []
        assert report.created == []
        assert report.rated_down == sum(1 for chat in seed.CHATS if chat.rating == -1)

    def test_a_skill_somebody_changed_is_kept_as_it_is(self, fake: FakeApi) -> None:
        seed.seed(_api(fake), key=PROVIDER_KEY, ask_in=_chat(fake, []))
        fake.rows["skills"][0]["content"] = seed.skill_body("narrow")

        report = seed.seed(_api(fake), key=None, ask_in=_chat(fake, []))

        assert fake.rows["skills"][0]["content"] == seed.skill_body("narrow")
        assert any("changed since it was seeded" in note for note in report.kept)

    def test_it_never_acts_in_any_organization_but_the_lab(self, fake: FakeApi) -> None:
        seed.seed(_api(fake), key=PROVIDER_KEY, ask_in=_chat(fake, []))
        lab = next(org["id"] for org in fake.orgs if org["slug"] == seed.ORG_SLUG)

        assert {org for _, _, org in fake.requests if org is not None} == {lab}

    def test_an_answer_that_never_opens_the_skill_is_reported_and_left_unrated(
        self, fake: FakeApi
    ) -> None:
        asked: list[str] = []
        report = seed.seed(
            _api(fake),
            key=PROVIDER_KEY,
            ask_in=_chat(fake, asked, answer=lambda q: (_answer_as_planned(q)[0], False)),
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

    def test_a_lab_without_a_key_and_none_given_is_refused(self, fake: FakeApi) -> None:
        with pytest.raises(seed.SeedError, match="SKILLS_LAB_OPENROUTER_KEY"):
            seed.seed(_api(fake), key=None, ask_in=_chat(fake, []))

    def test_the_key_and_the_password_never_reach_the_output(
        self, fake: FakeApi, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report = seed.seed(_api(fake), key=PROVIDER_KEY, ask_in=_chat(fake, []))
        printed = capsys.readouterr().out + json.dumps(seed.asdict(report))

        assert PROVIDER_KEY not in printed
        assert OWNER["password"] not in printed


class TestProbing:
    def test_a_probe_measures_its_wording_in_its_own_organization(self, fake: FakeApi) -> None:
        rates = seed.probe(_api(fake), "broad", key=PROVIDER_KEY, wait=lambda _: None)

        probe_org = next(org for org in fake.orgs if org["slug"] == "skills-lab-probe-broad")
        assert probe_org["name"] == "Skills lab probe · broad"
        assert rates == {"variant": "broad", "A": 0.5, "B": 0.5}
        assert fake.visible("skills", probe_org["id"])[0]["content"] == seed.skill_body("broad")
        assert {agent["name"] for agent in fake.visible("agents", probe_org["id"])} == {
            "Online returns desk",
            "Gift shop counter",
        }
        assert fake.rows["conversations"] == []

    def test_dropping_probes_deletes_only_what_carries_both_marks(self, fake: FakeApi) -> None:
        fake.orgs += [
            {
                "id": "org-probe",
                "name": "Skills lab probe · broad",
                "slug": "skills-lab-probe-broad",
            },
            {"id": "org-lookalike", "name": "Skills lab probe · broad", "slug": "someone-elses"},
            {"id": "org-lab", "name": "Skills lab", "slug": "skills-lab"},
        ]

        dropped = seed.drop_probes(_api(fake))

        assert dropped == ["Skills lab probe · broad"]
        assert [org["id"] for org in fake.orgs] == ["org-personal", "org-lookalike", "org-lab"]
