---
title: "Answer a handbook question in Slack"
description: "Put the document agent in a Slack test channel, ask the same questions and check who each run belonged to."
---

# Answer a handbook question in Slack

Put the [document agent](first-document-agent.md) in a Slack test channel and ask it the questions you already checked in the console. The result to look for is the same checked answer in a Slack thread, and a run in Activity recorded on the `slack` surface. This is a procedure to run, not a report of a measured deployment.

## Before you start

- **The document agent passes its three checks in the console.** Keep its handbook, model and published version fixed while you add Slack. If the model, the documents and the channel all change at once, a different answer tells you nothing about which change caused it.
- **A Slack workspace where you may install apps.** Use a test workspace or a test channel. The handbook is synthetic, so nothing private is at stake while you learn the path.
- **The `channels:manage` permission** to register the bot, and `agents:publish` on the agent, from your role or a grant, to bind it.

Socket Mode is the transport used below. The bot opens the connection to Slack, so nothing has to be reachable from the internet. That makes it the right choice on a laptop. [Channels](../channels.md#slack) describes the Events API alternative.

## Create the Slack app

1. In **api.slack.com/apps → Create New App → From an app manifest**, pick the test workspace and paste the manifest from the [Slack section of Channels](../channels.md#slack). Change `name` and `display_name` to what the bot should be called. Review the scopes before you install: the [scope table](../channels.md#scopes-and-events) says which call needs each one.
2. In **Basic Information → App-Level Tokens → Generate**, add the scope `connections:write` and copy the `xapp-` token.
3. In **Install App → Install to Workspace → Allow**, install it and copy the **Bot User OAuth Token** (`xoxb-`).

!!! warning "Leave token rotation off"

    With token rotation on, the `xoxb-` token expires and the bot stops answering. The platform stores a static bot token and does not refresh it.

Keep both tokens out of screenshots, recordings and help requests.

## Register the bot and bind the agent

1. In **Channels → Add channel**, choose Slack. Paste the bot token into **Bot token** and the `xapp-` token into **App-level token**. Both are sealed in the [vault](../secrets.md) and never shown again.
2. The new row says *No agent bound - this bot answers nothing*. That is expected until the next step.
3. Open the document agent in the Builder, go to **Availability** and choose the bot under **Where this agent is available**. The agent must have a published version.
4. Leave the channel lookups off. A handbook question does not need the agent to read the channel's history or its member list, and each lookup is a [separate decision](../reference/capabilities.md#chat-channel-lookup).
5. In Slack, create a test channel and invite the bot with `/invite @your-bot`.

## Ask the questions

Ask each question in Slack and compare the reply with the source.

| Where and what | Reference check |
| --- | --- |
| In the channel: `@your-bot Who handles an equipment request?` | Names the office manager and says it used the handbook |
| Reply in that thread: `Which details should I include?` | Item, reason and delivery location, answered in the same thread |
| A new message in the channel: `@your-bot How much can I spend?` | Says the handbook does not state an allowance |
| A channel message that does not mention the bot | No reply |
| A direct message to the bot, before you link your account | Asks you to connect your account and sends a link |

A thread is one conversation. The reply in the thread keeps the first answer in context. A new message in the channel starts a new conversation with no memory of the last one. See [one conversation per thread](../channels.md#one-conversation-per-thread).

The mention must be one Slack resolved, picked from the autocomplete. A handle typed as plain text is not a mention, and the bot stays silent.

## Check who each run belonged to

Open **Activity** and find the runs. Each one records the `slack` surface, the agent version that answered and the Slack account that wrote the message. Open a run and check that it called `search_documents` and that the retrieved passage is the one the answer relies on.

A sender who has not linked a Slack account to a member still gets an answer in a channel. That run takes the role of the person who bound the agent to the bot. So anyone who can post in the channel can spend the organization's budget and read what the bound collections contain, through the agent.

!!! info "The channel's members are the document's audience"

    The agent searches the collections its spec binds, whoever asks. A Slack user's own permissions in AgenticOS do not narrow that. Choose the channel and the collection together, and never test access rules with a private document.

To link your own account, send the bot a direct message. It answers with a link. Open it in the browser where you are signed in to the console and confirm **Connect this account**. From then on your messages run as you, with your permissions and your budget. The link lasts fifteen minutes and works once. Linked accounts are listed under **Settings → Profile → Chat accounts**.

To refuse unlinked senders in channels as well, set `require_link` on the bot's access policy. The rules and the per-account rate limit are in [linking, and where it is required](../channels.md#what-every-channel-shares).

## When it does not answer

Work through the path in this order:

1. The bot's row under **Channels** shows **Not connected**. The badge carries the reason, often a wrong or missing `xapp-` token.
2. The row still says no agent is bound, or the agent has no published version.
3. A scope or an event is missing. Adding one means reinstalling the app, which issues a new `xoxb-` token. Paste the new token into the bot's settings, or the bot keeps the access it had.
4. The bot is not in the channel, or the message was not a resolved mention.
5. A direct message from an unlinked account is refused until you link it.

If the bot answers but the answer is wrong, the Slack path works. Check retrieval in Activity and the collection's documents before you change anything in Slack. [Channels](../channels.md#slack) lists what is and is not reported for a silent bot.

## Record the trial

Keep these together, so another person can repeat the trial and compare:

- the AgenticOS version, the agent version, the model profile and the collection with its document status;
- the Slack manifest you pasted, without tokens, and the transport;
- each question, the reply as posted in Slack and the matching run in Activity;
- every failure, including a silent bot, and what fixed it;
- who installed the app, who bound the agent and who judged the answers.

A person does three things here that no setting replaces: installs the app, decides which channel may reach which documents, and judges each answer against the source. A screenshot of the Channels page explains the setup. Only the thread with the question and the answer side by side shows the result.

## Next steps

Before you replace the synthetic handbook with a real one, decide who should reach that document and choose the channel to match. Name who updates the document, who changes the agent and who follows up on questions the handbook cannot answer. [Rollout](../rollout.md) covers those roles.
