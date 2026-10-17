---
title: Projects
seo_title: Projects - shared files and instructions for AgenticOS chats
description: A project gives ongoing work one container of files and one set of instructions that every chat started in it shares, whichever agent answers.
---

# Projects

A **project** is a home for ongoing work: a launch, a monthly report, a client
engagement. It holds two things every chat started in it shares:

- **Files** in one container. Upload a brief, a spreadsheet or a whole folder
  once, and every chat in the project - today's and next week's - works on the
  same copy. A file an agent writes in one chat is there in the next.
- **Instructions** every agent answering in the project reads after its own:
  the tone, the deadlines, where the brand guide is.

A project also has a **default agent**, the one a new chat in it starts with.
Any agent can still answer in a project chat; the default only decides where a
chat begins.

## Starting a chat in a project

Two ways in:

- **New chat** on the project's page opens the chat with the project and its
  default agent already chosen.
- The composer's **+** menu offers **Work in a project** before the first
  message. The chip beside the agent picker shows the project; its **×** starts
  the chat outside it instead.

A chat stays in the project it was started in. The chip on an existing chat
links back to the project.

## What an agent gets in a project

Whichever agent answers, a run in a project chat works in the **project's
container** rather than in a workspace of its own:

- An agent with no sandbox is given one, the project's, so a plain chat agent can
  read and write the project's files.
- An agent with its own sandbox binding is moved into the project's container.
  The binding's approval settings carry over, so an author who set **Always ask**
  on the shell keeps that gate.
- The project's name, description and instructions are added after the agent's
  own instructions. The agent is still what it is, working on this.

The container is a [sandbox](sandbox.md) session when the deployment runs a
sandbox service, so the project's files can be run as well as read. Without
one, the project keeps its files as a stored workspace, which reads and writes
the same way but has no shell.

## Files

The project's **Files** tab is the container, browsable: a tree beside a reader
that opens Markdown, PDFs, images, spreadsheets and code in place.

- **Upload files** and **Upload folder** put files at the top of the project, a
  folder keeping its tree. Each file is held to the deployment's upload limit.
- **New folder** makes an empty folder for an agent to fill.
- The bin beside a file or folder removes it, with everything inside a folder, for
  every chat and agent in the project.

The `.agenticos` directory and the platform's own folders are not writable from
here; a path outside the project is refused before anything is written.

## Sharing and permissions

A project is private to whoever created it until they share it, with the same
**Share** dialog an agent or a skill uses: people, [departments](departments.md)
or the whole organization, each at a level.

| Grant level | Permission | What it allows |
|---|---|---|
| `read` | `projects:view` | See the project, its files and its instructions |
| `use` | `projects:use` | Chat in it, upload, make folders, remove files |
| `edit` | `projects:edit` | Change its instructions and default agent, share it, delete it |

Roles hold these at the usual scopes: an Owner or Admin reaches every project, a
Builder works in and edits the ones shared with them, a Member edits their own
and works in shared ones, and a Viewer reads what was shared. A chat whose author
loses `projects:use` stops reaching the project's files on its next turn.

**Chats stay their authors' own.** Sharing a project shares its files and
instructions, not the conversations in it: each person's chats in a project are
listed to them alone, as everywhere else in the console.

## Deleting a project

Deleting a project removes its container and every file in it. Its chats are
kept as ordinary chats, outside any project.

## Where projects show up

- **Projects** in the sidebar lists the five you used most recently, above the
  link to all of them.
- The dashboard's **Projects** card shows a row of them, with your chats in each.
- `GET /api/v1/projects` and its sub-routes are part of the public API, so a
  script can create a project and fill it with files. See [the API](api.md).
