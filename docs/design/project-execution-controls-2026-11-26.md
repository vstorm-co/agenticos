# Project execution controls — 26 November 2026

## Follow-up after discussion #3272

This contract supersedes the earlier candidate's Project-default command policy.
The main Tools & files card describes the active project's shared files rather
than asking every member to choose a command target. Advanced settings retain
explicit Agent/Project pins and offer automatic selection without a request pin.
Generic file tools and commands default to the agent's own executor, including in
attached project chats. Explicit project tools always address the project store.
The model may select the additional project executor for direct builds without a
manual user toggle, subject to enabled shell tools and existing approval rules.

`transfer_project_file` sends one bounded file as bytes between the authoritative
project store and the agent workspace, without model-mediated content copying.
It accepts `to_agent` or `from_agent`, relative paths and an optional current
`expected_sha256` for replacement. It refuses unknown/over-limit sizes, escaping
paths, unconfirmed overwrite, stale destination digests and changed project
selection. A receipt reports actual paths, bytes and SHA-256. Later edits do not
synchronize and arbitrary shell writes are not transactionally locked. Direct
project commands need no transfer. No cross-provider shared mount is promised.

Explicit preferences remain scoped to account, organization and conversation.
Local folder consent remains authoritative. Ordinary chat/channel selections
remain run-local; attached project chats always begin with their own project.
Unknown audiences cannot receive private project context. Personal coding-account
credentials remain unavailable on project/shared sources.

## Evidence boundary

The earlier 42 control/layout/store tests and five outgoing-frame regressions
covered the prior candidate, not this follow-up. Focused port, transfer, control,
layout and outgoing-frame checks for the new behavior are recorded by its change
and CI. A passing synthetic component test is not a live provider run or a shared
mount acceptance test.
