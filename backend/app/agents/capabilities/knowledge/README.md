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
| `parent_context` | Small-to-big retrieval: return each match with its surrounding context |

## Small-to-big retrieval (`parent_context`)

Small chunks retrieve precisely but read too narrowly; large chunks read well
but retrieve imprecisely. `parent_context` decouples the two: matching and
ranking always run on the precise small chunks, and only the text returned to
the model grows.

| Mode | What the model receives |
|---|---|
| `off` (default) | The matched chunk alone - identical to the pre-#1651 behaviour |
| `window` | The matched chunk plus its neighbours in the same document |
| `parent` | The whole parent document's chunks, in order |

Expansion happens on the return path only - it never changes which chunks
matched, their scores or their citations. It stays inside the caller's own
retrieval scope (it pulls siblings of an already-matched `parent_doc_id`, which
carries the same tenant tag), and it is bounded per result and per turn by the
deployment-level `parent_context_*` settings in `RAGSettings`, so a wide
document cannot blow the model's context budget. Overlapping windows are
de-duplicated across results.

The capability builds to `None` when no collection is bound: advertising a
search tool that always returns empty is worse than not having one, because the
model keeps trying it.

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
