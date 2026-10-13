# Skills

Progressive disclosure over an organization's written know-how. The agent reads
names and one-line descriptions; it loads a body only when it decides one is
relevant.

Three decisions worth keeping:

**The catalog is the model's own.** Each skill is a deferred capability, so its
name and description sit in pydantic-ai's capability list and `load_capability`
opens it. This platform publishes no `list_skills` or `load_skill` of its own -
two tools that restate a mechanism the framework already has.

**Skills are passed in memory.** The library accepts `Skill` objects directly,
so a run never touches the disk - no temp-file cleanup, no race between two runs
materialising the same skill, no path traversal surface.

**`run_skill_script` is excluded**, not merely left unused. It would be a second
way to run things beside the sandbox's `execute`, with a second set of rules to
get wrong. A skill's scripts reach a run as files under `/workspace/skills/`
instead - see `app/services/skill_workspace.py`.

Which skills an agent gets is a field on the spec, resolved server-side by the
runner. A capability never queries the database.
