# Departments and groups

Companies are organized in departments: sales, finance, HR, support. In
AgenticOS a department is a [group](directory.md#groups), and a group decides
who can use what. Finance can have its own agents, skills, context files and
knowledge bases that sales never sees, while the things everyone needs stay
open to the whole organization.

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

## Who can use a new thing

Creating an agent, a skill, a knowledge base or a context file asks one
question: **who can use it**.

| Choice | Who reaches it | Stored as |
|---|---|---|
| **Everyone** - the default | Every member of the organization | Visibility `org` |
| **Only me** | You, and whoever you share it with later | Visibility `private` (a knowledge base becomes a personal one) |
| **Chosen groups** | The members of the groups you pick | Visibility `private`, shared with each group at `use` |

A group's members find what was shared with it, use it and attach it to their
own agents. People outside the group do not see it in lists, in search, in the
Builder's pickers, through the API or through the AI Architect, which acts with
the permissions of whoever asks. Members whose role reaches every resource -
an owner, an admin, a builder by default - still see everything; see
[Permissions](permissions.md).

Apps are published by agents and start private to the person the run was for;
share one with a group from its **Share** panel. Every resource's **Sharing**
panel also adds or removes groups after creation.

## A group's page

Opening a group shows its people and everything shared with it, grouped by
kind - agents, knowledge bases, skills, context and apps - with the level each
was shared at. A reader sees only the items they could open anyway, so a
member of Sales reading Finance's page does not learn what Finance keeps.

## Where an agent's knowledge comes from

An agent can be bound to a knowledge base, skill or context file that is shared
more narrowly than the agent itself, and nothing refuses it. Everyone the agent
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

MCP connections are shared at the organization level or kept personal, not by
group. Group-scoped budgets and per-group analytics are not part of this yet.
