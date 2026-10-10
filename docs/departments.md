# Departments and groups

Companies are organized in departments: sales, finance, HR, support. In
AgenticOS a department is a [group](directory.md#groups), and a group decides
who can use what. Finance can have its own agents, skills, context files,
knowledge bases and MCP servers that sales never sees, while the things everyone
needs stay open to the whole organization.

## Adding your departments

**Groups** in the main navigation lists the organization's groups. A member
with `members:manage` adds them one at a time with **New group**, or several at
once with **Add departments**, which offers Sales, Finance, HR, Support,
Engineering, Marketing, Legal and Operations, each with an icon and a short
description. Rename them, change their icons or delete them afterwards like any
other group.

People are added to a group from its page, by hand, or by a
[directory group mapping](directory.md#directory-group-mappings) when your
company already keeps its teams in a directory.

### A group's lead

An administrator can make a member the group's **lead** - the crown beside them
in the members list. A lead adds people to their group and takes them out
without administering the organization, so a department head can bring in a new
hire without asking IT. Only someone with `members:manage` names or removes a
lead, since a lead hands out access to everything shared with the group.

## Who can use a new thing

Creating an agent, a skill, a knowledge base, a context file or a shared MCP
server asks one question: **who can use it**.

| Choice | Who reaches it | Stored as |
|---|---|---|
| **Everyone** - the default | Every member of the organization | Visibility `org` |
| **Only me** | You, and whoever you share it with later | Visibility `private` (a knowledge base becomes a personal one) |
| **Chosen groups or people** | The members of the groups you pick, and the people you name | Visibility `private`, shared with each at `use` |

Groups are offered as soon as you choose the third option; people are found by
typing a name or an email address. Each one picked stays as a chip until you
remove it.

A group's members find what was shared with it, use it and attach it to their
own agents. People outside the group do not see it in lists, in search, in the
Builder's pickers, through the API or through the AI Architect, which acts with
the permissions of whoever asks. Members whose role reaches every resource -
an owner, an admin, a builder by default - still see everything; see
[Permissions](permissions.md).

Apps are published by agents and start private to the person the run was for;
share one with a group from its **Share** panel. Every resource's **Sharing**
panel also adds or removes groups after creation.

## A department's MCP servers

An organization's MCP server - one shared account, connected once - can be
narrowed the same way, so Finance's ledger server is Finance's. Members who
manage MCP servers see the organization's servers, the ones they connected, and
those shared with their groups or with them; owners and admins see all of them.
A builder outside Finance does not find its server in the list, cannot open it
by its id, and cannot publish an agent bound to it. See
[MCP](mcp.md#personal-or-organization-wide).

An agent already bound to one keeps working for everyone who may run the agent.
The choice decides who may pick the server, not who is answered through it, so
the Builder shows it where the agent's knowledge comes from.

## A group's page

Opening a group shows its people and everything shared with it, grouped by
kind - agents, knowledge bases, skills, context, apps and MCP servers - with the
level each was shared at.

**Add to this group** shares several things at once: it lists everything the
reader may edit that the group does not have yet, with a search, a tick each and
the level to share at. Each is the same grant the Share panel writes, so it
needs the same right to edit.

Members are told when something is shared with their group - in the inbox and,
if they want it, by email; *Shared with your group* in notification settings
turns it off. Cards across the console say who each thing is for: *Everyone*,
its departments by name, or *Private*. A reader sees only the items they could open anyway, so a
member of Sales reading Finance's page does not learn what Finance keeps.

## Where an agent's knowledge comes from

An agent can be bound to a knowledge base, skill, context file or MCP server that
is shared more narrowly than the agent itself, and nothing refuses it. Everyone the agent
reaches is then answered from that source, including people who could not open
it themselves.

The Builder's **Toolbox** tab shows where the agent's knowledge comes from: who
the agent reaches, and for each source, whether it is the whole organization's
or which groups it belongs to. A source shared with fewer people than the agent
is marked, with a warning above the list. Narrow the agent to the same groups,
or widen the source, if that is not what you meant.

## The person's groups in instructions

Instructions can name the groups of the person the agent is talking to with
`{{groups}}` - for example, *"You are helping someone from {{groups}}."* It
becomes their group names, separated by commas, or nothing for a visitor. See
[Variables](reference/spec.md#variables).

## What is not covered yet

Group-scoped budgets and per-group analytics are not part of this yet.
