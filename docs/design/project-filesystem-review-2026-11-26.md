# Live Project filesystem: verification and acceptance

This follow-up completes the live shared-filesystem requirement in
[discussion #3272](https://github.com/vstorm-co/agenticos/discussions/3272).
It belongs to aggregate PR #3455. AgenticOS merge and release remain subject to
maintainer acceptance; this report is not a release announcement.

## Resulting behavior

A supported private Docker executor retains its own working directory and tools.
Commands receive `PROJECT_DIR=/project/<immutable run lease UUID>`, backed by the
Project's authoritative files through a trusted NFS export. No input/output copy
or synchronization call is required. Independent conversations see the same
Project changes while their agent workspaces remain separate. The optional
Project executor and explicit bounded copy tool remain separate choices.

The dependency is
[pydantic-ai-backend 0.2.40](https://github.com/vstorm-co/pydantic-ai-backend/releases/tag/v0.2.40),
implemented in PR #158 and cut in PR #159. Package and sandboxd image versions
must match. The exporter ships inside that sandboxd image, rather than requiring
an unpublished local helper image.

## Evidence

- Real FastAPI filesystem routes, PostgreSQL, run-lease supervision, SDK broker,
  default Docker builder and two unprivileged Linux NFS clients passed together.
  Binary NUL bytes, tempfile exclusive creation, fsync, rename, truncate and
  directories were verified. Ordinary Project file services observed kernel writes;
  API edits appeared immediately through the existing mount.
- A second independent chat shared Project files without gaining the other
  agent's own workspace. A read-only run could read binary data and API edits;
  writes returned kernel `EROFS`, left content intact, and subsequent reads worked.
- Already-open file descriptors were refused after run completion, explicit lease
  revocation and workspace generation changes. Exact synthetic database fixtures
  and Docker resources were removed; the audit chain was retained. No model calls
  or explicit file transfers were used in these proofs.
- Current native helper code passed on Linux container storage as a non-root user,
  without network or extra capabilities. A Python audit hook observed the actual
  hard-link capability probe. Probe/staging cleanup, exclusive-create replay,
  rename/delete-recreate verifier refusal and non-blocking special-file rejection
  were checked. The tested macOS bind storage refused unsupported xattrs explicitly.
- Migration `0373_project_filesystem_mounts.py` passed downgrade/upgrade and
  `alembic check` on an isolated schema copy. Tenant-bound binding constraints,
  parent cascades and JSONB metadata matched the models. The preview database
  was not downgraded and its tmpfs PostgreSQL container was preserved.

The full gateway proof found a PostgreSQL JSONB defect in binary data that was
otherwise valid UTF-8. The shared state boundary now stores NUL-containing bytes
as base64 before quota checking, preserving timestamps and atomic rollback.
The unchanged full proof passed after that fix. Further regressions cover staged
uploads before first command, immutable admitted API-key ceilings, cleanup failure
accounting and compatibility with existing unmounted ordinary conversations.

## Limits and remaining acceptance

Host support is explicitly enabled; the gateway must be reachable from both
sandboxd and its isolated export network. Other providers and wider executor
scopes refuse mounted Project command access. Existing ordinary conversations
retain their unmounted workspace; a new mounted conversation does not silently
replace or discard their files.

An exporter epoch change stops the retained agent. Recovery is operator-managed;
there is no automatic or self-service remount endpoint. The feature does not
promise full POSIX inode identity across external API renames or delete/recreate.
Symlinks and ownership changes are unsupported. Native writable storage requires
xattrs and atomic hard links; stored-file Projects do not need those host features.

The complete local Python 3.15 proof emitted a urllib3 HTTPResponse finalizer
warning after successful commands and cleanup. Simpler Docker/SDK baseline probes
did not reproduce it; no runtime regression was confirmed. The observation is
retained in the local proof log rather than classified as a clean log or hidden.
CI against the final AgenticOS commit and maintainer UI acceptance remain separate
checks. No AgenticOS merge, release, deployment or discussion reply is authorized
by this report.
