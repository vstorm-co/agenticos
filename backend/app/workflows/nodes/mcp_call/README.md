# mcp.call

Calls one tool on one of the organization's MCP servers, with arguments bound
from earlier steps. The server must be organization-owned and enabled; its
credential comes from the vault, as an agent's does. The output is the tool's
text, its structured answer when it returns one, and whether it answered with
an error - which fails the step unless `on_tool_error` is `complete`.

`approval` decides when a person approves the call first: `writes` (the default)
before a tool the server does not mark read-only, `all` before every call,
`none` never. The request goes to the same approvals inbox `human.approval`
uses; a rejection fails the step with `MCP_CALL_REJECTED`. MCP has no
idempotency key, so a crash after the call repeats it on the retry.
