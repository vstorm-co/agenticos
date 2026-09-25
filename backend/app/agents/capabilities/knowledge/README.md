# Knowledge

Search the knowledge collections an agent is bound to.

The collections themselves are **not** configured here - they are a field on the
agent spec, resolved server-side into vector-store names and handed to the run
through `AgentDeps`. The model decides *what* to search; it can never decide
*where*.

Configuration covers defaults and the optional query-analysis step:

| Field | Why it exists |
|---|---|
| `default_top_k` | How many passages when the model does not say |
| `query_analysis_mode` | Optional pre-retrieval query expansion, off by default |
| `query_analysis_max_variants` | How many rephrasings `multi_query` may add |

The capability builds to `None` when no collection is bound: advertising a
search tool that always returns empty is worse than not having one, because the
model keeps trying it.

## Query analysis and expansion (#1649)

Short, underspecified or vocabulary-mismatched queries under-retrieve. An opt-in
step, off by default, expands the query before retrieval:

- `multi_query` - the run's model writes up to `query_analysis_max_variants`
  rephrasings; the original and the variants are each retrieved and their results
  fused with RRF. **One model call.**
- `hyde` - the run's model writes a short hypothetical answer passage and
  retrieval runs against *its* embedding rather than the bare question's. **One
  model call.**

The load-bearing invariant: expansion produces alternative query *strings* only.
Every produced query is retrieved under the *same* server-trusted `RetrievalScope`
and the same business filters as the original (the scope and filters are resolved
once and bound into a closure in `_search.py`, then handed to
`retrieval.fuse_over_queries`). Expansion never touches the scope or the filters,
so it can widen recall but **never access** - an expanded query cannot reach
another tenant's or an out-of-scope chunk. This is why the step lives above
retrieval rather than inside the store.

Both modes inherit the run's own model (`ctx.model`), whose credential was
resolved from the vault - there is deliberately no configurable model name, which
on this multi-tenant platform would resolve against process environment variables
(the `compaction` capability documents the same choice). The nested call runs on
its own usage with a two-request limit, checks the run's budget before it goes
out, and is wrapped in `MeteredModel`, so each response is booked to the run's
ledger exactly once even when the model searches in parallel. It degrades to the
plain query when the run's model cannot make a request-response call (a realtime
model) or when the call fails in an expected way - a provider error, a
misbehaving model, its own limit, a spent budget. Expansion improves recall when
it works and is never the reason a search fails. Any other exception is a bug, so
it is not turned into a fallback: it leaves the search and reaches the tool's own
failure handler, which logs it with its traceback.

There is no keyword mode. The search tool's retrieval service is built from the
deployment's `RAGSettings`, whose `enable_hybrid_search` is off and set by
nothing, so a keyword-boosted string would only be embedded differently - it
would never reach a BM25 leg. A mode is permanent spec format, so it waits until
the lexical leg is real.

The variants are retrieved one after another, each embedding its own string: the
store embeds inside `search`, per collection and with that collection's own
embedder, so batching them into one embedding call needs a vector-taking search
the store does not have yet.

It composes with a future reranker (#142): expansion widens the candidate set,
fusion orders it, and a reranker would reorder what fusion returned.

## Renaming the search tool

The same search is "Search orders" for one agent and "Look up policies" for
another, and steering a model usually means rewording a tool rather than writing
a new one. That is still true - it is just no longer this capability's business.

`tool_name` and `tool_description` used to be fields on `KnowledgeConfig`, and
this was the only capability that had them. They are gone. A binding says it the
way every capability says it:

```yaml
capabilities:
  - id: knowledge
    tool_overrides:
      search_documents:
        name: search_refund_policy
        description: Look up the refund policy before quoting a window to a customer.
```

Keyed by the tool's stable id, which is what the approval gate decides on - the
old field was invisible to it, so a renamed tool could not be gated at all (see
`../approval/README.md`). A version-3 spec that used the old keys is folded into
this shape when it loads, so nothing published against it changes what its model
sees.
