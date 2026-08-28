# Resources

Everything around the product rather than in it: how to get help, how to
contribute, and how to extend the platform.

## Help AgenticOS

The project is young and the fastest way to help it is to use it and say what
broke.

<div class="grid cards" markdown>

- :material-bug:{ .lg .middle } **[Report a bug](https://github.com/vstorm-co/agenticos/issues/new)**

    What breaks, the sequence that triggers it, and how you would know it was
    fixed. That third one is the part most issues are missing.

- :material-lightbulb-on:{ .lg .middle } **[Suggest something](https://github.com/vstorm-co/agenticos/issues)**

    Check [the issue map](https://github.com/vstorm-co/agenticos/issues/168)
    first — it says what is already planned and what has no scope yet.

- :material-star:{ .lg .middle } **[Star the repository](https://github.com/vstorm-co/agenticos)**

    It is the cheapest signal that this is worth continuing.

</div>

## Development — contributing

Read the page that matches what you are touching. They are the repository's own
engineering notes, published rather than rewritten, so what you read is what
contributors read.

| Working on | Read |
|---|---|
| Anything at all, first | [Architecture](../architecture.md) — routes → services → repositories, and the request's transaction |
| A shape you have seen before | [Patterns](../patterns.md) |
| A feature, end to end | [Adding features](../adding_features.md) |
| A test, or a red coverage gate | [Testing](../testing.md) |
| A pull request | [Code review](../code-review.md) and [Branching](../branching.md) |

!!! warning "Three things that will bite you"

    A repository commits with `db.flush()`, never `db.commit()`. Background work
    that reads a row the request just wrote is handed over with
    `spawn_after_commit`, never `spawn`. And the platform layer is held at 100%
    coverage, enforced in CI. All three are in
    [Architecture](../architecture.md) and [Testing](../testing.md), and all
    three have been got wrong here at least once.

## Extending the platform

Adding to what AgenticOS itself can do, in Python. These are contributor
recipes — you need the repository checked out.

- [Add a capability](../howto/add-capability.md) — a new tool the model can call
- [Add a server to the MCP catalog](../howto/add-mcp-server.md)
- [Add an API endpoint](../howto/add-api-endpoint.md)
- [Add a background task](../howto/add-background-task.md)
- [Add a sync connector](../howto/add-sync-connector.md)

!!! tip "Before you write a capability"

    Ask whether it is really an [MCP connection](../mcp.md). A capability that
    would be an API client for one SaaS product is a server somebody has already
    written, and taking it into this repository means maintaining it against
    that product's API forever.

## Built on

AgenticOS is generated from the
[Full-Stack AI Agent Template](https://github.com/vstorm-co/full-stack-ai-agent-template),
and it stands on:

- [Pydantic AI](https://ai.pydantic.dev) — the agent runtime
- [FastAPI](https://fastapi.tiangolo.com) and [Pydantic](https://docs.pydantic.dev) — the backend
- [pgvector](https://github.com/pgvector/pgvector) — retrieval
- [Prefect](https://www.prefect.io) — background work
- [Next.js](https://nextjs.org) — the console
- [Model Context Protocol](https://modelcontextprotocol.io) — every integration

## Licence

Apache 2.0. See
[`LICENSE`](https://github.com/vstorm-co/agenticos/blob/main/LICENSE).
