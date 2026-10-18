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
  message, and so does `@`: picking a project there starts the chat in it
  instead of writing its name into the message. The chip beside the agent picker shows the project; its **×** starts
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
the same way but has no shell; two chats writing to it at once each keep what
they wrote, and where both changed one file, the later write stands. A project stays on the sandbox connection it was
created on, so that connection cannot be deleted while a project keeps its files
there.

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

A project opens on **Files**. Files can also be dropped anywhere on the tab, and
each one shows its progress as it goes up; an empty project is one place to drop
the first ones. **Chats** is a table of the project's chats, and **Apps** the
apps a run in one of them published - those the reader may open.
**Instructions** edits them in Markdown with Source and Preview, as the Agent
Builder does an agent's, above the project's name, description and default agent.

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

**A project's chats are its members'.** Whoever may see a project reads every
chat in it, and whoever may work in it (`use`) continues them: their turns carry
their own name and face, so a thread several people worked on says who asked
what. Renaming, archiving or deleting a chat stays with whoever started it. On
the **Chats** tab each row says whose the chat is, which agents answer in it, when
it last moved or who is at work in it right now, and who has had it open - the
latest faces, with every name on hover; whoever has it open right now comes
first, with a green dot. A chat
outside any project stays its author's own, as everywhere else in the console.

A project's chat is not shared on its own, by link or with a person: it is read
through the project, so share the project instead.

**Working in one chat together.** Several people can be in a project's chat at
once. A bar over the transcript shows who else has it open, and its owner can
invite somebody from there. While one of them writes, the others see their face and
"Anna is typing" over the composer. A question one of them asks, and the agent's answer,
appear for everybody in the chat as they are written. **Reply** on any message
quotes it above the composer, and the reply carries the quote - on screen, and to
the agent, which reads each person's turn under their name and is told the chat
may have several people in it, so it knows who asked what and what "yes, do that"
is about.

## Deleting a project

Deleting a project removes its container and every file in it. Its chats are
kept as ordinary chats, outside any project - except one whose starter's account
was deleted, which only the project still reached and which goes with it.

## Where projects show up

- **Projects** in the sidebar lists the five you used most recently, above the
  link to all of them.
- The chat list files every chat in the projects you can see - yours and your
  teammates' - under the project's name, above the chats outside any project.
- The dashboard's **Projects** card shows a row of them, with the chats in each.
- `GET /api/v1/projects` and its sub-routes are part of the public API, so a
  script can create a project and fill it with files. See [the API](api.md).
