# Memory

Memory has two stores. The claims ledger keeps short facts, preferences and
decisions with provenance and correction history. Named notes hold longer
material, such as a briefing on a person or a checklist.

Use `remember` for a new short memory, `correct_memory` for a correction and
`recall` for a specific topic. Use `write_memory` for longer material and
`read_memory` to open it. The automatic overview lists recent available notes
by name, so writing one does not require a second write to an index. Existing
`MEMORY.md` notes, including short inline entries, remain editable.

## What reaches the prompt

| Audience | Automatic overview | Tools |
| --- | --- | --- |
| Private chat or linked direct message | Current scoped claims and counts, saved index text and recent note names | Personal memory and permitted shared claims |
| Group channel | None | The room's own memory |
| Shared transcript or project chat | No personal memory | Permitted project and organization claims |
| Anonymous | None | No personal memory |

The runtime resolves the audience and store server-side. The overview is read
from the existing stores, never saved as a second copy. It is bounded by the
claims profile limit, the legacy index limit and at most 12 note references.
Note bodies are opened on demand. The counts describe the claims actually added
to the prompt.

`inject_context` defaults to true in a bound Memory capability. Turning it off
leaves tool access and eligible Memory Maintenance jobs in place.
`allow_personal` controls whether the agent reaches personal memory at all.
The maintenance worker checks the enabled capability and an enabled system
model, and writes evidence-backed claims to the ledger. It takes no action
based on whether a model happened to call a memory tool.

Memory deletion and suppression remain controlled by the owner or the
authorized operator. A delegate does not inherit the parent audience.
