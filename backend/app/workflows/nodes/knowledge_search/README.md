# knowledge.search

Searches one or more knowledge collections for a bound `query` and returns the
best passages as typed sources: `document_id`, `filename`, `collection`,
`page`, `chunk`, `score` and `content`. An agent can take them as context, and
`core.output` can return them to the caller.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `query` is bound |
| `out` | output | `KnowledgeSearchOutput` | `sources: SourceRef[]`, best first |

Config: `collection_ids` (picked from the collections you can read) and
`top_k` (1 to 50, default 5).

## No results is an answer

An empty `sources` list is a successful search. When a workflow should answer
differently without context, bind the sources to a `logic.if` and use the
condition `value`: an empty list is false.

## Who may search what

Publishing refuses a collection the graph's author cannot read. Each run checks
every collection again against the run's principal before it searches, because
access can be withdrawn between publishing and running. A collection that is
gone or no longer readable fails the node with `COLLECTION_NOT_ACCESSIBLE`. The
node never searches fewer collections than the graph names.

Tenant isolation is the retrieval service's own. Each collection's scope is
resolved by the vector store, as an agent's knowledge tool resolves it, so a
search never reaches another organization's rows.

## Effect kind and retries

`effect_kind="read"`, `retry_guarantee="idempotent"`. A failure inside the
vector store or the embedding provider is `KNOWLEDGE_SEARCH_FAILED` and is
marked retryable. The provider's own error text stays in the log, because it can
carry a request URL with a key in it.
