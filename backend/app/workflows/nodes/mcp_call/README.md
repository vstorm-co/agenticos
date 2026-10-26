# mcp.call

Calls one tool on one of the organization's MCP servers, with arguments bound
from earlier steps. The server must be organization-owned and enabled; its
credential comes from the vault, as an agent's does. The output is the tool's
text, its structured answer when it returns one, and whether it answered with
an error - which fails the step unless `on_tool_error` is `complete`.

`approval` decides when a person approves the call first: `writes` (the default)
before a tool the server does not mark read-only, `all` before every call,
`none` never. The request goes to the same approvals inbox `human.approval`
uses; a rejection fails the step with `MCP_CALL_REJECTED`.

MCP has no idempotency key of its own. `idempotency_key_argument` names a tool
argument the step fills with its stable operation key (the same on every retry,
over any bound value of that argument); the tool must declare it as text, or the
step fails with `MCP_IDEMPOTENCY_ARGUMENT_UNDECLARED` before calling, and publish
refuses an argument the recorded schema lacks. Such a step is `idempotent`.

A failure before the tool was called is a retryable `MCP_CALL_FAILED`. After the
call, it is retryable for a keyed call or a tool the server marks read-only (the
live listing, else the recorded one); after an unkeyed call to any other tool the
step ends `Uncertain` and a person decides, because the tool may have acted.
