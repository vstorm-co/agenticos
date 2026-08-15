"""Building a live agent from a stored spec.

The single place where configuration becomes an executable agent. Everything
above deals in specs and ids; everything below is Pydantic AI.

Keeping this a narrow, explicit funnel is the point: when the underlying agent
library changes shape, one file changes. When a new capability is added to the
platform, there is one obvious place it plugs in. And because the funnel is
narrow, the same spec produces the same agent whether the run came from the web
chat, a Slack mention or the public API - which is what makes "the Builder is
just another client" true rather than aspirational.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.capabilities import ReinjectSystemPrompt
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import DeferredToolRequests
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits

from app.agents.capabilities import build as build_capabilities
from app.agents.capabilities.approval import ApprovalGate, approval_required_tools
from app.agents.capabilities.budget import (
    BudgetGuard,
    BudgetScope,
    PeriodSpendLookup,
    SpendLedger,
    SpendLimit,
)
from app.agents.capabilities.compaction import (
    MODEL_CONTEXT_WINDOW_RESOURCE,
    ContextGauge,
    build_gauge,
)
from app.agents.deps import AgentDeps, ApprovalCallback
from app.agents.model_resolver import ModelRequestSpec
from app.agents.observability import instrument_agent
from app.agents.spec import AgentSpec
from app.core.secret_kinds import ApiKeySecret, StorableSecret

logger = logging.getLogger(__name__)

# How many model requests a run may make when its spec does not say. Raised
# from Pydantic AI's own 50: real agents with skills and MCP tools were hitting
# the ceiling mid-task, and the budget caps are what guard cost - this guards
# only the never-finishing loop, which 100 still catches.
DEFAULT_MAX_STEPS = 100


@dataclass
class BuiltAgent:
    """A runnable agent plus what the caller needs to observe and account for it.

    The ledger is returned rather than hidden inside the agent because the
    caller is what persists a run: it writes the cost row, and it decides what
    to show the user when a budget stops a run mid-conversation.
    """

    # The output is a union because a run can end without an answer: when a
    # gated tool is parked, Pydantic AI ends the run with the calls waiting on a
    # human instead. The caller must handle both, which is the point of making
    # it visible in the type.
    agent: PydanticAgent[AgentDeps, str | DeferredToolRequests]
    deps: AgentDeps
    ledger: SpendLedger
    # Exposed rather than buried in the agent's capability list: the caller
    # needs the limits to explain a stopped run, and reaching into another
    # library's internals to find them would break on its next release.
    budget: BudgetGuard
    # How full the context was before the last model request of this run. Read
    # after the run, beside the ledger, and for the same reason: the surface that
    # reports what a turn cost is the one that reports how close it came to the
    # ceiling.
    context: ContextGauge
    # The capabilities the spec asked for, without the two every agent gets.
    # Callers introspect what an agent can actually do without knowing which
    # entries the factory adds unconditionally.
    capabilities: list[Any]
    model_label: str
    # What stops a tool loop. Pydantic AI applies its own default when a run is
    # started without limits, so this is never None: leaving it off would make
    # "the agent spec said 50" and "nobody passed anything" indistinguishable at
    # the call sites, which is how one surface ends up uncapped.
    usage_limits: UsageLimits
    # Tool names, resolved from the spec once. A surface showing "this agent
    # will ask before it does X" reads this rather than guessing from the
    # capability list, where a capability with one gated tool and one ungated
    # one has no single answer.
    approval_required_tools: frozenset[str]


def build_agent(
    spec: AgentSpec,
    model_spec: ModelRequestSpec,
    *,
    organization_id: UUID,
    agent_id: UUID | None = None,
    run_id: UUID | None = None,
    user_id: str | None = None,
    user_name: str | None = None,
    granted_scopes: frozenset[str] | None = None,
    resources: dict[str, Any] | None = None,
    secrets: Mapping[UUID, StorableSecret] | None = None,
    extra_toolsets: list[AbstractToolset[Any]] | None = None,
    agent_period_spend: PeriodSpendLookup | None = None,
    org_period_spend: PeriodSpendLookup | None = None,
    org_monthly_budget_usd: Decimal | None = None,
    request_approval: ApprovalCallback | None = None,
    shared_budget: BudgetGuard | None = None,
) -> BuiltAgent:
    """Instantiate an agent from its spec.

    Args:
        spec: The published (or draft, when previewing) agent definition.
        model_spec: Already-resolved model and credentials.
        granted_scopes: Scopes the organization allows. Passing `None` skips
            the check and is for internal runs only.
        resources: Values resolved from the database for this run - collection
            names, skills - which capabilities need but must never fetch
            themselves.
        secrets: The unsealed secrets this spec's bindings reference, keyed by
            id. They reach the capability instance and stop there: nothing here
            puts one in `AgentDeps`, in a tool argument or in the model's
            context, and a spec carries only the id.
        extra_toolsets: Toolsets resolved outside the registry, such as MCP
            servers configured per organization.
        agent_period_spend: How to read what *this agent* has booked this month,
            for the cap in its own spec. Omitted where there is no database to
            ask - a preview - in which case that cap meters only this run.
        org_period_spend: The same for the organization as a whole. The two are
            separate arguments because they are separate quantities; one lookup
            serving both is precisely how an agent's cap came to be exhausted by
            its neighbours' spending.
        org_monthly_budget_usd: The organization-wide cap, which applies on top
            of whatever the agent's own spec asks for.
        request_approval: How to put a gated tool call to a human. Omitted on a
            surface that cannot ask anyone, where the gate refuses instead.
        shared_budget: The guard - and therefore the ledger - of the run this
            agent is being built *inside*. Passed only when building a delegate
            or an inline specialist, and it is what makes a delegation's cost
            visible: the same guard wraps every child model request, so it checks
            the same accumulated total before the request and records into it
            afterwards. Without it a child gets a guard of its own, meters
            nothing the parent can see, and the parent's cap stops binding at
            precisely the moment delegation multiplies spend.

            It also decides *whose* caps bind, and the answer is the parent's. A
            delegate's own `budget.monthly_usd` is not enforced inside a parent
            run: two guards metering one ledger would double-count every request,
            and the ceiling that matters is the one on the run somebody started.
            The delegate's own cap still governs runs of the delegate itself, and
            its run rows still accumulate against it - see `docs/governance.md`.

    Raises:
        BadRequestError: If the spec references an unknown tool, an invalid tool
            configuration, a scope the organization has not granted, or a secret
            the organization no longer has.
    """
    bindings = spec.bindings()
    configured = build_capabilities(
        bindings,
        granted_scopes=granted_scopes,
        # Added here rather than by every caller: the model is resolved before an
        # agent is built and nowhere above this knows the window it accepts, so a
        # capability needing it would otherwise have to reach for the model - which
        # is exactly what `resources` exists to stop.
        resources={
            **(resources or {}),
            MODEL_CONTEXT_WINDOW_RESOURCE: model_spec.context_length,
        },
        secrets=secrets,
    )

    # Which tools a human must approve before they act. Computed here, while the
    # registry metadata and the spec's overrides are both in hand, so a surface
    # never has to re-derive it from two sources.
    approval_required = approval_required_tools(spec)

    deps = AgentDeps(
        organization_id=organization_id,
        agent_id=agent_id,
        run_id=run_id,
        user_id=user_id,
        user_name=user_name,
        # Read from `resources` rather than a parameter of its own: two sources
        # for one list is how they drift apart.
        kb_collection_names=list((resources or {}).get("kb_collection_names") or []),
        request_approval=request_approval,
    )

    # A child spends against the run's ledger and under the run's caps, but
    # prices its own requests: `for_delegate` shares the first two and takes this
    # agent's provider for the third. Sharing the parent's guard outright would
    # price an Anthropic delegate against OpenAI's catalog.
    budget = (
        shared_budget.for_delegate(provider=model_spec.provider)
        if shared_budget is not None
        else BudgetGuard(
            ledger=SpendLedger(run_id=run_id, agent_id=agent_id, organization_id=organization_id),
            provider=model_spec.provider,
            limits=_spend_limits(
                spec,
                agent_period_spend=agent_period_spend,
                org_period_spend=org_period_spend,
                org_monthly_budget_usd=org_monthly_budget_usd,
            ),
        )
    )
    ledger = budget.ledger

    # Three capabilities every agent gets, regardless of its spec. Making them
    # configurable would make "an agent with no spending limit" - or one that
    # acts on the world unattended - something somebody could arrive at by
    # accident. The gate is attached even when nothing is gated, so that adding
    # a side-effecting capability to a spec is the only thing that has to be
    # right for approval to apply.
    # Filled before every model request, read once the run is over. Behind the
    # spec's own capabilities in the list, so the reading is of the history as it
    # will be *sent* - a compaction ordered ahead of this one has already run,
    # and reporting what triggered it instead would show a gauge that never falls.
    gauge = ContextGauge()

    capabilities: list[Any] = [
        # Long conversations drift away from their instructions; re-stating the
        # system prompt is cheap insurance for an agent whose behaviour *is* its
        # instructions.
        ReinjectSystemPrompt(),
        budget,
        ApprovalGate(required_tool_names=approval_required),
        *configured,
        # Every agent, not only one that compacts. The warning is most useful to
        # exactly the agent that will not: it is the one that reaches the ceiling
        # and gets refused by the provider.
        build_gauge(gauge, recorded_window=model_spec.context_length),
    ]

    # Profile settings first, agent overrides second - the agent is the more
    # specific statement of intent.
    #
    # A setting the author never chose is absent from the dump rather than
    # present as `None`, which is what keeps this merge honest in both
    # directions: it cannot blank out a value the model profile set, and it
    # cannot send `temperature: null` to a reasoning model, which rejects the
    # parameter however it is spelled. See `ModelSettingsSpec`.
    model_settings = ModelSettings(**{**model_spec.params, **spec.model_settings.model_dump()})

    agent = PydanticAgent[AgentDeps, str | DeferredToolRequests](
        model=model_spec.build(),
        model_settings=model_settings,
        system_prompt=spec.instructions or "",
        # `str` first so the model answers in text; `DeferredToolRequests`
        # is not a shape the model can choose, it is what the run ends with when
        # the approval gate parks a call.
        output_type=[str, DeferredToolRequests],
        capabilities=capabilities,
        toolsets=extra_toolsets or [],
    )

    _instrument(agent, spec, secrets or {}, agent_id=agent_id)

    return BuiltAgent(
        agent=agent,
        deps=deps,
        ledger=ledger,
        budget=budget,
        context=gauge,
        capabilities=configured,
        model_label=model_spec.label,
        approval_required_tools=approval_required,
        usage_limits=UsageLimits(request_limit=spec.max_steps or DEFAULT_MAX_STEPS),
    )


def _as_decimal(value: float) -> Decimal:
    """Convert a spec's float budget to Decimal for exact accumulation.

    Money accumulated as float drifts; the spec uses float because JSON has no
    decimal type, and this is the boundary where that ends. Via `str` rather
    than `Decimal(value)`, which would carry the binary approximation across
    intact - 0.1 becoming 0.1000000000000000055511151231257827.
    """
    return Decimal(str(value))


def _spend_limits(
    spec: AgentSpec,
    *,
    agent_period_spend: PeriodSpendLookup | None,
    org_period_spend: PeriodSpendLookup | None,
    org_monthly_budget_usd: Decimal | None,
) -> list[SpendLimit]:
    """Every ceiling this run is under, narrowest first.

    The agent's monthly cap and the organization's are two entries rather than
    `min()` of the two, because they meter different spend: one agent's month
    and the whole organization's. Taking the tighter of two numbers only says
    something when both count the same thing, and the previous version of this
    function did it against a single organization-wide total - which turned
    `AgentSpec.budget.monthly_usd` into "stop this agent once *anyone* has
    spent X" and refused an agent that had spent nothing all month.

    Keeping them separate loses nothing the collapse provided. An agent still
    cannot loosen the organization's ceiling: the organization's entry is present
    at its own number whatever the spec asks for, and an agent's spend is part of
    the organization's, so a $100 agent under a $10 organization is still stopped
    at $10. It gains the case the collapse got wrong - a $5 agent under a $50
    ceiling now binds when *it* has spent $5, not when its neighbours have - and
    the refusal names the cap that actually bound instead of inferring it from
    which of two numbers was smaller.

    Order is narrowest first so a run under both exhausted ceilings reports
    the one nearest the person reading it. The organization's is deliberately
    last: it is the one an agent's author cannot raise, and hearing about it
    first would send them to somebody else for a limit they could have fixed
    themselves.
    """
    limits: list[SpendLimit] = []
    if spec.budget is not None and spec.budget.monthly_usd is not None:
        limits.append(
            SpendLimit(
                scope=BudgetScope.AGENT,
                limit_usd=_as_decimal(spec.budget.monthly_usd),
                period_spend=agent_period_spend,
            )
        )
    if org_monthly_budget_usd is not None:
        limits.append(
            SpendLimit(
                scope=BudgetScope.ORGANIZATION,
                limit_usd=org_monthly_budget_usd,
                period_spend=org_period_spend,
            )
        )
    return limits


def _instrument(
    agent: PydanticAgent[AgentDeps, str | DeferredToolRequests],
    spec: AgentSpec,
    secrets: Mapping[UUID, StorableSecret],
    *,
    agent_id: UUID | None,
) -> None:
    """Send this agent's traces to its own Logfire project, if it asked for one.

    Silent when the spec says nothing, which is every agent by default: the
    deployment's own Logfire configuration already receives the run.

    A configured block whose token is missing is *not* an error here. The secret
    may have been deleted after publish, and the choice is between an agent that
    runs untraced and an agent that does not run - publishing is where a missing
    secret is refused, and a run is far too late.
    """
    observability = spec.observability
    if observability is None or observability.token_secret_id is None:
        return

    secret = secrets.get(observability.token_secret_id)
    if not isinstance(secret, ApiKeySecret):
        logger.warning(
            "agent_logfire_token_unavailable",
            extra={"agent_id": str(agent_id) if agent_id else None},
        )
        return

    instrument_agent(
        agent,
        token=secret.api_key.get_secret_value(),
        service_name=observability.service_name or spec.name,
        environment=observability.environment,
    )
