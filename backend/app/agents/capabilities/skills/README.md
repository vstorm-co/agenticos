# Skills

Progressive disclosure over an organization's written know-how. The agent reads
names and one-line descriptions; it loads a body only when it decides one is
relevant.

Two decisions worth keeping:

**Skills are passed in memory.** The toolset accepts `Skill` objects directly,
so a run never touches the disk — no temp-file cleanup, no race between two runs
materialising the same skill, no path traversal surface.

**`run_skill_script` is excluded from the toolset**, not merely left unused.
Until there is a sandbox, it is remote code execution wearing a helpful name.

Which skills an agent gets is a field on the spec, resolved server-side by the
runner. A capability never queries the database.
