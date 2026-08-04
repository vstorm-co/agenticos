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
  without pricing an Anthropic child against OpenAI's catalog.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.agents.capabilities.budget import BudgetGuard, BudgetScope, SpendLedger, SpendLimit
from app.agents.spec import AgentSpec, CapabilityBindingSpec, SpecialistSpec, SubagentRef


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
    assert converted.mcp_server_ids == []
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
