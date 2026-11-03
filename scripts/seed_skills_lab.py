"""Seed the Skills lab organization: one skill that several agents share.

Improving a shared skill can only be clicked through where a skill is bound by
more than one agent, those agents have test questions and rated answers, and
the answers show the model opening the skill. No deployment has that by
accident, so this builds it:

- `returns-policy`, Acme's return rules, as a skill with a short history: main
  v1 to v3, and a fork, Marketplace, from v2 with two versions of its own that
  touch lines main never does. It also has ten test questions of its own.
- **A**, an online returns desk, **B**, a gift-shop counter, and **C**, a
  wholesale desk, follow main. Each has test questions graded by checks,
  measured once, so the skill-loading ones are a check's sample. B opens the
  skill only on its eight rule questions; its other four are about the shop.
- **D**, an onboarding helper, does not bind it, so nothing it answers is the
  skill's evidence.
- **E**, a front desk, binds nothing and hands return questions to A, so the
  skill is opened by the agent it delegated to.
- **F**, an outlet desk, is pinned on main v2; **G**, a marketplace desk, reads
  the fork. A check on main runs neither, and one on the fork runs only G.
- **H**, a clearance desk, follows main on a monthly budget too small to check.
- **I**, a store info desk, follows main with questions that never open the
  skill, so a check samples it from the skill's own questions only.

No agent's instructions mention the skill. The model opens it from its
description, as it would in any organization.

Rule 2 is the one the journey changes. A's customers have an order number and
no receipt, so v1's "store credit only" is what A's people rate down, and A
fails half its questions. The obvious fix, `broad`, drops the receipt rule: it
fixes A and breaks B, whose shop has no order numbers. `narrow` counts an order
number as a receipt and fixes A without touching B. Both change how every desk
treats the skill's own questions; `gift` is `narrow` plus one sentence that only
the counter's questions ask about - the goods it sells cannot be returned without
a receipt - so it fixes A and C and breaks B alone. `--probe` measures one
wording on A's, B's and C's questions and the skill's own, in an organization
of its own, so that claim is checked on a real model before a phase relies on
it.

Built through the HTTP API and the console's own chat socket, never by writing
rows, for the reason `loadtest/seed.py` gives: a fixture assembled behind the
product's validation could show a state the product cannot produce. It creates
only what is missing, and leaves alone every row somebody may have worked on,
so running it again after a click-through keeps their changes. What it does
finish is a step an interrupted run left half done: a dataset that was never
measured gets its missing questions and its grading, a line of the skill still
holding only the plan's first versions gets the rest, an agent that was never
published is published, and a lab whose settings were never applied gets
them. A conversation it could not confirm is asked again on the next run, at most
twice. It never enters a Personal organization, and never asks or measures an
agent found under a planned name that somebody else owns or whose spec reaches
further than the plan - those are reported as refused.

The owner's login and the provider key come from the environment and are never
printed: `SKILLS_LAB_EMAIL`, `SKILLS_LAB_PASSWORD`, and
`SKILLS_LAB_OPENROUTER_KEY`, which is needed only while the organization has
no key. A first run costs about thirty cents on GPT-4.1 mini.

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
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, TypedDict

import httpx
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect
from websockets.typing import Subprotocol

Variant = Literal["v1", "broad", "narrow", "gift"]
VARIANTS: tuple[Variant, ...] = ("v1", "broad", "narrow", "gift")
AgentKey = Literal["A", "B", "C", "D", "E", "F", "G", "H", "I"]

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

GIFT_GOODS = ("candle", "mug", "vase", "scarf", "teddy bear", "notebook", "earrings")
"""What the counter sells, named in seven of its eight rule questions and in no other
desk's question nor the skill's own."""

FINAL_SALE = "final sale"

RULE_TWO["gift"] = (
    RULE_TWO["narrow"]
    + " Without a receipt, a candle, mug, vase, scarf, teddy bear, notebook or pair of "
    f"earrings is {FINAL_SALE}: it cannot be returned at all."
)


MAIN_VERSIONS = 3
"""Main's planned history: v2 dates the card refund, v3 adds the size exchange."""

FORK = "Marketplace"
FORK_FROM = 2
FORK_VERSIONS = 2
"""The fork starts from main v2; its two versions change rules 1 and 3, lines main never
touches, so catching it up with main's v3 merges without a conflict."""


def skill_body(variant: Variant = "v1", *, main: int = 1, fork: int = 0) -> str:
    """The skill's text: rule 2 worded as `variant`, as main version `main` and fork version
    `fork` of the Marketplace fork (0 for main itself) have it."""
    return "\n".join(
        (
            "# Returns and refunds at Acme",
            "",
            "1. Physical items can be returned within 30 days of delivery or purchase"
            + (
                "; items sold by a marketplace seller are returned to that seller."
                if fork >= 1
                else "."
            ),
            RULE_TWO[variant],
            "3. Digital goods (e-books, software, gift codes) are not refundable once "
            "downloaded or redeemed"
            + ("; marketplace gift codes follow the seller's rules." if fork >= 2 else "."),
            "4. An item damaged on arrival is refundable at any time with a photo of the damage.",
            "5. Refunds above $500 need a manager's approval: log the request and say a manager "
            "replies within 2 business days.",
            "6. Card refunds take 5-7 business days"
            + (" after we receive the item." if main >= 2 else "."),
            *(
                (
                    "7. Clothing can be exchanged once for another size within 30 days, with a receipt.",
                )
                if main >= 3
                else ()
            ),
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
STORE_CREDIT_DENIED = (
    r"(?:\bno|\bor(?: even)?(?: (?:offer|give|provide|issue))?"
    r"|\b(?:can(?:'t| ?not)|(?:un|not )able to|(?:won't|will not)(?: be able to)?|don't|do not)"
    r"(?: even)?(?: (?:offer|give|provide|issue|process))?(?: you)?(?: any)?"
    r"|\bnot(?: be)? eligible for(?: any)?) store credit"
    r"|store credit (?:is |are )?(?:unavailable|not (?:available|possible|an option|offered))"
    r"|store credit (?:isn't|is not|can(?:'t| ?not) be|won't be) "
    r"(?:available|offered|given|issued|possible|an option)"
)
"""The ways an answer names store credit only to deny it."""

CREDITED = (_regex(r"(?i)store credit"), _regex(rf"(?i)^(?![\s\S]*(?:{STORE_CREDIT_DENIED}))"))
"""Store credit offered: named, and not only to say there is none."""

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
    Case(question, (*CREDITED, Check(type="not_contains", value=FINAL_SALE)))
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


WHOLESALE_RULE = tuple(
    Case(question, REFUNDED)
    for question in (
        "Our order 4410-W came 8 days ago and the receipt is missing. Can we return two office chairs for a refund?",
        "Order 9032-W was delivered last week with no receipt on the pallet. We want a refund for the printer.",
        "We lost the receipt for order 6178-W from 12 days ago. Refund for the monitors, please.",
    )
)

OUTLET_RULE = tuple(
    Case(question, REFUNDED)
    for question in (
        "Order 51207 from the outlet shop came 6 days ago and I lost the receipt. Can I get a refund for the jacket?",
        "No receipt for outlet order 38854, bought 10 days ago. I want my money back for the boots.",
        "Outlet order 27631 arrived 3 days ago without a receipt. Refund the backpack, please.",
    )
)

TO_THE_SELLER = (_regex(r"(?i)(returned|return it|send it back|goes back) to (that|the) seller"),)

MARKETPLACE_RULE = tuple(
    Case(question, TO_THE_SELLER)
    for question in (
        "I bought a lamp from a marketplace seller on Acme's site 5 days ago. Can I return it to you?",
        "A marketplace seller sent me the wrong phone case. Who takes the return?",
        "Can I bring a rug I bought from a marketplace seller back to an Acme store?",
    )
)

COUNTER_STORE = (
    Case("Do you take online orders?", (_regex(r"(?i)(no|not|don't|do not)"),)),
    Case("How do I pay for what I buy here?", (_regex(r"(?i)(till|counter|checkout)"),)),
    Case("Where in the mall is the shop?", (_regex(r"(?i)(ground floor|entrance)"),)),
    Case("Do you sell gift cards?", (_regex(r"(?i)(yes|we do|counter)"),)),
)
"""Questions the counter answers from its own instructions, none of which the skill is for."""

STORE_INFO = (
    Case("When are you open on Sunday?", (_regex(r"10"),)),
    Case("Is parking free at the mall?", (_regex(r"(?i)(two hours|2 hours|free)"),)),
    Case("Do you wrap presents?", (_regex(r"(?i)free"),)),
    Case("Where do I find the store in the mall?", (_regex(r"(?i)(ground floor|entrance)"),)),
    Case("Can I buy a gift card in the store?", (_regex(r"(?i)(yes|counter)"),)),
)

SKILL_SET_CREDITED = tuple(
    Case(question, CREDITED)
    for question in (
        "I have no receipt for a picture frame I bought in a shop 9 days ago. What can you offer?",
        "I bought a desk lamp in store 2 weeks ago and lost the receipt. Can I bring it back?",
        "I paid cash for a toaster 6 days ago and threw the receipt away. What are my options?",
        "I have no receipt and no order number for a kettle from last week. Can I return it?",
    )
)

SKILL_SET_REFUNDED = tuple(
    Case(question, REFUNDED)
    for question in (
        "Order 73310 arrived 7 days ago and I never got a receipt. Can I return the blender for a refund?",
        "I lost the receipt for order 26475 from 10 days ago. Can I get a refund to my card?",
        "I want to return the shelf from order 84021, bought 3 weeks ago, with no receipt. What happens?",
        "Order 39186: the headphones were delivered 5 days ago and the receipt is gone. Refund please.",
    )
)

SKILL_SET = (
    *SKILL_SET_CREDITED,
    *SKILL_SET_REFUNDED,
    Case(
        "I bought an e-book yesterday and already downloaded it. Can I get a refund?",
        (_regex(r"(?i)(not|cannot|can't)"),),
    ),
    Case(
        "Can you refund a $780 camera I bought 4 days ago? I have the receipt.",
        (_regex(r"(?i)manager"),),
    ),
)
"""The skill's own test questions, graded the same on every agent that binds it: no receipt
and no order number keeps store credit, an order number counts as a receipt."""


Line = Literal["main", "pinned", "fork"]


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
    other: tuple[Case, ...] = GENERAL
    """The rest of its test questions."""
    line: Line = "main"
    """Main, latest; main version `FORK_FROM`, pinned; or the Marketplace fork, latest."""
    budget_usd: float = AGENT_BUDGET_USD
    earlier_instructions: tuple[str, ...] = ()
    """Instructions an earlier version of this seed published. An agent still holding them
    is the seed's, kept as it is: its measured questions are never rewritten, so only a
    fresh lab gets the current ones."""

    @property
    def cases(self) -> tuple[Case, ...]:
        return self.rule + self.other if self.dataset else ()


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
            "You are the counter of Acme's gift shop in the city mall, on the ground floor next "
            "to the main entrance. Customers pay at the till and get a paper receipt; there are "
            "no online orders and no order numbers. Gift cards are sold at the counter. Never "
            "guess a store rule. Answer in at most three sentences."
        ),
        binds_skill=True,
        dataset="Gift shop counter - test questions",
        rule=COUNTER_RULE,
        other=COUNTER_STORE,
        earlier_instructions=(
            "You are the counter of Acme's gift shop in the city mall. Customers pay at the "
            "till and get a paper receipt; there are no online orders and no order numbers. "
            "Never guess a store rule. Answer in at most three sentences.",
        ),
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
        dataset="Wholesale desk - test questions",
        rule=WHOLESALE_RULE,
        other=GENERAL[:3],
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
    AgentPlan(
        key="F",
        name="Outlet desk",
        description="Answers return questions for Acme's outlet web shop.",
        instructions=(
            "You answer customers of Acme's outlet web shop. Every outlet order has an order "
            "number. Never guess a store rule. Answer in at most three sentences."
        ),
        binds_skill=True,
        dataset="Outlet desk - test questions",
        rule=OUTLET_RULE,
        other=GENERAL[3:6],
        line="pinned",
    ),
    AgentPlan(
        key="G",
        name="Marketplace desk",
        description="Answers questions about items sold on Acme's marketplace.",
        instructions=(
            "You answer customers who bought from sellers on Acme's marketplace as well as from "
            "Acme itself. Never guess a store rule. Answer in at most three sentences."
        ),
        binds_skill=True,
        dataset="Marketplace desk - test questions",
        rule=MARKETPLACE_RULE,
        other=GENERAL[5:8],
        line="fork",
    ),
    AgentPlan(
        key="H",
        name="Clearance desk",
        description="Answers questions about Acme's clearance sale.",
        instructions=(
            "You answer customers of Acme's clearance sale. Never guess a store rule. Answer in "
            "at most three sentences."
        ),
        binds_skill=True,
        budget_usd=0.01,
    ),
    AgentPlan(
        key="I",
        name="Store info desk",
        description="Answers practical questions about Acme's mall store.",
        instructions=(
            "You answer practical questions about Acme's store in the city mall. It is open "
            "9:00-21:00 Monday to Saturday and 10:00-18:00 on Sunday, on the ground floor next to "
            "the main entrance. The mall garage is free for two hours, presents are wrapped for "
            "free, and gift cards are sold at the counter. Answer in at most two sentences."
        ),
        binds_skill=True,
        dataset="Store info desk - test questions",
        other=STORE_INFO,
    ),
)

PROBED: tuple[AgentKey, ...] = ("A", "B", "C")
"""The main line's measured desks, the ones a wording of rule 2 is probed on."""

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

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


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
                raise SeedError(
                    f"{method} {path}: {response.status_code} {response.text[:300]}",
                    status=response.status_code,
                )
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

    def find(self, path: str, *, org: str | None = None) -> JsonObject | None:
        """The object at `path`, or None when the API answers that there is none."""
        try:
            return self.call("GET", path, org=org)
        except SeedError as exc:
            if exc.status == 404:
                return None
            raise


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
    fork_id: str = ""
    skill_set_id: str = ""

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


def ensure_skill(api: Api, org: str, *, body: str, me: str, report: Report) -> str:
    """The skill, ours, created with `body` as its first version when there is none.

    One by that name somebody else created is refused rather than bound, since every
    planned agent would read its text.
    """
    for row in api.items("/skills", org=org, params={"q": SKILL}):
        if row.get("name") != SKILL:
            continue
        found = api.call("GET", f"/skills/{row['id']}", org=org)
        if str(found.get("owner_user_id")) != me:
            raise SeedError(f"A skill named {SKILL} in this organization is somebody else's")
        report.note(f"skill {SKILL}", made=False)
        return str(row["id"])
    skill = api.call(
        "POST",
        "/skills",
        org=org,
        body={
            "name": SKILL,
            "description": SKILL_DESCRIPTION,
            "content": body,
            "visibility": "org",
        },
    )
    report.note(f"skill {SKILL}", made=True)
    return str(skill["id"])


def _line_versions(api: Api, org: str, skill: str, fork: str | None = None) -> list[JsonObject]:
    params: dict[str, str | int] = {"limit": 100}
    if fork is not None:
        params["fork_id"] = fork
    rows = api.items(f"/skills/{skill}/versions", org=org, params=params)
    return sorted(rows, key=lambda row: int(row["number"]))


def _extend_line(
    api: Api,
    org: str,
    skill: str,
    *,
    held: Sequence[JsonObject],
    planned: Sequence[str],
    base: str | None,
    fork: str | None,
    label: str,
    report: Report,
) -> list[str]:
    """Save the planned versions a line lacks, after checking the ones it holds are the plan's.

    A line whose versions are not the plan's, or that has more of them, was worked on
    since it was seeded and is left as it is. Answers the line's version ids, oldest first.
    """
    ids = [str(row["id"]) for row in held]
    contents = [
        api.call("GET", f"/skills/{skill}/versions/{vid}", org=org).get("content") for vid in ids
    ]
    if len(held) > len(planned) or contents != list(planned[: len(held)]):
        report.note(f"{label} (changed since it was seeded, kept as is)", made=False)
        return ids
    if len(held) == len(planned):
        report.note(label, made=False)
        return ids
    for content in planned[len(held) :]:
        body: JsonObject = {
            "base_version_id": ids[-1] if ids else base,
            "description": SKILL_DESCRIPTION,
            "content": content,
        }
        if fork is not None:
            body["fork_id"] = fork
        ids.append(str(api.call("POST", f"/skills/{skill}/versions", org=org, body=body)["id"]))
    report.note(label, made=True)
    return ids


def ensure_history(api: Api, org: str, skill: str, *, report: Report) -> list[str]:
    """Main's planned versions, v1 to `MAIN_VERSIONS`; answers their ids, oldest first."""
    planned = [skill_body(main=number) for number in range(1, MAIN_VERSIONS + 1)]
    return _extend_line(
        api,
        org,
        skill,
        held=_line_versions(api, org, skill),
        planned=planned,
        base=None,
        fork=None,
        label=f"main history v1-v{MAIN_VERSIONS}",
        report=report,
    )


def ensure_fork(
    api: Api, org: str, skill: str, main: Sequence[str], *, me: str, report: Report
) -> str | None:
    """The Marketplace fork from main v`FORK_FROM`, with its own planned versions.

    A fork by that name is the seed's only when the signed-in owner made it from that
    version; an archived one, or one somebody else started, is refused, and so is every
    agent that would read it.
    """
    archived = api.items(f"/skills/{skill}/forks", org=org, params={"archived": "true"})
    if any(row.get("name") == FORK for row in archived):
        report.refuse(f"fork {FORK}: it was archived")
        return None
    found = next(
        (row for row in api.items(f"/skills/{skill}/forks", org=org) if row.get("name") == FORK),
        None,
    )
    if found is None:
        if len(main) < FORK_FROM:
            report.refuse(f"fork {FORK}: main has no v{FORK_FROM} to start from")
            return None
        found = api.call(
            "POST",
            f"/skills/{skill}/forks",
            org=org,
            body={"name": FORK, "from_version_id": main[FORK_FROM - 1]},
        )
        report.note(f"fork {FORK}", made=True)
    else:
        made_by = str((found.get("created_by") or {}).get("id"))
        if made_by != me or (found.get("base") or {}).get("number") != FORK_FROM:
            report.refuse(f"fork {FORK}: somebody else's, or not started from main v{FORK_FROM}")
            return None
        report.note(f"fork {FORK}", made=False)
    fork = str(found["id"])
    planned = [skill_body(main=FORK_FROM, fork=number) for number in range(1, FORK_VERSIONS + 1)]
    _extend_line(
        api,
        org,
        skill,
        held=_line_versions(api, org, skill, fork),
        planned=planned,
        base=str((found.get("base") or {}).get("id")),
        fork=fork,
        label=f"versions of fork {FORK}",
        report=report,
    )
    return fork


def agent_spec(
    plan: AgentPlan,
    *,
    model: str,
    skill: str,
    delegate: tuple[str, str] | None = None,
    fork: str | None = None,
) -> JsonObject:
    """The spec `plan` publishes. `delegate` is the (agent, version) it may hand work to, and
    `fork` the fork a plan on the fork line reads."""
    capabilities: list[dict[str, str]] = []
    spec: JsonObject = {
        "name": plan.name,
        "description": plan.description,
        "instructions": plan.instructions,
        "model_profile_id": model,
        "budget": {"monthly_usd": plan.budget_usd},
        "capabilities": capabilities,
    }
    if plan.binds_skill:
        capabilities.append({"id": "skills"})
        spec["skill_ids"] = [skill]
        if plan.line == "pinned":
            spec["skill_bindings"] = [{"skill_id": skill, "version": FORK_FROM}]
        elif plan.line == "fork":
            spec["skill_bindings"] = [{"skill_id": skill, "fork_id": fork}]
    if delegate is not None:
        capabilities.append({"id": "subagents"})
        spec["subagents"] = [{"agent_id": delegate[0], "agent_version_id": delegate[1]}]
    return spec


REACH = ("collection_ids", "context_ids", "mcp_servers", "external_agents", "reviewers")
"""Spec fields that let an agent read or call something; the seed's agents use none of them."""


def _bindings(spec: JsonObject) -> list[tuple[str, str, str]]:
    return sorted(
        (str(row.get("skill_id")), str(row.get("version")), str(row.get("fork_id")))
        for row in spec.get("skill_bindings") or ()
    )


def differences(spec: JsonObject, planned: JsonObject) -> list[str]:
    """The fields in which `spec` reaches or says more than `planned`, the spec the seed publishes.

    Which line of a bound skill it reads is not one: another version or fork of the same
    skill reaches nothing more, and moving an agent there is what the skill page is for.
    """
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


def distrust(
    api: Api,
    org: str,
    agent_id: str,
    planned: JsonObject,
    *,
    me: str,
    earlier: Collection[str] = (),
) -> tuple[str | None, JsonObject]:
    """Why an agent found under a planned name must not be run as the seed's, if it must not,
    and the spec that would run.

    The seed asks and measures as the signed-in owner, so an agent somebody else owns, or
    one whose spec gained a model, a capability or a reach the plan does not give it, could
    read what the owner may read. Its published version is what would run; an agent never
    published is judged by its draft, which publishing would freeze. Instructions in
    `earlier`, an earlier seed's, are the seed's own too.
    """
    agent = api.call("GET", f"/agents/{agent_id}", org=org)
    if str(agent.get("owner_user_id")) != me:
        return "somebody else owns it", {}
    version = agent.get("current_version_id")
    spec = (
        api.call("GET", f"/agents/{agent_id}/versions/{version}", org=org).get("spec") or {}
        if version
        else agent.get("draft_spec") or {}
    )
    changed = differences(spec, planned)
    if changed == ["instructions"] and str(spec.get("instructions")) in earlier:
        changed = []
    if not changed:
        return None, spec
    return f"its {'published' if version else 'draft'} spec differs in {', '.join(changed)}", spec


def ensure_agents(
    api: Api,
    org: str,
    plans: Sequence[AgentPlan],
    *,
    model: str,
    skill: str,
    main: Sequence[str],
    fork: str | None,
    me: str,
    report: Report,
) -> dict[AgentKey, str]:
    """Each planned agent the seed may run, published.

    One found under a planned name is used only when `distrust` finds nothing, and an agent
    that hands work to a refused one is refused with it; a refused agent is reported, never
    changed, and never asked or measured. A plan on the fork line waits for the fork, and a
    pinned one for main's v`FORK_FROM`, which a line somebody changed may not have. One an
    interrupted run created and never published is published now; a published one is left
    exactly as it is.
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
        if plan.line == "fork" and fork is None:
            report.refuse(f"{label}: the {FORK} fork it reads is missing or was refused")
            continue
        if plan.line == "pinned" and len(main) < FORK_FROM:
            report.refuse(f"{label}: main has no v{FORK_FROM} to pin")
            continue
        delegate = None
        if plan.delegates_to is not None:
            target = ids[plan.delegates_to]
            delegate = (
                target,
                str(api.call("GET", f"/agents/{target}", org=org)["current_version_id"]),
            )
        planned = agent_spec(plan, model=model, skill=skill, delegate=delegate, fork=fork)
        agent_id = existing.get(plan.name)
        if agent_id is None:
            agent_id = str(api.call("POST", "/agents", org=org, body={"spec": planned})["id"])
            report.note(label, made=True)
        else:
            reason, spec = distrust(
                api, org, agent_id, planned, me=me, earlier=plan.earlier_instructions
            )
            if reason is not None:
                report.refuse(f"{label}: {reason}")
                continue
            kept = ""
            if str(spec.get("instructions")) in plan.earlier_instructions:
                kept = " (seeded by an earlier version of this seed, kept as is)"
            elif _bindings(spec) != _bindings(planned):
                kept = " (moved to another line of the skill, kept as is)"
            report.note(f"{label}{kept}", made=False)
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
    "checks": {"enabled": True, "required": True, "defaults": []},
    "trajectory": {"enabled": False},
    "judge": {"enabled": False},
    "reference": {"enabled": False},
    "review": {"select": "none"},
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


def started_runs(api: Api, org: str, dataset: str) -> list[JsonObject]:
    """The runs on `dataset`, any agent's, that are under way or have answered a question.

    One that ended before answering anything measured nothing and does not count.
    """
    return [
        run
        for run in api.items(f"/datasets/{dataset}/eval-runs", org=org, params={"limit": 100})
        if run.get("status") in UNFINISHED or run.get("attempts_done", 0) > 0
    ]


def _graded_as_planned(api: Api, org: str, dataset: str) -> bool:
    scoring = api.call("GET", f"/datasets/{dataset}", org=org).get("scoring") or {}
    return all(
        (scoring.get(scorer) or {}).get(name) == value
        for scorer, settings in SCORING.items()
        for name, value in settings.items()
    )


def complete_dataset(
    api: Api, org: str, dataset: str, cases: Sequence[Case], *, label: str, report: Report
) -> None:
    """Give a dataset the seed began, and nothing has measured, its grading and the rest of
    its questions.

    It is the seed's own only while it holds the plan's first questions, in order and with
    their checks, graded as `SCORING` grades them - what an interrupted run leaves. A
    question removed, added or reworded since, a check or the grading changed, makes it
    somebody's, and it is left as it is. The grading is set before the first question, so
    an empty dataset is still the seed's to grade.
    """
    held = [
        (row.get("input"), row.get("checks"))
        for row in api.items(f"/datasets/{dataset}/cases", org=org, params={"limit": 100})
    ]
    planned = [(case.question, list(case.checks)) for case in cases]
    missing = cases[len(held) :]
    if held != planned[: len(held)] or (
        held and missing and not _graded_as_planned(api, org, dataset)
    ):
        report.note(f"{label} (changed since it was seeded, kept as is)", made=False)
        return
    if not missing:
        return
    api.call("PUT", f"/datasets/{dataset}/scoring", org=org, body=SCORING)
    for case in missing:
        api.call(
            "POST",
            f"/datasets/{dataset}/cases",
            org=org,
            body={"input": case.question, "checks": list(case.checks)},
        )
    if held:
        report.finish(f"{label}: {len(missing)} missing questions added")


def ensure_skill_set(api: Api, org: str, skill: str, *, report: Report) -> str:
    """The skill's own test questions, created empty and completed while nothing has run them."""
    found = api.find(f"/skills/{skill}/test-set", org=org)
    if found is None:
        found = api.call(
            "POST", f"/skills/{skill}/test-set", org=org, body={"from_evidence": False}
        )
        report.note(f"test questions of {SKILL}", made=True)
    else:
        report.note(f"test questions of {SKILL}", made=False)
    dataset = str(found["id"])
    if not started_runs(api, org, dataset):
        complete_dataset(
            api, org, dataset, SKILL_SET, label=f"test questions of {SKILL}", report=report
        )
    return dataset


def measure_on(api: Api, org: str, *, agent: str, dataset: str, label: str, report: Report) -> str:
    """The run measuring `agent` on `dataset`: its own that counts, or one started now."""
    mine = [run for run in started_runs(api, org, dataset) if str(run.get("agent_id")) == agent]
    if mine:
        report.note(f"measurement of {label}", made=False)
        return str(mine[0]["id"])
    started = api.call(
        "POST", f"/agents/{agent}/eval-runs", org=org, body={"dataset_id": dataset, "reruns": 0}
    )
    report.note(f"measurement of {label}", made=True)
    return str(started["id"])


def measure(
    api: Api, org: str, agents: Mapping[AgentKey, str], *, report: Report
) -> dict[AgentKey, str]:
    """Each agent with test questions: its dataset, and the run measuring the agent on it.

    From the first run that counts on any agent, the dataset is somebody's measurement and
    is never completed again; the seed's own agent is still measured on it when it has no
    run of its own. Running a dataset on an agent is also what makes it that agent's test
    set, since a plain dataset names no agent.
    """
    runs: dict[AgentKey, str] = {}
    for plan in AGENTS:
        if plan.dataset is None or plan.key not in agents:
            continue
        dataset = ensure_dataset(api, org, plan, plan.dataset, report=report)
        report.datasets[plan.key] = dataset
        if not started_runs(api, org, dataset):
            complete_dataset(
                api, org, dataset, plan.cases, label=f"dataset of {plan.key}", report=report
            )
        runs[plan.key] = measure_on(
            api, org, agent=agents[plan.key], dataset=dataset, label=plan.key, report=report
        )
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


def _settle(api: Api, org: str, *, made: bool, row: JsonObject, report: Report) -> None:
    """AI assistance on and a budget set, on an organization made now or never set up."""
    untouched = not row.get("ai_assistance_enabled") and row.get("monthly_budget_usd") is None
    if not (made or untouched):
        return
    api.call(
        "PATCH",
        f"/orgs/{org}",
        org=org,
        body={"ai_assistance_enabled": True, "monthly_budget_usd": ORG_BUDGET_USD},
    )
    if not made:
        report.finish("organization settings: AI assistance on, a monthly budget set")


def seed(api: Api, *, key: str | None, ask_in: Callable[[str], Ask]) -> Report:
    """Build Skills lab, or finish building it; `ask_in` opens the chat for an organization."""
    report = Report()
    me = str(api.call("GET", "/users/me")["id"])
    org, made, row = ensure_org(api, name=ORG_NAME, slug=ORG_SLUG, report=report)
    report.organization_id = org
    _settle(api, org, made=made, row=row, report=report)
    model = ensure_model(api, org, key=key, report=report)
    skill = ensure_skill(api, org, body=skill_body(), me=me, report=report)
    report.skill_id = skill
    main = ensure_history(api, org, skill, report=report)
    fork = ensure_fork(api, org, skill, main, me=me, report=report)
    report.fork_id = fork or ""
    report.skill_set_id = ensure_skill_set(api, org, skill, report=report)
    agents = ensure_agents(
        api, org, AGENTS, model=model, skill=skill, main=main, fork=fork, me=me, report=report
    )
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


def passed_questions(api: Api, org: str, run: JsonObject, *, label: str) -> set[str]:
    """The questions the measured answers passed."""
    arm = (run.get("outcome") or {}).get("candidate_arm_id")
    if arm is None:
        raise SeedError(f"The measurement of {label} has no result to read")
    passed = api.items(
        f"/eval-runs/{run['id']}/cases",
        org=org,
        params={"arm_id": str(arm), "outcome": "passed", "limit": 100},
    )
    return {str(case.get("input")) for case in passed}


def finished(
    api: Api, org: str, run_id: str, *, label: str, wait: Callable[[float], None], deadline: float
) -> JsonObject:
    """The run once it completed; one that ended any other way says nothing about a wording."""
    run = api.call("GET", f"/eval-runs/{run_id}", org=org)
    while run["status"] in UNFINISHED:
        if time.monotonic() > deadline:
            raise SeedError(f"The measurement of {label} did not finish in time")
        wait(5)
        run = api.call("GET", f"/eval-runs/{run_id}", org=org)
    if run["status"] != "completed":
        raise SeedError(
            f"The measurement of {label} ended {run['status']}, so it says nothing "
            "about the wording: drop the probes and measure again"
        )
    return run


def _count(passed: set[str], cases: Sequence[Case]) -> int:
    return sum(1 for case in cases if case.question in passed)


def probe(
    api: Api,
    variant: Variant,
    *,
    key: str | None,
    wait: Callable[[float], None] = time.sleep,
    patience: float = EVAL_PATIENCE_SECONDS,
) -> JsonObject:
    """Measure the main line's desks with rule 2 worded as `variant`, in an organization of its own.

    The skill is main's newest text with that wording, and each desk in `PROBED` answers its
    own questions and the skill's. Against `v1`, `broad` and `gift` should cost B at least
    five of its eight rule questions and `narrow` at most one, while all three win A its
    eight back; on the skill's questions `broad` fails the ones with no order number, and
    `narrow` and `gift` pass both groups. So the answer counts questions passed per group,
    not a pass rate over all of them. Fork and version labels are not read: the probe has
    neither.
    """
    report = Report()
    me = str(api.call("GET", "/users/me")["id"])
    org, made, row = ensure_org(
        api,
        name=PROBE_NAME.format(variant=variant),
        slug=PROBE_SLUG.format(variant=variant),
        report=report,
    )
    _settle(api, org, made=made, row=row, report=report)
    model = ensure_model(api, org, key=key, report=report)
    skill = ensure_skill(
        api, org, body=skill_body(variant, main=MAIN_VERSIONS), me=me, report=report
    )
    skill_set = ensure_skill_set(api, org, skill, report=report)
    probed = [plan for plan in AGENTS if plan.key in PROBED]
    agents = ensure_agents(
        api, org, probed, model=model, skill=skill, main=(), fork=None, me=me, report=report
    )
    if report.refused:
        raise SeedError(
            f"The probe organization holds agents the seed did not make: {report.refused}"
        )
    own = measure(api, org, agents, report=report)
    on_skill_set = {
        plan.key: measure_on(
            api,
            org,
            agent=agents[plan.key],
            dataset=skill_set,
            label=f"{plan.key} on the skill's questions",
            report=report,
        )
        for plan in probed
    }
    result: JsonObject = {"variant": variant}
    deadline = time.monotonic() + patience
    for plan in probed:
        mine = finished(api, org, own[plan.key], label=plan.key, wait=wait, deadline=deadline)
        theirs = finished(
            api,
            org,
            on_skill_set[plan.key],
            label=f"{plan.key} on the skill's questions",
            wait=wait,
            deadline=deadline,
        )
        passed = passed_questions(api, org, mine, label=plan.key)
        on_set = passed_questions(api, org, theirs, label=f"{plan.key} on the skill's questions")
        result[plan.key] = {
            "rule_passed": _count(passed, plan.rule),
            "rule_total": len(plan.rule),
            "pass_rate": (mine.get("outcome") or {}).get("candidate_pass_rate"),
            "skill_set": {
                "no_order_number": _count(on_set, SKILL_SET_CREDITED),
                "order_number": _count(on_set, SKILL_SET_REFUNDED),
                "of_each": len(SKILL_SET_CREDITED),
            },
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
