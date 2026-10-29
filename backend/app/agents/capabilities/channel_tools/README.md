# channel_tools — what the agent can ask about the channel it is in

Channel runs receive bounded metadata about their current conversation. Tools let
the agent ask additional questions about the channel and deliver requested files.

This capability provides channel lookups and an explicitly granted file action:

| Tool | Answers |
|---|---|
| `get_channel_info` | Name, purpose, topic, size |
| `list_channel_members` | Who is here |
| `search_channels` | Which other channels exist, by name and purpose |
| `read_channel_history` | Recent channel messages, or `scope="thread"` for this thread |
| `send_channel_file` | Send a workspace file when the user requests delivery |

## One contract across chat platforms

`_directory.py` declares the shape; `app/services/channels/{mattermost,slack,telegram,teams}.py`
implement it. That direction is deliberate. Every platform answers *who is in
this channel*, through a different API with different field names — and separate
capabilities, one per platform, would mean the model had to know which platform
it was standing on before it could ask a question each can answer. It would
also mean separate sets of tool ids, so an approval decision made on Slack would
mean nothing on Mattermost.

A platform that genuinely cannot answer raises `ChannelDirectoryUnsupported`,
and the toolset returns its message rather than failing the run. Telegram gives
a bot no way to search channels or read history, and `getChatAdministrators` is
the whole of what it may list — so a Telegram member list is a list of
administrators and says so, in the `role` field, rather than reading as
everybody.

## What it deliberately does not do

**It does not take a channel id.** The directory is bound server-side to the
channel the message arrived in. An argument for it would turn "who is in this
channel" into "read any channel this bot is in", asked from a conversation
somewhere else — and the model is the one thing in the run that a person in the
channel can influence.

**It does not escalate.** Every call goes through the bot's own token, so the
agent sees exactly what the bot sees. Membership of the channel is the
permission boundary, and it is the platform's rather than one this repository
invented — which is why there is no allow-list here to get out of step with
Mattermost's own.

**Automatic channel context is separate from tool grants.** The runner injects
the channel name, purpose, topic and a bounded visible roster as lower-trust
conversation data, outside system instructions. Slack uses native member IDs
without profile fan-out. The
capability grants additional queries and explicit file actions; removing a tool
does not remove the runtime context. Personal MCP availability is derived from
the sender identity and their connections, not from the binding's prose.

**It is not gated on a scope.** Nothing here reaches outside what the operator
already gave the bot when they created it, so a deployment-wide switch would
only be able to say "no channel bot may know its own channel's name".

## The one worth gating

`read_channel_history` puts other people's messages into a run transcript that
somebody reads weeks later. It is a read, so it is not `side_effecting` and it
does not ask by default — but it is the obvious candidate for a `tool_approval`
override on a binding, and it is why the tools are declared separately
rather than as one capability-wide flag.

## Where it appears

Nowhere except a channel run. `_build` returns `None` when the run has no bound
directory, which is every run from the dashboard, the API, the widget and a
schedule. The binding stays valid on such an agent — the same published agent
answers in a browser and on Mattermost, and only one of those is a channel.


## Explicit file delivery

Creating or editing a workspace file does not post it to a channel. The operator
must grant `send_channel_file` on the bot binding. The side-effecting action reads
one named workspace file through a server-bound callback and submits it through
the adapter immediately, so a later parked call cannot lose a queued attachment.
Provider failures are returned as failures; Teams can require acceptance in a
personal chat. Delegates do not inherit the callback. Requested chart and visual
pictures retain their separate delivery path.

History defaults to the current channel's recent messages and supports the bound
thread as an explicit scope. Neither accepts a channel or thread ID. Automatic
thread context backfill continues to use only the bound thread.
