"""How a tool tells the model it got the call wrong.

Two shapes, and they say different things. `ModelRetry` means *you can fix this
by calling again differently* - the message goes back as a retry prompt and the
model gets another attempt. A returned string means *this is the result; reason
about it* - the run moves on with the answer it was given.

Which one a failure takes is decided by whose mistake it was:

- **The model's, in the arguments it composed** - a chart series with the wrong
  number of values, a context file that does not exist, a `NameError` in Python
  it wrote. `ModelRetry`, through :func:`steer`.
- **A transient failure of the thing behind the tool** - a search provider that
  is down, a knowledge base that timed out. Also `ModelRetry`, and for a reason
  worth stating: an error in the shape of a result reads to the model as "nothing
  found", and it then answers from memory, confidently, without saying that it
  had to.
- **Everything else** - a result that is simply bad news (a command that exited
  non-zero, a search with no hits), a capability the deployment does not offer, a
  refusal. Returned as text. A retry prompt on a refusal in particular invites the
  model to look for a way around it.

`steer` exists rather than a bare `raise ModelRetry` because retries are not
free. A tool call gets `retries` attempts - one, by default, and nothing here
raises it - and the attempt *after* the last one does not fail the tool, it ends
the whole run with `UnexpectedModelBehavior`. So a model that sends the same
malformed chart twice would take the conversation down with it, where returning a
string would have let it apologise and carry on. On the final attempt the message
is therefore returned rather than raised: steered while there is budget for it,
and never worse than the string it would have returned anyway.

`pydantic-ai-backend` holds the same rule for the workspace tools, in
`toolsets/_failures.py`, with the same helper name.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import ModelRetry
from pydantic_ai.tools import RunContext


def steer(ctx: RunContext[Any], message: str) -> str:
    """Ask the model to try again, while it still has an attempt left.

    Args:
        ctx: The tool call's context, for how many retries remain.
        message: What went wrong, and what a different call should do about it.
            Written for the model: name the argument and what a correct one
            looks like, never an internal identifier or a stack trace.

    Returns:
        `message`, on the last attempt, for the caller to return as its result.

    Raises:
        ModelRetry: Otherwise - the message reaches the model as a retry prompt.
    """
    if ctx.last_attempt:
        return message
    raise ModelRetry(message)
