"""The seams delegation is built on, exercised directly.

Four things landed in `app/agents/spec.py`, `deps.py` and the budget capability
before anything used them, and a seam nobody calls is a seam nobody has checked.
Each test here covers one, and each one is a refusal or a conversion that
something further out depends on being right:

- an agent cannot delegate to the same agent twice, refused in the spec rather
  than at publish so a hand-written YAML import is caught by the same rule as the
  Builder;
- a specialist cannot bind one capability twice, for the reason `AgentSpec`
  refuses it - the second binding would silently shadow the first with no
  indication which was built;
- a specialist converts to the bindings the registry consumes, and to a full
  `AgentSpec`, because "one spec type, one validator, one builder used
  recursively" is a claim about this method rather than an aspiration;
- a delegate's guard shares the run's ledger and limits while pricing its own
  provider, which is what keeps a delegation's cost inside the cap somebody set
  without pricing an Anthropic child against OpenAI's catalog;
- one shared ledger still answers "what did *this* delegate spend", because every
  entry is stamped with the delegation that booked it. That is the seam a
  delegation's recorded cost is read off, and it is what makes one set of prices
  serve both the run's total and each delegate's share;
- the stash answers what a delegation has already spent, keyed by the `task` call
  that opens it, because the ledger a resumed turn reads its share off is a fresh
  object holding nothing from before the park.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.agents.capabilities.budget import (
    BudgetGuard,
    BudgetScope,
    SpendEntry,
    SpendLedger,
    SpendLimit,
    SpendShare,
    booked_to,
)
from app.agents.spec import AgentSpec, CapabilityBindingSpec, SpecialistSpec, SubagentRef
from app.agents.subagent_runtime import DelegationSpend, DelegationStash


def _specialist(**overrides: object) -> dict[str, object]:
    return {
        "name": "researcher",
        "description": "Researches a topic and cites sources",
        "instructions": "You research things.",
        **overrides,
    }


def test_an_agent_cannot_delegate_to_the_same_agent_twice() -> None:
    """Two pins of one agent are two delegates with one name.

    The model addresses a delegate by the handle its row owns, so a second pin of
    the same agent gives the model no way to say which it meant and the second
    would shadow the first.
    """
    agent_id = uuid4()
    with pytest.raises(ValueError, match="delegated to more than once"):
        AgentSpec(
            name="Support",
            subagents=[
                SubagentRef(agent_id=agent_id, agent_version_id=uuid4()),
                SubagentRef(agent_id=agent_id, agent_version_id=uuid4()),
            ],
        )


def test_two_pins_of_different_agents_are_allowed() -> None:
    """The refusal above is about one agent twice, not about having two delegates."""
    spec = AgentSpec(
        name="Support",
        subagents=[
            SubagentRef(agent_id=uuid4(), agent_version_id=uuid4()),
            SubagentRef(agent_id=uuid4(), agent_version_id=uuid4()),
        ],
    )

    assert len(spec.subagents) == 2


def test_a_specialist_cannot_bind_one_capability_twice() -> None:
    """The same rule `AgentSpec` applies, restated because it is not inherited.

    A `field_validator` does not carry across unrelated models, and a specialist
    that could bind `knowledge` twice would build one of the two with nothing
    saying which.
    """
    with pytest.raises(ValueError, match="bound more than once"):
        SpecialistSpec(
            **_specialist(
                capabilities=[
                    CapabilityBindingSpec(id="knowledge"),
                    CapabilityBindingSpec(id="knowledge"),
                ]
            )
        )


def test_a_specialist_hands_its_capabilities_to_the_registry() -> None:
    """`bindings()` is what `build_agent` consumes, so a specialist has to answer it."""
    specialist = SpecialistSpec(
        **_specialist(capabilities=[CapabilityBindingSpec(id="clock")]),
    )

    bindings = specialist.bindings()

    assert [binding.capability_id for binding in bindings] == ["clock"]


def test_a_specialist_without_a_model_runs_on_its_parents() -> None:
    """The conversion that keeps one builder rather than two.

    A specialist naming no profile runs on the profile of the agent that called
    it - the least surprising answer, and the only one that works when the parent
    is the only agent whose profile the author chose. The fields a specialist
    deliberately lacks arrive at their `AgentSpec` defaults, which is what makes
    "the parent's caps bind" true rather than merely intended.
    """
    parent_profile = uuid4()
    specialist = SpecialistSpec(**_specialist(max_steps=12))

    converted = specialist.to_agent_spec(fallback_model_profile_id=parent_profile)

    assert converted.name == "researcher"
    assert converted.instructions == "You research things."
    assert converted.model_profile_id == parent_profile
    assert converted.max_steps == 12
    # No cap, no alerts of its own, no Logfire project, no connections, and no
    # delegating further - each absent on purpose.
    assert converted.budget is None
    assert converted.observability is None
    assert converted.mcp_servers == []
    assert converted.subagents == []


def test_a_specialist_keeps_a_model_profile_it_names() -> None:
    """The fallback applies only when the specialist chose nothing."""
    own = uuid4()
    specialist = SpecialistSpec(**_specialist(model_profile_id=own))

    assert specialist.to_agent_spec(fallback_model_profile_id=uuid4()).model_profile_id == own


def test_a_delegates_guard_shares_the_run_and_prices_its_own_provider() -> None:
    """One ledger and one set of limits, two providers.

    Sharing the parent's guard outright would price a delegate's requests against
    the parent's provider - silently, usually as unpriced, which under-reports the
    run and marks a perfectly priceable one partial. Sharing `run_state` matters
    too and is the less obvious half: the baselines are read from the database
    once per *run*, not once per agent, because several delegations would
    otherwise read them at the same time on a session that is not
    concurrency-safe.
    """
    ledger = SpendLedger(run_id=uuid4())
    parent = BudgetGuard(
        ledger=ledger,
        provider="openai",
        limits=[SpendLimit(scope=BudgetScope.AGENT, limit_usd=Decimal("5"))],
    )

    delegate = parent.for_delegate(provider="anthropic")

    assert delegate.provider == "anthropic"
    assert delegate.ledger is ledger
    assert delegate.limits is parent.limits
    assert delegate.run_state is parent.run_state


def _priced(cost: str, tokens: int = 10) -> SpendEntry:
    return SpendEntry(
        model_name="gpt-4.1",
        input_tokens=tokens,
        output_tokens=tokens,
        cost_usd=Decimal(cost),
        priced=True,
    )


def test_a_delegation_the_run_is_starting_has_spent_nothing_yet() -> None:
    """Which is every delegation until one parks, so the ordinary path is the share alone.

    A `task` call the stash has never seen is a delegation being started rather than
    continued. Answering anything but zero here would add a previous delegation's
    cost to a fresh one.
    """
    stash = DelegationStash(spent={"another-task-call": DelegationSpend(cost_usd=Decimal("2"))})

    assert stash.already_spent("this-task-call") == DelegationSpend()


def test_a_delegation_being_continued_answers_with_what_it_already_cost() -> None:
    """The key is the parent's `task` call, which the replay presents again."""
    spent = DelegationSpend(cost_usd=Decimal("0.25"), input_tokens=7, output_tokens=3)
    stash = DelegationStash(spent={"the-task-call": spent})

    assert stash.already_spent("the-task-call") == spent


def test_a_delegation_with_no_tool_call_to_name_it_carries_nothing() -> None:
    """There is nothing a resume could key it by, so there is nothing to have kept.

    Reachable because `RunContext.tool_call_id` is optional: a caller driving the
    toolset without a model behind it has no `task` call, and `park` already refuses
    to stash such a delegation for the same reason.
    """
    stash = DelegationStash(spent={"the-task-call": DelegationSpend(cost_usd=Decimal("0.25"))})

    assert stash.already_spent(None) == DelegationSpend()


def test_a_delegation_the_run_is_starting_has_no_earlier_start() -> None:
    """Which is every delegation until one parks, so the recorder takes this turn's.

    A `task` call the stash has never seen is a delegation being started rather than
    continued: nothing began in an earlier turn, so `_span_start` reads the whole
    span off this turn's own handle.
    """
    stash = DelegationStash(started={"another-task-call": datetime(2026, 8, 5, tzinfo=UTC)})

    assert stash.already_started("this-task-call") is None


def test_a_delegation_being_continued_answers_with_when_it_first_began() -> None:
    """The key is the parent's `task` call, which the replay presents again."""
    began = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
    stash = DelegationStash(started={"the-task-call": began})

    assert stash.already_started("the-task-call") == began


def test_a_delegation_with_no_tool_call_to_name_it_carries_no_start() -> None:
    """Nothing a resume could key it by, exactly as with what it already spent."""
    stash = DelegationStash(started={"the-task-call": datetime(2026, 8, 5, tzinfo=UTC)})

    assert stash.already_started(None) is None


def test_one_ledger_still_says_which_delegation_spent_what() -> None:
    """The seam a delegation's recorded cost is read off.

    Not a ledger per agent - that is the design that stops the parent's cap from
    binding at all - but one ledger whose entries know who booked them. Everything
    the parent spends before, during and after a delegation stays the parent's,
    which is what makes the answer independent of *when* the delegation is settled.
    """
    ledger = SpendLedger()

    ledger.book(_priced("0.20"))
    with booked_to("delegation-a", has_own_row=True):
        ledger.book(_priced("0.01"))
    ledger.book(_priced("0.30"))

    assert ledger.share_of("delegation-a").cost_usd == Decimal("0.01")
    assert ledger.total_usd == Decimal("0.51")


def test_a_nested_delegation_takes_the_spend_from_the_one_it_is_inside() -> None:
    """The innermost delegation wins, which is what stops a level double-counting.

    A mid-tree delegate's row and its own delegate's row both land in
    `monthly_spend(agent_id=...)`, so a share containing what the level below spent
    is the same money recorded twice under one agent's month.
    """
    ledger = SpendLedger()

    with booked_to("child", has_own_row=True):
        ledger.book(_priced("0.02"))
        with booked_to("grandchild", has_own_row=True):
            ledger.book(_priced("0.04"))
        ledger.book(_priced("0.02"))

    assert ledger.share_of("child").cost_usd == Decimal("0.04")
    assert ledger.share_of("grandchild").cost_usd == Decimal("0.04")
    # The whole, once: the shares partition the ledger rather than overlapping it.
    assert ledger.total_usd == Decimal("0.08")


def test_an_inline_specialist_bills_its_spend_to_its_published_ancestor() -> None:
    """The panel keeps the specialist's own share; the row gets the ancestor's whole.

    A published delegate (`has_own_row=True`) delegates to an inline specialist
    (`has_own_row=False`). The specialist's request is stamped to the specialist for
    its panel and to the delegate for its month, so `share_of` and `billed_share_of`
    answer the two questions that used to be one - and the money no longer falls
    between them (agenticos#228).
    """
    ledger = SpendLedger()

    with booked_to("researcher", has_own_row=True):
        ledger.book(_priced("0.50"))
        with booked_to("fact-checker", has_own_row=False):
            ledger.book(_priced("0.25"))

    # The panel: each shows only its own requests, exactly as before.
    assert ledger.share_of("researcher").cost_usd == Decimal("0.50")
    assert ledger.share_of("fact-checker").cost_usd == Decimal("0.25")
    # The row: the delegate's month is its own plus the specialist it used, and the
    # specialist bills nothing to a row of its own - it has none.
    assert ledger.billed_share_of("researcher").cost_usd == Decimal("0.75")
    assert ledger.billed_share_of("fact-checker").cost_usd == Decimal("0")
    # Nothing counted twice: the whole ledger is the researcher's billed share here.
    assert ledger.total_usd == Decimal("0.75")


def test_inline_specialists_nest_to_the_nearest_published_ancestor() -> None:
    """Two levels of inline still bill to the one published delegate above them.

    `billed_to` advances only across a delegation with its own row, so an inline
    specialist under an inline specialist under a published delegate leaves both of
    them pointing at the delegate - which is the only agent with a month to land in.
    """
    ledger = SpendLedger()

    with booked_to("researcher", has_own_row=True):
        ledger.book(_priced("0.10"))
        with booked_to("summariser", has_own_row=False):
            ledger.book(_priced("0.20"))
            with booked_to("fact-checker", has_own_row=False):
                ledger.book(_priced("0.30"))

    assert ledger.billed_share_of("researcher").cost_usd == Decimal("0.60")
    assert ledger.billed_share_of("summariser").cost_usd == Decimal("0")
    assert ledger.billed_share_of("fact-checker").cost_usd == Decimal("0")


def test_an_inline_specialist_under_the_runs_own_agent_bills_to_no_delegated_row() -> None:
    """Its spend is in the top-level row, which is the whole ledger, so it needs none.

    `has_own_row=False` with nothing published above it leaves `billed_to` at its
    default - the run's own agent - which no delegated row is ever keyed by. The
    money is not lost: the top-level run row is the whole ledger regardless.
    """
    ledger = SpendLedger()

    with booked_to("fact-checker", has_own_row=False):
        ledger.book(_priced("0.25"))

    assert ledger.share_of("fact-checker").cost_usd == Decimal("0.25")
    assert [entry.billed_to for entry in ledger.entries] == [None]
    assert ledger.total_usd == Decimal("0.25")


def test_a_share_carries_the_tokens_and_whether_it_was_priced() -> None:
    """`cost_is_partial` on a child row is about the child's own requests.

    A parent on a model `genai-prices` does not know makes the *parent's* total a
    floor; it says nothing about a delegate that ran on a priced one, and marking
    every child row in the run partial is how a priceable delegation was reported
    as incomplete.
    """
    ledger = SpendLedger()

    ledger.book(SpendEntry("mystery-1", 5, 5, Decimal(0), priced=False))
    with booked_to("delegation-a", has_own_row=True):
        ledger.book(_priced("0.01", tokens=7))

    with booked_to("delegation-b", has_own_row=True):
        ledger.book(SpendEntry("mystery-2", 5, 5, Decimal(0), priced=False))

    priced = ledger.share_of("delegation-a")
    assert (priced.input_tokens, priced.output_tokens) == (7, 7)
    assert priced.has_unpriced_models is False
    # The other direction: a delegate on a model nothing can price reports a floor
    # of its own, however well priced the rest of the run was.
    assert ledger.share_of("delegation-b").has_unpriced_models is True
    assert ledger.has_unpriced_models is True


def test_a_delegation_that_made_no_request_of_its_own_has_no_share() -> None:
    """A delegate the library refused, or one whose whole job was to delegate on."""
    ledger = SpendLedger()
    ledger.book(_priced("0.20"))

    assert ledger.share_of("delegation-a") == SpendShare()


def test_spend_outside_a_delegation_belongs_to_the_run_itself() -> None:
    """The attribution is reset on the way out, not left set.

    A leaked value would book the parent's next request to a delegate that had
    already answered - the same defect as the delta, arriving by another route.
    """
    ledger = SpendLedger()

    with booked_to("delegation-a", has_own_row=True):
        ledger.book(_priced("0.01"))
    ledger.book(_priced("0.30"))

    assert [entry.delegation for entry in ledger.entries] == ["delegation-a", None]
