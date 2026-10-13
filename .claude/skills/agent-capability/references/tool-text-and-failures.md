# What a tool says, and how it says a call went wrong

Two things every tool in `app/agents/capabilities/**` owes, both of them prompt.
`docs/reference/capabilities.md#what-a-tool-tells-the-model` is the same rule at
behaviour level; this is how it is written.

## The docstring is the description

The tool function's docstring is what the model reads before choosing the tool —
there is no second place to put it. Four parts, and the fourth is the one that
keeps being left out:

```python
async def search_documents(ctx: RunContext[AgentDeps], query: str, top_k: int | None = None) -> str:
    """Search the organization's documents for passages relevant to a question.

    Use before answering anything that depends on internal knowledge, and cite
    the document names from the results rather than paraphrasing.

    Args:
        query: What to look for, phrased as the user would ask it.
        top_k: How many passages to return. Omit to use the agent's default.

    Returns:
        Formatted passages with their source documents and relevance scores.
    """
```

1. **One sentence: what it does.** It is also what `CapabilityToolInfo.description`
   carries into the Builder, so a person choosing what to approve and the model
   choosing when to act read the same words.
2. **When to use it — and when to use another tool.** `glob` searches
   recursively where `ls` does not; `create_chart` is for numbers you already
   have and `generate_image` for something to be drawn. Naming the neighbour is
   what stops the wrong-tool call.
3. **Every argument**, with its default and its ceiling. `limit: How many to
   return. Omit for the agent's default.`
4. **`Returns:` — the shape of the answer**, its failures, and any truncation.
   This is the half a tool description usually omits, and the model cannot infer
   it: that `grep` answers in three shapes depending on `output_mode`, that
   `glob` stops at 100 paths and says `... and N more`, that a failed `execute`
   still returns its output. A tool whose answer can be a slice must say so, or
   the model reasons from the slice as though it were the whole set.

`charts/_toolset.py` is the worked example — worth reading before writing a new
tool, including for what it does with a shape a JSON Schema cannot express.

**A tool from a library** (`sandbox`, `skills`, `planning`, `subagents`) does not
get its text rewritten here: import it. `sandbox` takes
`TOOL_TEXT[id].summary` for the catalog and hands the model the same object's
full rendering, so the two cannot drift. Writing a short label here instead is
how a tool's description — the strongest prompt in the product — becomes a
caption for a form.

## Failures: a mistake, a result, and a refusal

`ModelRetry` means *you can fix this by calling again differently*. A returned
string means *this is the result; reason about it*. Which one applies is decided
by whose mistake it was, not by how bad the news is.

| The failure | Shape | Example here |
|---|---|---|
| The arguments the model composed | `steer(ctx, ...)` | a chart series with the wrong number of values; `read_context` on a name that does not exist; a `NameError` in code `run_python` was given |
| Transient failure of what is behind the tool | `steer(ctx, ...)` | the vector store is down; the search provider rate-limited us |
| A result that is bad news | return the text | a command that exited non-zero; a search with no hits; a channel this bot cannot see |
| A refusal | return the text | a permission rule; a capability the deployment does not offer |

The second row is the one that looks wrong and is not: an error in the shape of
a result reads to the model as "nothing found", and it then answers from memory,
confidently, without saying it had to. `web_research` carries that reasoning in a
comment beside the call.

The fourth row is the one that is dangerous to get wrong: a retry prompt on a
refusal invites the model to look for a way around it.

## Always `steer`, never a bare `raise ModelRetry`

```python
from app.agents.capabilities._failures import steer

if len(series.values) != len(x_values):
    return steer(ctx, f"Series {series.key!r} has ... Send one number per x value.")
```

A tool call gets `retries` attempts — **one**, by default, and nothing in this
repository raises it. A `ModelRetry` raised past that budget does not fail the
call: it ends the whole run with `UnexpectedModelBehavior`. So a model that sends
the same malformed chart twice would take the conversation down with it.

`steer` returns the message instead of raising on the last attempt. Steered while
there is budget for it; never worse than the string it would have returned.

Two consequences when adding a tool:

- **It needs `ctx`.** A tool registered `takes_ctx=False` cannot see the retry
  budget. `RunContext` is excluded from the JSON schema, so adding it costs the
  model nothing.
- **Test both halves.** `_tool_ctx()` for the retry, `_tool_ctx(retry=1)` for the
  floor — the second is the one that proves a bad call cannot end the run.

`pydantic-ai-backend` holds the identical rule for the workspace tools, in
`toolsets/_failures.py`, with the same helper name.

## What the message says

Written for the model, not for a log reader: name the argument, say what a
correct one looks like. `"Series 'revenue' has 0 value(s) for 1 x value(s). Send
one number per x value, in the same order."` — not `"validation error"`, and
never a stack trace, an internal identifier or a provider's raw message (which
carries request URLs, and a URL carries a key). The exception's own text belongs
in the `logger.exception` line beside the call — `.claude/rules/exceptions-security.md`
has that rule in full.
