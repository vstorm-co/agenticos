# Learn

The sections below are the recommended way to learn AgenticOS, in order. Read
them as a course: each one assumes the ones before it, and none of them assumes
you have read the source.

## Get started

You need a running stack and one agent that answers you. About twenty minutes.

<div class="grid cards" markdown>

- :material-download:{ .lg .middle } **[Install](../install.md)**

    Docker Compose, or the services by hand. Five minutes to a stack you can
    open in a browser.

- :material-rocket-launch:{ .lg .middle } **[Your first agent](../first-agent.md)**

    A provider key, an agent, a published version, a run that cost something.

- :material-lightbulb:{ .lg .middle } **[Concepts](../concepts.md)**

    Spec, version, exposure, trigger, run. Five nouns. Everything else is built
    from them, so this is the page to reread when something surprises you.

</div>

!!! tip

    Read **Concepts** even if you are in a hurry. Most confusion about this
    platform is one of those five nouns being taken for another — a *spec* for a
    *version*, an *exposure* for a *trigger*.

!!! tip "Lost in the console?"

    [The console](../console.md) is the map of every area — what each one is
    for, and which page explains it.

## Build the agent

Now make it good. Each page here is one thing you give the agent, and they are
independent — take the ones your agent needs.

<div class="grid cards" markdown>

- :material-compass-outline:{ .lg .middle } **[Choosing a model](../choosing-models.md)**

    Which model this agent should use — open weights or closed, what drives the
    bill, and how to change your mind later.

- :material-brain:{ .lg .middle } **[Models and providers](../models.md)**

    27 providers, model profiles, fallbacks, and what a token actually costs.

- :material-school:{ .lg .middle } **[Skills](../skills.md)**

    Written know-how the agent loads only when it decides it is relevant.

- :material-text-box-outline:{ .lg .middle } **[Context files](../context.md)**

    Standing knowledge written once and bound to many agents — a glossary, a
    tone guide, an escalation matrix.

- :material-file-document-multiple:{ .lg .middle } **[Knowledge](../file-processing.md)**

    Upload, parse, chunk, embed. Collections, and syncing a Drive folder or a
    bucket into one.

- :material-connection:{ .lg .middle } **[MCP connections](../mcp.md)**

    Any MCP server by URL, and 59 in the picker with OAuth already wired.

- :material-console:{ .lg .middle } **[The sandbox](../sandbox.md)**

    Files and a shell, isolated, with a lifetime.

- :material-clock-outline:{ .lg .middle } **[Triggers](../triggers.md)**

    A run that happens on a schedule or on an event, with nobody typing.

</div>

## Put it in front of people

An agent nobody can reach is a draft. This is how it leaves the console.

<div class="grid cards" markdown>

- :material-source-branch:{ .lg .middle } **[Environments](../environments.md)**

    `staging` and `production` as names pinned to versions, so publishing and
    releasing are two decisions.

- :material-forum:{ .lg .middle } **[Surfaces](../channels.md)**

    Web chat, a hosted page, an embeddable widget, the HTTP API, Slack, Telegram
    and Mattermost — one runner behind all of them.

- :material-server:{ .lg .middle } **[The deployment itself](../deployment.md)**

    Its identity, its sign-up policy, its notices. The things that are about the
    installation rather than about an agent.

- :material-cloud-upload:{ .lg .middle } **[Deploy](../deploy.md)**

    Getting the platform onto a host.

- :material-account-group:{ .lg .middle } **[Rolling it out](../rollout.md)**

    Who does what, a realistic first ninety days, what it costs, and the
    questions your security review will ask.

</div>

## Keep it under control

The part most agent frameworks leave to you. Read it before you give an agent a
tool that spends money or writes to something.

<div class="grid cards" markdown>

- :material-account-key:{ .lg .middle } **[Permissions](../permissions.md)**

    Three layers: what a role allows, what a grant widens, what a scope lets a
    tool reach.

- :material-shield-check:{ .lg .middle } **[Governance](../governance.md)**

    Budgets checked before the request, approvals decided once, alerts, and an
    audit trail that keeps the value rather than the row.

- :material-lock:{ .lg .middle } **[Secrets and the vault](../secrets.md)**

    One mechanism for every credential at rest, and deliberately no second one.

</div>

## How-to — recipes

Short answers to specific questions, once you know your way around.

- [Write an agent's instructions](../howto/customize-agent-prompt.md)
- [Configure sync sources](../howto/configure-sync-sources.md)
- [Use message ratings](../howto/use-ratings.md)

Looking for how to *extend* the platform in Python — a new capability, a new
connector, a new endpoint? That is under
[Resources](../resources/index.md#extending-the-platform).

## Where to go next

When you know how the platform behaves and want to know exactly what a setting,
a command or a spec field does, that is [Reference](../configuration.md).
