"""Seed the Skills lab organization: one skill that several agents share.

Improving a shared skill can only be clicked through where a skill is bound by
more than one agent, those agents have test questions and rated answers, and
the answers show the model opening the skill. No deployment has that by
accident, so this builds it:

- `returns-policy`, Acme's return rules, as a skill.
- **A**, an online returns desk, and **B**, a gift-shop counter, both bind it.
  Each has sixteen test questions graded by checks, measured once.
- **C**, a wholesale desk, binds it with no test questions: the agent a check
  can only report as unknown.
- **D**, an onboarding helper, does not bind it, so nothing it answers is the
  skill's evidence.
- **E**, a front desk, binds nothing and hands return questions to A, so the
  skill is opened by the agent it delegated to.

No agent's instructions mention the skill. The model opens it from its
description, as it would in any organization.

Rule 2 is the one the journey changes. A's customers have an order number and
no receipt, so v1's "store credit only" is what A's people rate down, and A
fails half its questions. The obvious fix, `broad`, drops the receipt rule: it
fixes A and breaks B, whose shop has no order numbers. `narrow` counts an order
number as a receipt and fixes A without touching B. `--probe` measures one
wording on A's and B's questions in an organization of its own, so that claim
is checked on a real model before a phase relies on it.

Built through the HTTP API and the console's own chat socket, never by writing
rows, for the reason `loadtest/seed.py` gives: a fixture assembled behind the
product's validation could show a state the product cannot produce. It creates
only what is missing, and leaves alone every row somebody may have worked on,
so running it again after a click-through keeps their changes. What it does
finish is a step an interrupted run left half done: a dataset that was never
measured gets its missing questions and its grading, and an agent that was
never published is published, and a lab whose settings were never applied gets
them. A conversation it could not confirm is asked again on the next run, at most
twice. It never enters a Personal organization, and never asks or measures an
agent found under a planned name that somebody else owns or whose spec reaches
further than the plan - those are reported as refused.

The owner's login and the provider key come from the environment and are never
printed: `SKILLS_LAB_EMAIL`, `SKILLS_LAB_PASSWORD`, and
`SKILLS_LAB_OPENROUTER_KEY`, which is needed only while the organization has
no key. A first run costs about twenty cents on GPT-4.1 mini.

`make seed-skills-lab SKILLS_LAB_URL=<the stack's API>` seeds, `PROBE=<variant>`
measures a wording instead, and `DROP_PROBES=1` deletes the probe organizations
once their numbers are written down.
"""

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, TypedDict

import httpx
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect
from websockets.typing import Subprotocol

Variant = Literal["v1", "broad", "narrow"]
VARIANTS: tuple[Variant, ...] = ("v1", "broad", "narrow")
AgentKey = Literal["A", "B", "C", "D", "E"]

ORG_NAME = "Skills lab"
ORG_SLUG = "skills-lab"
PROBE_NAME = "Skills lab probe · {variant}"
PROBE_SLUG = "skills-lab-probe-{variant}"

SKILL = "returns-policy"
SKILL_DESCRIPTION = (
    "Acme's rules for returns and refunds: time limits, receipts, store credit, digital goods "
    "and refunds over $500. Open it before answering any return, refund or exchange question."
)
VAULT_ENTRY = "OpenRouter"
MODEL_LABEL = "GPT-4.1 mini"
MODEL = "openai/gpt-4.1-mini"
ORG_BUDGET_USD = 10
AGENT_BUDGET_USD = 2

CHAT_ATTEMPTS = 2
CHAT_SECONDS = 240
EVAL_PATIENCE_SECONDS = 900
UNFINISHED = frozenset({"queued", "running"})

JsonObject = dict[str, Any]
"""One JSON object from the API, its fields read by the names the API documents."""

RULE_TWO: dict[Variant, str] = {
    "v1": (
        "2. **Proof of purchase.** With a receipt, refund to the original payment method. "
        "Without a receipt, offer store credit only - never a cash or card refund."
    ),
    "broad": (
        "2. **Proof of purchase.** A receipt is not required: refund every eligible item to "
        "the original payment method."
    ),
    "narrow": (
        "2. **Proof of purchase.** An order number counts as a receipt. With a receipt or an "
        "order number, refund to the original payment method. Without either, offer store "
        "credit only - never a cash or card refund."
    ),
}


def skill_body(variant: Variant) -> str:
    """The skill's text with rule 2 worded as `variant` words it."""
    return "\n".join(
        (
            "# Returns and refunds at Acme",
            "",
            "1. Physical items can be returned within 30 days of delivery or purchase.",
            RULE_TWO[variant],
            "3. Digital goods (e-books, software, gift codes) are not refundable once "
            "downloaded or redeemed.",
            "4. An item damaged on arrival is refundable at any time with a photo of the damage.",
            "5. Refunds above $500 need a manager's approval: log the request and say a manager "
            "replies within 2 business days.",
            "6. Card refunds take 5-7 business days.",
            "",
            "Answer in at most three sentences, and say no plainly when the answer is no.",
        )
    )


class Check(TypedDict):
    type: Literal["contains", "not_contains", "regex"]
    value: str


@dataclass(frozen=True)
class Case:
    question: str
    checks: tuple[Check, ...]


def _regex(pattern: str) -> Check:
    return Check(type="regex", value=pattern)


REFUNDED = (_regex(r"(?i)refund"), Check(type="not_contains", value="store credit"))
CREDITED = (_regex(r"(?i)store credit"),)

GENERAL = (
    Case(
        "I bought a kettle 5 days ago and have the receipt. Can I return it?",
        (_regex(r"(?i)(yes|refund|return)"),),
    ),
    Case(
        "Can I return a jacket I bought 40 days ago? I have the receipt.",
        (_regex(r"(?i)(30 days|cannot|can't|not)"),),
    ),
    Case(
        "I redeemed a gift code last week. Can I get my money back?",
        (_regex(r"(?i)(not|cannot|can't)"),),
    ),
    Case(
        "My $650 espresso machine broke on day one. I have the receipt and photos.",
        (_regex(r"(?i)manager"),),
    ),
    Case(
        "My blender was broken when I opened the box 3 months ago. I have a photo.",
        (_regex(r"(?i)(refund|yes)"),),
    ),
    Case(
        "How many days until a card refund reaches my account?", (_regex(r"5\s*(-|\u2013|to)\s*7"),)
    ),
    Case(
        "I downloaded software yesterday and want a refund.", (_regex(r"(?i)(not|cannot|can't)"),)
    ),
    Case(
        "Can I return a $520 chair I bought 10 days ago? I have the receipt.",
        (_regex(r"(?i)manager"),),
    ),
)

ONLINE_RULE = tuple(
    Case(question, REFUNDED)
    for question in (
        "I lost the receipt for headphones I ordered 12 days ago, order 58213. Can I get my money back?",
        "No receipt, but my order number is 70411. I bought a phone case 5 days ago. Refund please.",
        "Order 66120 arrived 9 days ago and I deleted the confirmation email. Can I return the speaker for a refund?",
        "I can't find the receipt for my keyboard, order 49302, delivered last week. What are my options?",
        "Returning a webcam from order 81277, bought 20 days ago, receipt lost. Will I get a refund to my card?",
        "Order 30958: the charger I bought 3 days ago doesn't fit and I never got a receipt. Refund?",
        "I want to return a mouse from order 55416, 14 days ago. No receipt, just the order number.",
        "Order 92740 was delivered 25 days ago. I lost the receipt for the monitor stand. Can I get a refund?",
    )
)

COUNTER_RULE = tuple(
    Case(question, CREDITED)
    for question in (
        "I lost the receipt for a scented candle I bought here 6 days ago. Can I return it?",
        "I bought a mug 10 days ago but threw away the receipt. What can you do?",
        "No receipt for this photo frame I bought last week. I'd like my money back.",
        "I paid cash for a scarf 4 days ago and lost the receipt. Can I return it?",
        "Can I return a teddy bear I bought 2 weeks ago? I don't have the receipt.",
        "I lost the receipt for a notebook set from 20 days ago. Refund please.",
        "I bought this vase 8 days ago and the receipt is gone. What are my options?",
        "I want to return earrings I bought 12 days ago, without a receipt.",
    )
)


@dataclass(frozen=True)
class AgentPlan:
    key: AgentKey
    name: str
    description: str
    instructions: str
    binds_skill: bool
    delegates_to: AgentKey | None = None
    dataset: str | None = None
    rule: tuple[Case, ...] = ()
    """The questions on rule 2, the ones a wording of it decides."""

    @property
    def cases(self) -> tuple[Case, ...]:
        """Every test question: the rule's, and the general ones each measured desk shares."""
        return self.rule + GENERAL if self.dataset else ()


AGENTS = (
    AgentPlan(
        key="A",
        name="Online returns desk",
        description="Answers return and refund questions for Acme's online shop.",
        instructions=(
            "You are the returns desk of Acme's online shop. Every online order has an order "
            "number, and customers rarely keep the emailed receipt. Never guess a store rule. "
            "Answer in at most three sentences."
        ),
        binds_skill=True,
        dataset="Online returns desk - test questions",
        rule=ONLINE_RULE,
    ),
    AgentPlan(
        key="B",
        name="Gift shop counter",
        description="Answers questions at the counter of Acme's gift shop in the city mall.",
        instructions=(
            "You are the counter of Acme's gift shop in the city mall. Customers pay at the till "
            "and get a paper receipt; there are no online orders and no order numbers. Never "
            "guess a store rule. Answer in at most three sentences."
        ),
        binds_skill=True,
        dataset="Gift shop counter - test questions",
        rule=COUNTER_RULE,
    ),
    AgentPlan(
        key="C",
        name="Wholesale desk",
        description="Answers Acme's business customers who buy in bulk.",
        instructions=(
            "You answer Acme's business customers, who buy in bulk through their account "
            "manager. Every wholesale order has an order number. Never guess a store rule. "
            "Answer in at most three sentences."
        ),
        binds_skill=True,
    ),
    AgentPlan(
        key="D",
        name="Onboarding helper",
        description="Helps new customers set up an account and place a first order.",
        instructions="You help new Acme customers create an account and place their first order. Answer briefly.",
        binds_skill=False,
    ),
    AgentPlan(
        key="E",
        name="Front desk",
        description="Acme's first point of contact, which passes return questions on.",
        instructions=(
            "You are Acme's front desk. Hand every return or refund question to the online "
            "returns desk and pass on its answer. Answer anything else yourself, briefly."
        ),
        binds_skill=False,
        delegates_to="A",
    ),
)

ORDER_NUMBER_IS_A_RECEIPT = (
    "My order number is my receipt - offering only store credit is wrong for an online order."
)


@dataclass(frozen=True)
class ChatPlan:
    """One conversation to hold, and how its answer is rated once it says what is expected.

    `expects` is a pattern the answer has to match before the rating is given, so a
    rating always says something true about the answer it is on. `opens_skill` is
    whether the answer has to show the model opening the skill (True), must not
    (False), or is not checked (None) - a delegated answer opens it in the
    delegate's own run, which this conversation does not carry.
    """

    agent: AgentKey
    question: str
    rating: Literal[1, -1] | None = None
    comment: str | None = None
    expects: str | None = None
    opens_skill: bool | None = None


CHATS = (
    *(
        ChatPlan(
            "A", question, -1, ORDER_NUMBER_IS_A_RECEIPT, r"(?i)store credit", opens_skill=True
        )
        for question in (
            "I don't have a receipt for the earbuds from order 40218, delivered 6 days ago. Can I return them?",
            "Order 77105 came 11 days ago and I lost the receipt for the router. Can I get a refund?",
            "I want my money back for a tablet case, order 23390, bought 2 weeks ago. No receipt.",
            "My order 61544 arrived 4 days ago; there was no receipt in the box. I'd like to return the lamp.",
            "Can I return a smartwatch strap from order 88012 without the receipt? It was 9 days ago.",
            "Order 15876, a USB hub from 18 days ago - receipt gone. Refund to my card please.",
        )
    ),
    ChatPlan(
        "A",
        "I have the receipt for a phone case from order 22831, bought 10 days ago. Can I return it?",
        1,
        expects=r"(?i)refund",
        opens_skill=True,
    ),
    ChatPlan(
        "A",
        "Can I get a refund for an e-book I downloaded yesterday? Order 19044.",
        1,
        expects=r"(?i)(not|cannot|can't)",
        opens_skill=True,
    ),
    *(
        ChatPlan("B", question, 1, expects=r"(?i)store credit", opens_skill=True)
        for question in (
            "I lost the receipt for a candle holder I bought 5 days ago. Can I return it?",
            "No receipt for a wallet I bought here a week ago - can I bring it back?",
            "I bought a puzzle 3 days ago and lost the receipt. What are my options?",
        )
    ),
    ChatPlan(
        "B",
        "What time do you open on Sundays?",
        -1,
        "It did not know our opening hours.",
        opens_skill=False,
    ),
    ChatPlan(
        "C",
        "Our order 7781-W arrived 10 days ago and the receipt is lost. Can we get a refund for the 3 desk lamps?",
        -1,
        "The order number is our receipt - store credit only makes no sense for a wholesale order.",
        expects=r"(?i)store credit",
        opens_skill=True,
    ),
    ChatPlan(
        "C",
        "A $600 projector from order 5520-W is faulty and we have photos. Refund?",
        opens_skill=True,
    ),
    ChatPlan(
        "D",
        "Can I return the speaker I ordered last week?",
        -1,
        "It did not know the return rules.",
        opens_skill=False,
    ),
    ChatPlan(
        "D",
        "How do I reset my password?",
        -1,
        "Too vague - it never said where the reset link is.",
        opens_skill=False,
    ),
    ChatPlan(
        "E",
        "I lost my receipt for headphones from order 61822, bought 8 days ago. Can I get a refund?",
    ),
    ChatPlan("E", "Order 47109: the keyboard arrived 6 days ago and I have no receipt. Refund?"),
)


class SeedError(Exception):
    """A call the seed depends on was refused, or the deployment never answered."""


class Api:
    """The HTTP API as the signed-in owner, signing in again when the access token lapses."""

    def __init__(self, client: httpx.Client, *, email: str, password: str) -> None:
        self._client = client
        self._email = email
        self._password = password
        self.token = self._sign_in()

    def _sign_in(self) -> str:
        try:
            response = self._client.post(
                "/api/v1/auth/login", data={"username": self._email, "password": self._password}
            )
        except httpx.HTTPError as exc:
            raise SeedError(f"The deployment did not answer: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise SeedError(f"Signing in was refused ({response.status_code})")
        return str(response.json()["access_token"])

    def call(
        self,
        method: str,
        path: str,
        *,
        org: str | None = None,
        body: object = None,
        params: Mapping[str, str | int] | None = None,
    ) -> JsonObject:
        """The object a call answers with; an answer with no body reads as an empty one."""
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self.token}"}
            if org is not None:
                headers["X-Organization-Id"] = org
            try:
                response = self._client.request(
                    method, f"/api/v1{path}", headers=headers, json=body, params=params
                )
            except httpx.HTTPError as exc:
                raise SeedError(f"{method} {path}: no answer ({type(exc).__name__})") from exc
            if response.status_code == 401 and attempt == 1:
                self.token = self._sign_in()
                continue
            if response.status_code >= 300:
                raise SeedError(f"{method} {path}: {response.status_code} {response.text[:300]}")
            return response.json() if response.content else {}
        raise SeedError(f"{method} {path}: still unauthorized after signing in again")

    def items(
        self,
        path: str,
        *,
        org: str | None = None,
        params: Mapping[str, str | int] | None = None,
    ) -> list[JsonObject]:
        """The `items` of a list the API answers with."""
        return list(self.call("GET", path, org=org, params=params)["items"])


Ask = Callable[[str, str], str]
"""Ask an agent (by id) one question in a new conversation; answers the conversation's id."""


def socket_chat(api: Api, base_url: str, organization_id: str) -> Ask:
    """Chat the way the console does, over the agent socket, so each run is a web run."""
    url = re.sub(r"^http", "ws", base_url.rstrip("/"))
    address = f"{url}/api/v1/ws/agent?organization_id={organization_id}"

    def ask(agent_id: str, question: str) -> str:
        protocols = [Subprotocol(f"access_token.{api.token}"), Subprotocol("chat")]
        try:
            with connect(address, subprotocols=protocols, max_size=None, open_timeout=30) as socket:
                socket.send(json.dumps({"message": question, "agent_id": agent_id}))
                while True:
                    frame = json.loads(socket.recv(timeout=CHAT_SECONDS))
                    if frame.get("type") == "complete":
                        return str(frame["data"]["conversation_id"])
                    if frame.get("type") == "error":
                        message = (frame.get("data") or {}).get("message")
                        raise SeedError(f"The chat was refused: {message}")
        except (TimeoutError, OSError, WebSocketException) as exc:
            raise SeedError(f"The chat broke off: {type(exc).__name__}") from exc

    return ask


@dataclass
class Report:
    """What the run found and did, printed as one JSON line at the end."""

    organization_id: str = ""
    skill_id: str = ""
    agents: dict[str, str] = field(default_factory=dict)
    datasets: dict[str, str] = field(default_factory=dict)
    measured: dict[str, str] = field(default_factory=dict)
    created: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    finished: list[str] = field(default_factory=list)
    rated_down: int = 0
    rated_up: int = 0
    skill_opened: int = 0
    unconfirmed: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)

    def note(self, what: str, *, made: bool) -> None:
        (self.created if made else self.kept).append(what)
        print(f"{'created' if made else 'found'} {what}")

    def finish(self, what: str) -> None:
        self.finished.append(what)
        print(f"finished {what}")

    def refuse(self, what: str) -> None:
        self.refused.append(what)
        print(f"refused {what}")


def ensure_org(api: Api, *, name: str, slug: str, report: Report) -> tuple[str, bool, JsonObject]:
    """The organization with `slug`, whether it was created now, and its row as listed.

    A Personal organization's slug comes from its owner's email, so it can be `slug`
    too; it is never the one meant, and creating ours then fails on the taken slug
    rather than seeding into somebody's own space.
    """
    for org in api.items("/orgs"):
        if org.get("slug") == slug and not org.get("is_personal"):
            report.note(f"organization {name}", made=False)
            return str(org["id"]), False, org
    org = api.call("POST", "/orgs", body={"name": name, "slug": slug})
    report.note(f"organization {name}", made=True)
    return str(org["id"]), True, org


def ensure_model(api: Api, org: str, *, key: str | None, report: Report) -> str:
    """The model the agents run on. Creating the organization's first one also publishes the
    system agents it was seeded with, the judge and the improver among them."""
    for profile in api.items("/providers/model-profiles", org=org):
        if profile.get("label") == MODEL_LABEL:
            report.note(f"model {MODEL_LABEL}", made=False)
            return str(profile["id"])
    secrets = api.items("/secrets", org=org, params={"purpose": "openrouter"})
    secret = next((row for row in secrets if row.get("name") == VAULT_ENTRY), None)
    if secret is None:
        if not key:
            raise SeedError("The organization has no OpenRouter key: set SKILLS_LAB_OPENROUTER_KEY")
        secret = api.call(
            "POST",
            "/secrets",
            org=org,
            body={
                "name": VAULT_ENTRY,
                "purpose": "openrouter",
                "value": {"kind": "api_key", "api_key": key},
            },
        )
        report.note("the OpenRouter entry in the vault", made=True)
    profile = api.call(
        "POST",
        "/providers/model-profiles",
        org=org,
        body={
            "label": MODEL_LABEL,
            "provider": "openrouter",
            "model": MODEL,
            "secret_id": secret["id"],
        },
    )
    report.note(f"model {MODEL_LABEL}", made=True)
    return str(profile["id"])


def ensure_skill(api: Api, org: str, *, variant: Variant, me: str, report: Report) -> str:
    """The skill, ours: one by that name somebody else created is refused rather than bound,
    since every planned agent would read its text."""
    for row in api.items("/skills", org=org, params={"q": SKILL}):
        if row.get("name") != SKILL:
            continue
        found = api.call("GET", f"/skills/{row['id']}", org=org)
        if str(found.get("owner_user_id")) != me:
            raise SeedError(f"A skill named {SKILL} in this organization is somebody else's")
        changed = found.get("content") != skill_body(variant)
        report.note(
            f"skill {SKILL}{' (changed since it was seeded, kept as is)' if changed else ''}",
            made=False,
        )
        return str(row["id"])
    skill = api.call(
        "POST",
        "/skills",
        org=org,
        body={
            "name": SKILL,
            "description": SKILL_DESCRIPTION,
            "content": skill_body(variant),
            "visibility": "org",
        },
    )
    report.note(f"skill {SKILL}", made=True)
    return str(skill["id"])


def agent_spec(
    plan: AgentPlan, *, model: str, skill: str, delegate: tuple[str, str] | None = None
) -> JsonObject:
    """The spec `plan` publishes. `delegate` is the (agent, version) it may hand work to."""
    capabilities: list[dict[str, str]] = []
    spec: JsonObject = {
        "name": plan.name,
        "description": plan.description,
        "instructions": plan.instructions,
        "model_profile_id": model,
        "budget": {"monthly_usd": AGENT_BUDGET_USD},
        "capabilities": capabilities,
    }
    if plan.binds_skill:
        capabilities.append({"id": "skills"})
        spec["skill_ids"] = [skill]
    if delegate is not None:
        capabilities.append({"id": "subagents"})
        spec["subagents"] = [{"agent_id": delegate[0], "agent_version_id": delegate[1]}]
    return spec


REACH = ("collection_ids", "context_ids", "mcp_servers", "external_agents", "reviewers")
"""Spec fields that let an agent read or call something; the seed's agents use none of them."""


def differences(spec: JsonObject, planned: JsonObject) -> list[str]:
    """The fields in which `spec` reaches or says more than `planned`, the spec the seed publishes."""
    found = [
        name
        for name in ("instructions", "model_profile_id")
        if str(spec.get(name) or "") != str(planned.get(name) or "")
    ]
    if [str(x) for x in spec.get("skill_ids") or ()] != [
        str(x) for x in planned.get("skill_ids") or ()
    ]:
        found.append("skill_ids")
    capabilities = sorted(str(c.get("id")) for c in spec.get("capabilities") or ())
    if capabilities != sorted(c["id"] for c in planned["capabilities"]):
        found.append("capabilities")
    delegates = [str(ref.get("agent_id")) for ref in spec.get("subagents") or ()]
    if delegates != [str(ref["agent_id"]) for ref in planned.get("subagents") or ()]:
        found.append("subagents")
    found += [name for name in REACH if spec.get(name)]
    if (spec.get("code_mode") or {}).get("enabled"):
        found.append("code_mode")
    return found


def distrust(api: Api, org: str, agent_id: str, planned: JsonObject, *, me: str) -> str | None:
    """Why an agent found under a planned name must not be run as the seed's, if it must not.

    The seed asks and measures as the signed-in owner, so an agent somebody else owns, or
    one whose spec gained a model, a capability or a reach the plan does not give it, could
    read what the owner may read. Its published version is what would run; an agent never
    published is judged by its draft, which publishing would freeze.
    """
    agent = api.call("GET", f"/agents/{agent_id}", org=org)
    if str(agent.get("owner_user_id")) != me:
        return "somebody else owns it"
    version = agent.get("current_version_id")
    spec = (
        api.call("GET", f"/agents/{agent_id}/versions/{version}", org=org).get("spec") or {}
        if version
        else agent.get("draft_spec") or {}
    )
    changed = differences(spec, planned)
    if not changed:
        return None
    return f"its {'published' if version else 'draft'} spec differs in {', '.join(changed)}"


def ensure_agents(
    api: Api,
    org: str,
    plans: Sequence[AgentPlan],
    *,
    model: str,
    skill: str,
    me: str,
    report: Report,
) -> dict[AgentKey, str]:
    """Each planned agent the seed may run, published.

    One found under a planned name is used only when `distrust` finds nothing, and an agent
    that hands work to a refused one is refused with it; a refused agent is reported, never
    changed, and never asked or measured. One an interrupted run created and never published
    is published now; a published one is left exactly as it is.
    """
    existing = {
        row["name"]: str(row["id"]) for row in api.items("/agents", org=org, params={"limit": 100})
    }
    ids: dict[AgentKey, str] = {}
    for plan in plans:
        label = f"agent {plan.key} {plan.name}"
        if plan.delegates_to is not None and plan.delegates_to not in ids:
            report.refuse(f"{label}: it hands work to {plan.delegates_to}, which was refused")
            continue
        delegate = None
        if plan.delegates_to is not None:
            target = ids[plan.delegates_to]
            delegate = (
                target,
                str(api.call("GET", f"/agents/{target}", org=org)["current_version_id"]),
            )
        planned = agent_spec(plan, model=model, skill=skill, delegate=delegate)
        agent_id = existing.get(plan.name)
        if agent_id is None:
            agent_id = str(api.call("POST", "/agents", org=org, body={"spec": planned})["id"])
            report.note(label, made=True)
        else:
            reason = distrust(api, org, agent_id, planned, me=me)
            if reason is not None:
                report.refuse(f"{label}: {reason}")
                continue
            report.note(label, made=False)
        if api.call("GET", f"/agents/{agent_id}", org=org).get("current_version_id") is None:
            api.call(
                "POST",
                f"/agents/{agent_id}/publish",
                org=org,
                body={"note": "v1: seeded for Skills lab"},
            )
            if existing.get(plan.name) is not None:
                report.finish(f"{label}: published")
        ids[plan.key] = agent_id
        report.agents[plan.key] = agent_id
    return ids


SCORING = {
    "checks": {"enabled": True, "required": True},
    "trajectory": {"enabled": False},
    "judge": {"enabled": False},
    "reference": {"enabled": False},
}


def ensure_dataset(api: Api, org: str, plan: AgentPlan, name: str, *, report: Report) -> str:
    rows = api.items("/datasets", org=org, params={"q": name, "limit": 100})
    found = next((row for row in rows if row.get("name") == name), None)
    if found is not None:
        report.note(f"dataset {name}", made=False)
        return str(found["id"])
    created = api.call(
        "POST",
        "/datasets",
        org=org,
        body={"name": name, "description": f"Test questions for {plan.name}.", "visibility": "org"},
    )
    report.note(f"dataset {name}", made=True)
    return str(created["id"])


def complete_dataset(api: Api, org: str, plan: AgentPlan, dataset: str, *, report: Report) -> None:
    """Give a dataset nothing has measured yet its grading and every question it lacks.

    Only ever called before the first measurement, so a dataset a person has worked on
    since - a question removed, the grading changed - is never touched: once measured,
    it is theirs.
    """
    api.call("PUT", f"/datasets/{dataset}/scoring", org=org, body=SCORING)
    held = {
        row.get("input")
        for row in api.items(f"/datasets/{dataset}/cases", org=org, params={"limit": 100})
    }
    missing = [case for case in plan.cases if case.question not in held]
    for case in missing:
        api.call(
            "POST",
            f"/datasets/{dataset}/cases",
            org=org,
            body={"input": case.question, "checks": list(case.checks)},
        )
    if held and missing:
        report.finish(f"dataset of {plan.key}: {len(missing)} missing questions added")


def measure(
    api: Api, org: str, agents: Mapping[AgentKey, str], *, report: Report
) -> dict[AgentKey, str]:
    """Each agent with test questions: its dataset, and the run measuring the agent on it.

    A run counts once it is under way or has answered a question, whatever it ended in. From
    the first such run on any agent, the dataset is somebody's measurement and is never
    completed again; the seed's own agent is still measured on it when it has no run of its
    own. Runs that ended before answering anything measured nothing, so a dataset with only
    those is completed first. Running a dataset on an agent is also what makes it that
    agent's test set, since a plain dataset names no agent.
    """
    runs: dict[AgentKey, str] = {}
    for plan in AGENTS:
        if plan.dataset is None or plan.key not in agents:
            continue
        agent = agents[plan.key]
        dataset = ensure_dataset(api, org, plan, plan.dataset, report=report)
        report.datasets[plan.key] = dataset
        started = [
            run
            for run in api.items(f"/datasets/{dataset}/eval-runs", org=org, params={"limit": 100})
            if run.get("status") in UNFINISHED or run.get("attempts_done", 0) > 0
        ]
        mine = [run for run in started if str(run.get("agent_id")) == agent]
        if mine:
            report.note(f"measurement of {plan.key}", made=False)
            runs[plan.key] = str(mine[0]["id"])
        else:
            if not started:
                complete_dataset(api, org, plan, dataset, report=report)
            started = api.call(
                "POST",
                f"/agents/{agent}/eval-runs",
                org=org,
                body={"dataset_id": dataset, "reruns": 0},
            )
            report.note(f"measurement of {plan.key}", made=True)
            runs[plan.key] = str(started["id"])
        report.measured[plan.key] = runs[plan.key]
    return runs


@dataclass(frozen=True)
class Transcript:
    conversation_id: str
    question: str
    answer: str
    answer_id: str | None
    rated: bool
    opened_skill: bool


def read_transcript(api: Api, org: str, conversation_id: str) -> Transcript:
    """The conversation's first question and the answer to it.

    Only that turn: a question somebody asked after it is not what a plan rates, so its
    answer and the skill it opened are left out.
    """
    messages = api.items(
        f"/conversations/{conversation_id}/messages", org=org, params={"limit": 100}
    )
    asked = [index for index, message in enumerate(messages) if message.get("role") == "user"]
    if not asked:
        return Transcript(conversation_id, "", "", None, rated=False, opened_skill=False)
    turn = messages[asked[0] + 1 : asked[1] if len(asked) > 1 else len(messages)]
    answers = [m for m in turn if m.get("role") == "assistant" and m.get("content")]
    last = answers[-1] if answers else None
    opened = any(
        call.get("tool_name") == "load_capability" and (call.get("args") or {}).get("id") == SKILL
        for message in turn
        for call in message.get("tool_calls") or ()
    )
    return Transcript(
        conversation_id=conversation_id,
        question=str(messages[asked[0]]["content"]),
        answer=last["content"] if last else "",
        answer_id=str(last["id"]) if last else None,
        rated=bool(last and last.get("user_rating") is not None),
        opened_skill=opened,
    )


def fits(plan: ChatPlan, transcript: Transcript) -> bool:
    """Whether `transcript` is the conversation `plan` describes, so its rating would be true."""
    if transcript.answer_id is None:
        return False
    if plan.opens_skill is not None and transcript.opened_skill != plan.opens_skill:
        return False
    return plan.expects is None or re.search(plan.expects, transcript.answer) is not None


def held_chats(api: Api, org: str, agent: str) -> list[Transcript]:
    rows = api.items("/conversations", org=org, params={"agent_id": agent, "limit": 100})
    return [read_transcript(api, org, str(row["id"])) for row in rows]


def hold_chat(
    api: Api,
    org: str,
    plan: ChatPlan,
    *,
    agent: str,
    held: Sequence[Transcript],
    ask: Ask,
    report: Report,
) -> None:
    """Make sure one conversation `plan` describes exists, rated as it says.

    An earlier run's conversation that fits is used, and rated if it was not yet. Otherwise
    the question is asked again, at most `CHAT_ATTEMPTS` times, since a model's answer
    differs between runs; one that never fits is reported rather than rated untruthfully,
    and the next run asks again.
    """
    candidates = [transcript for transcript in held if transcript.question == plan.question]
    for attempt in range(CHAT_ATTEMPTS + 1):
        fitting = next((transcript for transcript in candidates if fits(plan, transcript)), None)
        if fitting is not None:
            _rate(api, org, plan, fitting, report)
            return
        if attempt == CHAT_ATTEMPTS:
            break
        candidates = [read_transcript(api, org, ask(agent, plan.question))]
    report.unconfirmed.append(f"{plan.agent}: {plan.question}")
    print(f"unconfirmed {plan.agent}: {plan.question} (the next run asks again)")


def _rate(api: Api, org: str, plan: ChatPlan, transcript: Transcript, report: Report) -> None:
    if transcript.opened_skill:
        report.skill_opened += 1
    if plan.rating is None:
        return
    if not transcript.rated:
        body: JsonObject = {"rating": plan.rating}
        if plan.comment:
            body["comment"] = plan.comment
        api.call(
            "POST",
            f"/conversations/{transcript.conversation_id}/messages/{transcript.answer_id}/rate",
            org=org,
            body=body,
        )
    if plan.rating < 0:
        report.rated_down += 1
    else:
        report.rated_up += 1


def seed(api: Api, *, key: str | None, ask_in: Callable[[str], Ask]) -> Report:
    """Build Skills lab, or finish building it; `ask_in` opens the chat for an organization."""
    report = Report()
    me = str(api.call("GET", "/users/me")["id"])
    org, made, row = ensure_org(api, name=ORG_NAME, slug=ORG_SLUG, report=report)
    report.organization_id = org
    untouched = not row.get("ai_assistance_enabled") and row.get("monthly_budget_usd") is None
    if made or untouched:
        api.call(
            "PATCH",
            f"/orgs/{org}",
            org=org,
            body={"ai_assistance_enabled": True, "monthly_budget_usd": ORG_BUDGET_USD},
        )
        if not made:
            report.finish("organization settings: AI assistance on, a monthly budget set")
    model = ensure_model(api, org, key=key, report=report)
    skill = ensure_skill(api, org, variant="v1", me=me, report=report)
    report.skill_id = skill
    agents = ensure_agents(api, org, AGENTS, model=model, skill=skill, me=me, report=report)
    measure(api, org, agents, report=report)
    ask = ask_in(org)
    held = {agent_key: held_chats(api, org, agent) for agent_key, agent in agents.items()}
    for chat in CHATS:
        if chat.agent not in agents:
            continue
        hold_chat(
            api, org, chat, agent=agents[chat.agent], held=held[chat.agent], ask=ask, report=report
        )
    return report


def rule_passed(api: Api, org: str, run: JsonObject, plan: AgentPlan) -> int:
    """How many of `plan`'s rule questions the measured answers passed."""
    arm = (run.get("outcome") or {}).get("candidate_arm_id")
    if arm is None:
        raise SeedError(f"The measurement of {plan.key} has no result to read")
    passed = api.items(
        f"/eval-runs/{run['id']}/cases",
        org=org,
        params={"arm_id": str(arm), "outcome": "passed", "limit": 100},
    )
    rule = {case.question for case in plan.rule}
    return sum(1 for case in passed if case.get("input") in rule)


def probe(
    api: Api,
    variant: Variant,
    *,
    key: str | None,
    wait: Callable[[float], None] = time.sleep,
    patience: float = EVAL_PATIENCE_SECONDS,
) -> JsonObject:
    """Measure A and B with rule 2 worded as `variant`, in an organization of its own.

    No conversations: only the skill, the two agents, their questions and one measurement
    each. Against `v1`, `broad` should cost B at least five of its eight rule questions and
    `narrow` at most one, while both win A its eight back - which is why the answer counts
    the rule questions passed rather than the pass rate over all sixteen.
    """
    report = Report()
    me = str(api.call("GET", "/users/me")["id"])
    org, _, _ = ensure_org(
        api,
        name=PROBE_NAME.format(variant=variant),
        slug=PROBE_SLUG.format(variant=variant),
        report=report,
    )
    model = ensure_model(api, org, key=key, report=report)
    skill = ensure_skill(api, org, variant=variant, me=me, report=report)
    measured = [plan for plan in AGENTS if plan.dataset is not None]
    agents = ensure_agents(api, org, measured, model=model, skill=skill, me=me, report=report)
    if report.refused:
        raise SeedError(
            f"The probe organization holds agents the seed did not make: {report.refused}"
        )
    runs = measure(api, org, agents, report=report)
    result: JsonObject = {"variant": variant}
    deadline = time.monotonic() + patience
    for plan in measured:
        run = api.call("GET", f"/eval-runs/{runs[plan.key]}", org=org)
        while run["status"] in UNFINISHED:
            if time.monotonic() > deadline:
                raise SeedError(
                    f"The measurement of {plan.key} did not finish in {patience:.0f} seconds"
                )
            wait(5)
            run = api.call("GET", f"/eval-runs/{runs[plan.key]}", org=org)
        if run["status"] != "completed":
            raise SeedError(
                f"The measurement of {plan.key} ended {run['status']}, so it says nothing "
                "about the wording: drop the probes and measure again"
            )
        result[plan.key] = {
            "rule_passed": rule_passed(api, org, run, plan),
            "rule_total": len(plan.rule),
            "pass_rate": (run.get("outcome") or {}).get("candidate_pass_rate"),
        }
    return result


def drop_probes(api: Api) -> list[str]:
    """Delete the probe organizations the caller owns, recognised by both name and slug."""
    marks = {(PROBE_NAME.format(variant=v), PROBE_SLUG.format(variant=v)) for v in VARIANTS}
    dropped: list[str] = []
    for org in api.items("/orgs"):
        if (org.get("name"), org.get("slug")) not in marks:
            continue
        if org.get("role") != "owner":
            print(f"skipped {org['name']}: only its owner may delete it")
            continue
        api.call("DELETE", f"/orgs/{org['id']}", org=str(org["id"]))
        dropped.append(str(org["name"]))
        print(f"deleted {org['name']}")
    return dropped


def parse(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--url", default=os.environ.get("SKILLS_LAB_URL", "http://localhost:8000"))
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--probe", choices=VARIANTS, help="Measure one wording of rule 2 in its own organization"
    )
    group.add_argument("--drop-probes", action="store_true", help="Delete the probe organizations")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse(argv)
    email = os.environ.get("SKILLS_LAB_EMAIL")
    password = os.environ.get("SKILLS_LAB_PASSWORD")
    if not email or not password:
        print("Set SKILLS_LAB_EMAIL and SKILLS_LAB_PASSWORD to the owner's login.")
        return 2
    key = os.environ.get("SKILLS_LAB_OPENROUTER_KEY") or None
    with httpx.Client(base_url=args.url, timeout=300) as client:
        try:
            api = Api(client, email=email, password=password)
            if args.drop_probes:
                result: object = {"deleted": drop_probes(api)}
            elif args.probe:
                result = probe(api, args.probe, key=key)
            else:
                report = seed(api, key=key, ask_in=lambda org: socket_chat(api, args.url, org))
                result = asdict(report)
        except SeedError as exc:
            print(f"FAILED: {exc}")
            return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
