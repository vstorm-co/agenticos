"""How hard the model reasons before it answers.

Pydantic AI's own `Thinking` is returned rather than wrapped. A capability of
ours around it would only be a second place for the same value to be written,
and the two would eventually disagree — it already sets the unified `thinking`
model setting that every reasoning-capable provider understands.

This module exists anyway, holding the one function that builds it, so the
package has the same shape as every other capability: `__init__.py` registers,
`_capability.py` builds. A reader looking for what `thinking` *does* finds it
where the other nine put it.
"""

from __future__ import annotations

from pydantic_ai.capabilities import Thinking
from pydantic_ai.settings import ThinkingEffort


def build_thinking(effort: ThinkingEffort | None) -> Thinking:
    """Turn a chosen effort into the capability that carries it.

    `True` is the unified setting's "on, at whatever effort this provider
    defaults to" — which is exactly what an unset effort asks for. Binding the
    capability at all is the decision to think; the level is the refinement.
    """
    return Thinking(effort=effort or True)
