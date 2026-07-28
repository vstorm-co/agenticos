"""Reading a spec to decide which tools need a human.

Separate from the gate because the two answer different questions at different
times: this turns stored configuration into a set of tool names once, while an
agent is being assembled; the gate consults that set on every tool call. Keeping
the rule here means a surface never re-derives it from the registry and the spec
and gets a different answer.
"""

from __future__ import annotations

from app.agents.capabilities import get as get_capability
from app.agents.spec import AgentSpec, CapabilityBindingSpec


def tool_needs_approval(
    *, tool_id: str, binding: CapabilityBindingSpec, side_effecting: bool
) -> bool:
    """Whether one tool of one binding must be approved before it runs.

    The most specific statement wins:

    1. ``tool_approval[tool_id]`` - this agent's decision about this tool.
    2. the binding's ``approval`` - this agent's decision about the whole
       capability, and so the default for every tool in it.
    3. the capability's ``side_effecting`` flag - what the code that wrote the
       tool says about it, and the answer when the spec says nothing.

    ``'default'`` at either of the first two levels is not an answer, it is a
    deferral to the next one. That is what makes a spec written before per-tool
    approval existed behave exactly as it did: no ``tool_approval`` and no
    ``approval`` leaves ``side_effecting`` deciding, as it always did.

    Keyed on the tool's stable id rather than the name the model sees, so a
    renamed tool keeps the gate its operator put on it.
    """
    for mode in (binding.tool_approval.get(tool_id, "default"), binding.approval):
        if mode != "default":
            return mode == "required"
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
    unapproved with nothing reporting it. So the decision reads ``tool.id`` and
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
                tool_id=tool.id,
                binding=binding,
                side_effecting=definition.side_effecting,
            )
        )
    return frozenset(required)
