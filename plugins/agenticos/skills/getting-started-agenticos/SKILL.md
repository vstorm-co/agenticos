---
name: getting-started-agenticos
description: Chooses an AgenticOS adoption path from a repository, a fork, a local installation or an existing deployment. Use when the user wants to get started, install AgenticOS, connect its MCP server or understand what is needed for their own use case.
---

# Start from the user's actual position

Find the intended outcome, audience and current installation. A fork is useful
when changing platform code; deploying upstream images needs no fork. A configured
organization needs neither a clone nor a new installation to build resources.

| Starting point | Next work |
|---|---|
| Existing MCP tools | Read `whoami`; use `get_platform_context` if advertised |
| Existing server, no connection | Obtain its API `/mcp` URL and connect the client |
| No installation | Use the deployment skill's local or single-host path |
| Platform code needs changing | Use the development skill's fork path |
| A business outcome | Discover existing resources, then use the solution-building skill |

Do useful discovery before asking for information already in the repository or
connection. Ask only for decisions that change the result: target organization,
audience, host, external accounts or permitted effects. Work within the user's
existing authorization; a missing optional preference does not block preparation.

## Connection and compatibility

For Claude Code, the console lists the command under Settings → MCP clients:

```bash
claude mcp add --transport http agenticos https://<api-host>/mcp
```

Finish OAuth in the browser. The consenting member selects the organization and
scopes. Do not request their password, token, OAuth code or callback URL in chat.
Ordinary organization keys cannot reach assistant-only lifecycle operations.

The baseline plugin was tested against 1.82.2. New setup, release and bundle
operations require MCP contract 1. If `get_platform_context` exists, read its
`mcp_contract_version`, `features`, authentication and granted scopes. Otherwise
use only the tools actually advertised; explain what needs an upgrade. Never
probe a missing feature by attempting a write. See [compatibility.json](../../compatibility.json).

## Handoff

Continue into the matching skill in this plugin. Report the chosen deployment and
organization, what is ready, and the next missing dependency. An installation is
not ready just because containers started: require a completed agent run and an
accessible console before reporting an end-to-end success.
