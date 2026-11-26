# Project workspaces: discussion 3272

This follow-up implements the separation requested in discussion #3272 within
release candidate #3455. It does not introduce a shared filesystem driver or
promise that two providers can mount the same directory.

## Files and execution

Project file tools use the project's authoritative shared files. Generic file
tools, working directory and commands use the selected executor, which defaults
to the agent's own environment even in a project chat. A command that needs the
project's own environment can select the Project executor through tools; no user
radio switch is required. A deliberate advanced UI/API executor pin remains
binding for the run.

A service-backed Project provides a command-capable shared workspace. A
stored-files Project needs no running container and provides no shell. New
Projects default to stored files; explicit automatic or named sandbox selection
remains available. Existing Projects retain their backend. Shared files persist
across project chats; an indefinitely running process is not part
of that contract. Selection by tools outside an attached project remains scoped
to one run, including approval/question continuations. It does not move the
conversation or give an unverified channel audience private Project access.

## Moving data when the agent's own CLI needs it

`transfer_project_file` transfers one named file as bytes, at most 8 MiB. The
model supplies paths, not file contents. `to_agent` prepares an input for the
agent's own tools; `from_agent` explicitly saves a result to the Project. Direct
commands in the Project workspace need no transfer.

The receipt identifies both namespaces, relative agent path, absolute command
path, byte count and SHA-256. An existing destination requires its expected
current digest. The service rechecks authority, Project generation and canonical
path boundaries. No automatic tree synchronization, deletion propagation,
implicit writeback, image/mount configuration or provider credentials cross the
boundary. Ordinary shell writes are not transactionally locked by the digest
check; this is conflict detection, not an atomic shared filesystem.

Sandboxd's current session-creation wire contract deliberately does not accept
mounts, and the configured remote providers have no common mount contract.
Changing `cwd` cannot expose another machine's files. A future shared mount
requires explicit infrastructure support and its own authorization/lifecycle
contract; it cannot be implemented as a path alias in this router.

## Console acceptance follow-up

The primary chat card shows the active Project context, with executor overrides
under Advanced. Personal coding accounts are a separate disclosure. Project
resources and export use typed groups, real authorized avatar metadata and
expandable dialogs. Python Actions presents inputs, callable functions and its
result together. Personal navigation is edited from the sidebar or the same
profile dialog; organization role defaults remain in organization settings.

Unrelated settings stay enabled while another section saves. Organization writes
are serialized and retain their original organization identity. Optional
onboarding guidance links the new configuration without making it mandatory;
snoozed reminders disappear rather than becoming a second plain sidebar link.

Focused verification and the exact-head CI run are recorded in PR #3455.
Production deployment and release publication still require maintainer approval.
