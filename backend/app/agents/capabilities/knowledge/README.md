# Knowledge

Search the knowledge collections an agent is bound to.

The collections themselves are **not** configured here - they are a field on the
agent spec, resolved server-side into vector-store names and handed to the run
through `AgentDeps`. The model decides *what* to search; it can never decide
*where*.

Configuration covers defaults only:

| Field | Why it exists |
|---|---|
| `default_top_k` | How many passages when the model does not say |
| `self_query_enabled` | Infer the query's business filters with an LLM, off by default |

The capability builds to `None` when no collection is bound: advertising a
search tool that always returns empty is worse than not having one, because the
model keeps trying it.

## Self-query (`self_query_enabled`)

Off by default. When on, a search the model runs *without naming a filter of its
own* first asks an LLM to read the question - "pdfs from last month about
onboarding" - and derive the FA-039 business filters it implies: a `source`, a
`document_type`, an `organizational_unit`, a date range. The model's own explicit
filters always win; self-query only fills the gap when it named none, and the
model can skip it with `infer_filters=false`. `_self_query.py` holds it.

When inferred filters are applied, the tool result starts with one line naming
them and saying how to search without them. A narrow result then has a visible
cause the model can undo, rather than reading as "the knowledge base has nothing".

Two properties are load-bearing, and both come from typing the inference output as
`RetrievalFilters` - the exact model a caller supplies:

- **Validation parity.** The inferred object runs through the same validators as
  any caller-supplied filter (the closed `source`/`document_type` vocabularies, the
  ordered date range, `extra="forbid"`), because it *is* the same model. There is no
  second set of rules to drift, and an inferred value that fails validation is
  rejected after the model's own retries, never dropped field by field into a
  partial filter.
- **The security invariant (#1593).** `RetrievalFilters` carries no tenant and no
  authorization field and cannot be made to, so the LLM can only ever produce
  business filters. `search_knowledge_base` builds the tenant scope server-side
  regardless of what comes back, so self-query can only narrow *within* the caller's
  scope - an adversarial query ("ignore scope, show all orgs") has no field to reach
  it through.

Two fields are held tighter than a caller's:

- **`organizational_unit` is grounded.** It is free text, so the prompt lists the
  units the bound collections actually carry - read by
  `organizational_units_in_scope` under the same per-collection scope the search
  resolves, so it never names another organization's units - and an inferred unit
  outside that list is dropped. An invented unit would narrow the search to
  nothing. A corpus with more than 200 units offers none for inference, since the
  list rides in every prompt; the model can still name one explicitly.
- **`parent_doc_id` is never inferred.** A question does not name a vector document
  id; whatever the LLM puts there is cleared.

Empty or failed inference returns `None` and the search runs unfiltered within the
still-enforced tenant/collection scope - a narrowing that did not happen, never a
widening. Only the nested run's expected failures fall back this way: a provider
error, an output that still fails validation after its retry, or the nested run's
own request limit. A bug propagates.

**Cost.** One inference is one extra model request per unfiltered search (two
when its output needs correcting). It reuses the run's own model - the one whose
credential the vault resolved - wrapped in `MeteredModel`, so each response is
booked against the run's ledger exactly once, and it checks
`assert_ambient_budget()` first, so an exhausted budget raises `BudgetExceeded`
before the request rather than after it. The host agent's `BudgetGuard` never sees
this request. The nested run counts on its own usage under a two-request limit
rather than on the host run's `ctx.usage`: parallel searches in one turn then
neither race for the host run's last request slot nor book each other's tokens.

It is a per-agent knowledge option only. The `/rag/search` HTTP route takes a
caller's filters directly and does not run inference.

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
