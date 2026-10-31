"""The one rule for a name an author gives to an output port.

A switch rule, a classify category, an `error.handle` branch and an approval
choice each become an output port named by the author. None may reuse a port
the step already has - its static ones, which the step's own config refuses here,
and `error`, which the graph validator refuses for a step that routes its errors
(`validate._error_port_clash_problems`), because only the graph knows that.
"""


def refuse_clash(name: str, static_ports: frozenset[str]) -> str:
    """`name`, or a refusal naming it when the step already has a port called that."""
    if name in static_ports:
        raise ValueError(clash_message(name))
    return name


def clash_message(name: str) -> str:
    """What every refusal says, so the author learns what to do."""
    return f"`{name}` is already a port on this step - rename it"
