# Historical shipped AgenticOS templates

Verbatim public `backend/app/core/catalog/agent_templates/general/agenticos/AGENT.md`
from release history, parsed by the official template reader in regression tests:

- `nov14/AGENT.md`: `2c92a094a934bef7f841b1bc808e8e67be4e0426`.
- `nov12-release/AGENT.md`: release `v1.67.0`, commit
  `e465a39d72e84ae7122c5950edbaf906721fda1a`.
- `nov12/AGENT.md`: `2d987f5d92d7a6973bd54bc04c59563351d6c312`.

These fixtures prove exact shipped provenance; an agent's name does not authorize
replacing a custom prompt or configuration.

History also records the files-only sandbox variant produced by the historical
`for_this_deployment` when a container workspace was unavailable. Regression
tests verify upgrades after a workspace becomes available.
