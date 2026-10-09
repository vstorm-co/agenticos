# platform

Lets an agent operate AgenticOS itself - the Platform Assistant's hands (#1798).

## What it is

The same operations the platform's MCP server offers Claude Code
(`app.services.platform_mcp._tools`), handed to an agent as tools. Each one is a
call to the public API made in-process with a credential the runner mints for
the person the run acts for, so the agent can do exactly what that person could
do over HTTP - their role, their grants, the organization's budget and audit -
and nothing more.

## What it deliberately does not do

- **Act as anyone else.** There is no service identity. A run with nobody behind
  it (an anonymous widget visitor) gets no credential, and the capability builds
  nothing.
- **Write without a person.** Every tool that changes something is declared
  side-effecting, so the approval gate holds it until a person approves the
  exact call. An operator can still gate the reads too, per tool.
- **Delete, publish or touch a credential.** None of those is an operation here.
- **Speak MCP to itself.** The MCP server and this capability share the tool
  functions, not a network hop: the protocol adds nothing between an agent and the
  platform it runs on, and the run would otherwise depend on reaching its own
  public address.
