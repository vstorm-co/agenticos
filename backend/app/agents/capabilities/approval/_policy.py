"""Reading a spec to decide which tools need a human.

Separate from the gate because the two answer different questions at different
times: this turns stored configuration into a set of tool names once, while an
agent is being assembled; the gate consults that set on every tool call. Keeping
the rule here means a surface never re-derives it from the registry and the spec
and gets a different answer.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.agents.capabilities import CapabilityDef, CapabilityToolInfo
from app.agents.capabilities import get as get_capability
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import BadRequestError


def tool_needs_approval(
    *, tool: CapabilityToolInfo, binding: CapabilityBindingSpec, side_effecting: bool
) -> bool:
    """Whether one tool of one binding must be approved before it runs.

    The most specific statement wins:

    1. `tool_approval[tool.id]` - this agent's decision about this tool.
    2. the binding's `approval` - this agent's decision about the whole
       capability, and so the default for every tool in it.
    3. the tool's own `side_effecting`, for a capability whose tools are not
       one answer - a filesystem that is read *and* written, say.
    4. the capability's `side_effecting` flag - what the code that wrote the
       tool says about it, and the answer when nothing above said anything.

    `'default'` at either of the first two levels is not an answer, it is a
    deferral to the next one, and so is a tool declaring no `side_effecting` of
    its own. That is what makes a spec written before per-tool approval existed
    behave exactly as it did: no `tool_approval` and no `approval` leaves the
    capability's flag deciding, as it always did.

    Keyed on the tool's stable id rather than the name the model sees, so a
    renamed tool keeps the gate its operator put on it.
    """
    for mode in (binding.tool_approval.get(tool.id, "default"), binding.approval):
        if mode != "default":
            return mode == "required"
    if tool.side_effecting is not None:
        return tool.side_effecting
    return side_effecting


def approval_required_tools(spec: AgentSpec) -> frozenset[str]:
    """Every tool in a spec that a human must approve before it runs.

    Returns the names the model will call, because that is what the gate sees
    on a tool call - but the *decision* is keyed on each tool's stable id, so
    renaming a tool cannot quietly drop its gate.

    Those two are not the same string once a binding renames a tool, and getting
    it wrong is a security bug rather than a cosmetic one: gate the *declared*
    name and the gate waits for a tool the model never calls, while the tool it
    does call - the side-effecting one somebody deliberately gated - runs
    unapproved with nothing reporting it. So the decision reads `tool.id` and
    the answer reads the effective name.

    Raises:
        BadRequestError: If the spec names a capability the registry does not
            have. Publishing checks that first and reports every problem at
            once; this is the backstop for a spec that reached the factory
            another way.
    """
    required: set[str] = set()
    for binding in spec.capabilities:
        if not binding.enabled:
            continue
        definition = get_capability(binding.id)
        required.update(
            tool.name
            for tool in definition.effective_tools(binding.tool_overrides)
            if tool_needs_approval(
                tool=tool,
                binding=binding,
                side_effecting=definition.side_effecting,
            )
        )
    return frozenset(required)


def ungateable_tool_problems(
    binding: CapabilityBindingSpec, definition: CapabilityDef, config: BaseModel | None
) -> list[str]:
    """Approval on a tool the model provider, not this deployment, would run.

    `ApprovalGate` wraps *tool execution*, which is the only place a call can be
    held - so a tool the provider executes on its own side never reaches it. Under
    `web_fetch`'s `native` method there is no local tool at all, and under `auto`
    there is one only on a model with no native fetch of its own; a `native` search
    is the same shape. Either way a binding that asks for approval and then hands
    the call to the provider gets a gate that never fires, and the failure is
    silent: the queue stays empty and the agent acts unapproved.

    Refused rather than repaired. "Ask before this agent reads a page" and "let
    the provider fetch, with its own egress and citations" are both legitimate,
    and quietly forcing the local tool to make the gate work would answer a
    question that is the author's - while quietly dropping the gate is the bug.
    `auto` is refused with `native`, because which of the two an `auto` binding
    gets is a property of the model profile and that changes without republishing.

    Which configurations hand which tools over is
    :class:`~app.agents.capabilities.ProviderExecuted` on the capability itself,
    not a branch per capability in the caller: the first version of this knew
    `web_fetch`'s methods by name and `web_research`'s identical `native` was
    published unrefused for as long as that lasted (#857).
    """
    declared = definition.provider_executed
    if declared is None:
        return []
    handed_over = declared.tools_for(config)
    gated = sorted(
        tool.id
        for tool in definition.tools
        if tool.id in handed_over
        and tool_needs_approval(
            tool=tool, binding=binding, side_effecting=definition.side_effecting
        )
    )
    if not gated:
        return []
    chosen = str(getattr(config, declared.field, ""))
    return [
        f"Capability '{binding.id}' requires approval for {', '.join(gated)}, but "
        f"{declared.field} '{chosen}' can hand the call to the model provider, where "
        f"this deployment has no call to hold. Choose a {declared.field} this "
        "deployment runs itself, or drop the approval requirement."
    ]


def refuse_ungateable_approvals(spec: AgentSpec) -> None:
    """Refuse to assemble an agent whose approval gate could never fire.

    Publish validation asks the same question of a draft, which is where it
    should be answered - while somebody is looking at a form and can change it.
    But a version published *before* that refusal existed never passes through
    validation again: a run loads the frozen `AgentVersion` and hands its spec
    straight to :func:`app.agents.factory.build_agent`. Without this, every
    agent the two refusals were written for goes on fetching and searching
    unapproved for ever, which is what makes a publish-time-only fix a fix for
    new agents rather than for the defect (#871).

    Refused rather than downgraded, the same choice publish makes: swapping the
    binding to a method this deployment runs would answer a question that is the
    author's, and dropping the gate is the bug itself. It costs an upgrade - an
    agent that has been running this way stops running, with a message naming
    what to change - and that is the honest price, because what stops is an agent
    whose operator asked for an approval nobody was ever being asked for.

    Raises:
        BadRequestError: If any enabled binding gates a tool the model provider
            would execute.
    """
    problems: list[str] = []
    for binding in spec.capabilities:
        if not binding.enabled:
            continue
        definition = get_capability(binding.id)
        config = definition.validate_config(binding.config)
        problems.extend(ungateable_tool_problems(binding, definition, config))
    if problems:
        raise BadRequestError(
            message=(
                "This agent was published with an approval that cannot be enforced. "
                "Edit it and publish it again."
            ),
            details={"problems": problems},
        )
