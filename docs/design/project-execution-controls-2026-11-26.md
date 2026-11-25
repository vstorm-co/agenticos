# Project execution controls — 26 November 2026

The console's Work on settings separate a project's file context from the
workspace that executes commands. Attached project chats default to the project;
ordinary chats default to the agent. A files-only agent gets an explanation,
without controls that pretend to enable a shell.

A choice applies to the next message. Explicit preferences are scoped to account,
organization and conversation. A draft is tied to its project and moves to the
created conversation without becoming another new chat's default. Embedded
Architect and Builder conversations do not inherit the main chat's executor.
The authenticated server still resolves project access and owns admission.

Local folder consent takes precedence over a remembered cloud choice. Switching
back to cloud makes that explicit cloud choice available again. A missing or
unreadable project disables Project; pending metadata never flashes a selected
Agent executor as if the project had already been resolved. Dynamic project
selection in other chats remains run-scoped and is not inferred from file history.

Verification: 42 focused control/layout/store tests, plus five exact outgoing-frame
regressions (four workspace/default/local cases and one embedded-chat isolation
case). Type checking and scoped ESLint pass. Commit hooks and aggregate CI are
recorded separately; these component tests do not claim a live provider run.
