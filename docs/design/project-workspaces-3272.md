# Project workspaces: discussion 3272

This follow-up implements the shared-filesystem behavior requested in
[discussion #3272](https://github.com/vstorm-co/agenticos/discussions/3272),
as part of release candidate #3455. AgenticOS remains unmerged until acceptance.

## Files and execution

Project files have one authoritative store. An agent retains its own runtime,
toolchain and working directory. A mount-enabled Docker connection adds a live
filesystem at `/project`; commands receive `PROJECT_DIR=/project/<lease-id>`.
Shell and Python can use existing Project files immediately and write results
back without transfer calls or synchronization. Generic relative file paths
still address the agent's own workspace. The optional Project executor runs in
the Project's separate runtime when deliberately selected.

New Projects default to stored files and need no running Project container.
Existing Projects retain their backend. The mount supports stored files and
service-backed native filesystems that pass the required filesystem checks.
`transfer_project_file` remains an optional explicit bounded copy; it is not
needed for the live mount and is not described as its implementation.

## Isolation and lifecycle

Sandboxd receives a typed, application-issued binding for an exact tenant and
session, never model-selected host paths, URLs or images. A trusted Rust NFS
export helper reaches the operator-configured API gateway on its own bridge;
it publishes no ports. Docker mounts its NFS volume into an unprivileged agent.
The agent receives neither helper credentials nor Docker privileges.

Immutable run-lease directories prevent an existing filehandle from silently
changing to another Project. Every RPC checks the current run, actor membership,
credential scopes, conversation audience, Project grant and generation, and
routine source policy. Writes commit before acknowledgement. Leases renew while
the run is active, expire after 90 seconds without renewal, and are revoked on
selection change, pause and cleanup. Continuations restore selection rather than
persisted live authority. Project files remain outside agent snapshots, Skills,
attachments and output-spill staging.

This first implementation supports private conversation- and run-scoped Docker
executors with an explicitly enabled host contract. Other providers and shared
executor scopes refuse admission. Existing sessions without the mount require
explicit migration/recreation preserving their own files. An exporter restart
invalidates its handles and stops the retained agent; recovery requires an
explicit remount, never command replay or an empty replacement workspace.

Regular files and directories are supported. Symlinks and ownership changes are
not supported. Native writable filesystems require extended attributes and atomic
hard-link publication for durable exclusive creation. Linux container storage
passed the probe; the tested macOS bind mount returned `ENOTSUP` and is refused.
External API renames invalidate path-based handles; full POSIX inode identity
across external delete/recreate is not claimed.

## Console acceptance follow-up

The primary chat card shows the active Project context, with executor overrides
under Advanced. Personal coding accounts are a separate disclosure. Project
resources and export use typed groups, real authorized avatar metadata and
responsive dialogs. Python Actions presents inputs, callable functions and its
result together. Personal navigation is edited from the sidebar or the same
profile dialog, with actions pinned below its scrolling options. Project chat
counts sit beside the Chats tab instead of adding a second toolbar. Organization
role defaults remain in organization settings.

Unrelated settings stay enabled while another section saves. Organization writes
are serialized and retain their original organization identity. Optional
onboarding guidance links the new configuration without making it mandatory;
snoozed reminders disappear rather than becoming a second plain sidebar link.

Focused verification and the exact-head CI run are recorded in PR #3455.
Production deployment and release publication still require maintainer approval.
