# Skills

Progressive disclosure over an organization's written know-how. The agent reads
names and one-line descriptions; it loads a body only when it decides one is
relevant.

Three decisions worth keeping:

**Loading remains native.** Each skill is a deferred capability. `_loader.py`
adapts the framework's catalog to “available skills” and its loader to
`read_skill`; `read_skill_resource` reads supporting files. The pinned SDK has no
public loader configuration (upstream pydantic-ai#12781), so the private imports
are isolated in this adapter. No globals or dependencies are patched.

Its namespaced typed parts extend the SDK's native load parts, preserving load
state, duplicate detection, tools and authoritative instruction delivery in text,
streaming and realtime. Persist messages through `dump_messages`, which serializes
generic copies of only the extended loader parts, retaining their kind and fields.
Other SDK serializers, including instruction ids and cache baselines, stay in
effect. Legacy typed calls and returns are adapted before a run,
including pending approvals; their call ids and arguments remain unchanged.
The spec's stable approval key remains `load_capability`.

**Skills are passed in memory.** The library accepts `Skill` objects directly,
so a run never touches the disk - no temp-file cleanup, no race between two runs
materialising the same skill, no path traversal surface.

**`run_skill_script` is excluded**, not merely left unused. It would be a second
way to run things beside the sandbox's `execute`, with a second set of rules to
get wrong. A skill's scripts reach a run as files under `/workspace/skills/`
instead - see `app/services/skill_workspace.py`.

Which skills an agent gets is a field on the spec, resolved server-side by the
runner. A capability never queries the database.

Long static references are adapted to SDK callable resources with bounded
character ranges: 8,000 by default and at most 20,000 per read. The existing
`read_skill_resource` tool accepts `args` containing `offset` and `limit`; the
reply names the next offset. Skill loading and resource authority stay with the
SDK, while the adapter validates page arguments before slicing.
