---
title: "Answer questions from your database"
description: "Connect a self-hosted Postgres MCP server behind a read-only role and a views-only schema, and let an agent query it."
---

# Answer questions from your database

Connect a Postgres MCP server so an agent can answer questions from your own
database, and put a read-only role and a views-only schema between the agent
and your tables before you do. This is a procedure to run, not a report of a
measured deployment: the MCP server this recipe needs cannot be reached from
this installation, for a reason explained below, so nothing here was run
end to end against a live agent.

## What you need

- A [running installation](../install.md) with a model profile.
- A Postgres MCP server you run yourself, reachable at a URL this deployment
  can dial. The catalog's `postgres` entry is exactly this: no hosted URL, a
  bearer token *your own server* checks, and a warning to point it at
  read-only views rather than a primary with write access. See
  [the catalog](../mcp.md#data-and-analytics).
- `connections:manage`, to register the organization connection.

## Why a read-only role and a views-only schema

**MCP tools are outside the approval gate.** A capability's tools can be held
for a person to approve; an MCP server's cannot; there is no per-call review of
the SQL an agent's query tool runs. Whatever the connected server can do, the
agent can do without asking - see
[MCP tools are outside the approval gate](../governance.md#an-approval-inside-a-delegation).
The database credential itself has to be the boundary, not a setting on the
agent.

Two decisions do that work:

- **A role with no write privileges**, so the worst a wrong or manipulated
  query can do is read something it should not - never change or delete a row.
- **A schema of views, not the base tables**, granted to that role instead of
  the tables themselves. A view can drop columns a model should not see and
  pre-aggregate what it returns, which is both a privacy boundary and a
  cheaper query for the agent to write.

## Prepare the input

A small synthetic `orders` table, in a database of its own:

```sql
CREATE TABLE orders (
    id           serial PRIMARY KEY,
    customer     text NOT NULL,
    status       text NOT NULL CHECK (status IN ('paid', 'refunded', 'pending')),
    amount_cents integer NOT NULL,
    created_at   date NOT NULL
);

INSERT INTO orders (customer, status, amount_cents, created_at) VALUES
    ('Ada',     'paid',     4200, '2026-09-01'),
    ('Grace',   'paid',     1800, '2026-09-02'),
    ('Ada',     'refunded', 4200, '2026-09-03'),
    ('Rex',     'paid',     9900, '2026-09-05'),
    ('Grace',   'pending',  2500, '2026-09-06'),
    ('Linus',   'paid',     3300, '2026-09-06'),
    ('Rex',     'paid',     1500, '2026-09-08'),
    ('Ada',     'paid',     6000, '2026-09-09');
```

The views-only schema and the role the MCP server's connection string
authenticates as:

```sql
CREATE SCHEMA reporting;

CREATE VIEW reporting.daily_paid_totals AS
SELECT created_at, count(*) AS paid_orders, sum(amount_cents) AS paid_amount_cents
FROM orders
WHERE status = 'paid'
GROUP BY created_at
ORDER BY created_at;

CREATE VIEW reporting.status_counts AS
SELECT status, count(*) AS orders, sum(amount_cents) AS amount_cents
FROM orders
GROUP BY status
ORDER BY status;

CREATE ROLE shop_readonly LOGIN PASSWORD 'change-me';
GRANT CONNECT ON DATABASE shop_demo TO shop_readonly;
GRANT USAGE ON SCHEMA reporting TO shop_readonly;
GRANT SELECT ON reporting.daily_paid_totals, reporting.status_counts TO shop_readonly;
REVOKE ALL ON SCHEMA public FROM shop_readonly;
```

The reference answer, so you can check a reply against the source rows:
`status_counts` gives paid 6 orders / 26700 cents, pending 1 / 2500, refunded
1 / 4200. `shop_readonly` querying `orders` directly is refused with
`permission denied for table orders` - the views are the only door.

## Connect the server

1. In an agent's **Toolbox → MCP servers**, choose **Connect a server** and
   pick **PostgreSQL** from the catalog, or connect it once from **MCP
   servers** in the organization settings so more than one agent can bind it.
2. Point the connection at your own running Postgres MCP server (for example
   [`crystaldba/postgres-mcp`](https://github.com/crystaldba/postgres-mcp))
   configured with `shop_readonly`'s connection string and its restricted,
   read-only mode. Paste the bearer token that server checks - not the
   database password - as the connection's token.
3. On the agent's binding, narrow `allowed_tools` to the read-only ones the
   server exposes, on top of whatever the connection itself already allows.
4. Bind only this connection, set a budget, and set instructions that name the
   two views and tell the agent to say when a question needs a column or a
   table the views do not carry, rather than guessing.

## Why this could not be run here

Connecting the server was attempted against this installation and refused:

```text
This MCP server URL cannot be used: Blocked: 'localhost' resolves to
private/internal address '::1'. SSRF protection does not allow requests to
internal networks.
```

An MCP connection's URL is refused unconditionally for any loopback, private,
link-local or shared-CGNAT address - there is no local-development exception,
because the same check also guards a `cdp_url` and every OAuth discovery hop.
See [a URL this deployment must not reach is refused](../mcp.md#a-connection).
A Postgres MCP server reachable only on `localhost` or a private network
address - the ordinary place to first run one - cannot be connected from this
deployment's own machine. Reaching it needs a routable address: a small host
with a public or VPN-reachable IP, or a tunnel, in front of the server.

The SQL above was run and checked directly against Postgres; the role refusal
and the view totals quoted are real. What was not verified is an agent
actually querying through the connected server, because the server was never
reachable to connect.

## Check the result

| Check | Reference |
| --- | --- |
| A question naming the paid total | 26700 (six paid orders) |
| A question about pending orders | 2500 (one order) |
| A question naming a column no view exposes (e.g. the customer name) | The agent says it cannot answer that from what it is bound to |
| A query the role cannot run (an update, a delete) | Refused at the database, `permission denied` |
| `allowed_tools` narrowed to read-only tools | A write tool the server offers is not in the model's toolset at all |

## When it goes wrong

- **The connection is refused with an SSRF message.** The server's address is
  loopback, private or otherwise internal to this deployment's own network -
  see above. Put a routable address in front of it.
- **The agent reads the base table instead of the views.** `shop_readonly` was
  granted on `public` as well as `reporting`, or the base table's schema was
  never revoked from it. Re-run the `REVOKE` above.
- **A query the agent runs looks like it changed something.** It could not
  have, if the role truly has no write grant - check the role's grants before
  assuming the agent misbehaved.
- **The connection probes successfully but the Builder lists no tools.**
  Nothing has probed it yet, or the last probe failed - `POST
  /mcp-connections/{id}/test` refreshes it.
- **Two agents need different access to the same database.** Connect the
  server twice, under two names, each with its own role and its own views -
  one server, two credentials, never one role widened for the stricter agent.

## Record the trial

Keep the SQL that created the fixture, the role's grants, the view
definitions, the connection's `allowed_tools`, and the agent's binding-level
`allowed_tools`. A person still decides which columns belong in a view before
an agent ever reaches it - narrowing access after an agent is already asking
questions is a much harder conversation than deciding it first.
