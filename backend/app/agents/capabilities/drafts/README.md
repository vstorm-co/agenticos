# Drafts

Exposes one tool, `write_draft`, for text the person will send or paste somewhere
else: an e-mail, a chat reply, a post. Nothing is drawn here. The tool validates
the card and answers with a fixed sentence; the web chat rebuilds the card from
the stored call's arguments, the way it rebuilds a drawing, and the share-by-link
page gets it rebuilt by the server.

The tool is offered only where the card shows: `AgentDeps.shows_drafts`, set by
the web chat's runner and its approval resume alone. A delegate never sees it.
Everywhere else the agent writes the draft in its answer.

## Layout

| File | Holds |
|---|---|
| `_spec.py` | The format and its limits - `DraftField`, `DraftVersion`, `DraftCard`, `parse_draft_card()` |
| `_toolset.py` | `DraftsToolset`: the one tool, its prompt, and the unconstrained input models |
| `_capability.py` | The `Drafts` dataclass and `get_toolset()`, filtered to where the card shows |
| `__init__.py` | Registry entry and exports |

**Why `_spec.py` is separate.** The share-by-link rebuild parses a stored call's
arguments. It is a consumer of the format, not of the agent, so the format sits
in a leaf module that imports no toolset and no capability.

**Why the tool's parameters carry no limits.** Pydantic AI validates parameters
before the method runs and ends the run when its retries are spent. The limits
live on the `_spec.py` models, built inside the method, so a card that breaks one
goes back through `steer` and never costs the turn.

Two instructions in the tool's description are load-bearing: write **plain text**
unless asked otherwise, and **do not repeat the draft** in the answer. The
capability's instruction and the tool's result say the latter again, because the
description alone left gpt-4.1 quoting the draft in about a third of runs. A third, for
details the model does not know: it writes a short placeholder in square brackets
(`[Your Name]`) instead of inventing one, and keeps brackets already in the text it was
given; the card shows those in red. A result that does not open with `Drafted ` (a refusal on the last
attempt) draws no card.
