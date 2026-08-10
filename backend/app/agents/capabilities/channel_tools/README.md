# channel_tools — what the agent can ask about the channel it is in

A bot answering in `~support` knows the words somebody typed and nothing else.
It does not know the channel is called `~support`, who is in it, what it was set
up for, or what was said in it ten minutes ago — so "who should I ask about
billing?" and "summarise what we decided above" are questions it can only
answer by guessing.

This capability is those four questions, and only those four:

| Tool | Answers |
|---|---|
| `get_channel_info` | Name, purpose, topic, size |
| `list_channel_members` | Who is here |
| `search_channels` | Which other channels exist, by name and purpose |
| `read_channel_history` | What was said recently |

## One contract, three implementations

`_directory.py` declares the shape; `app/services/channels/{mattermost,slack,telegram}.py`
implement it. That direction is deliberate. Every platform answers *who is in
this channel*, through a different API with different field names — and three
capabilities, one per platform, would mean the model had to know which platform
it was standing on before it could ask a question all three can answer. It would
also mean three sets of tool ids, so an approval decision made on Slack would
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

**It does not inject channel context automatically.** Putting the member list
and the channel purpose into every system prompt is a different feature with a
different failure mode: a `purpose` written by whoever can edit the channel,
pasted into the instructions, is a prompt injection with a public edit button.
That is issue #5 on the channels note — dynamic context sections, resolved per
run and marked as data — and it is deliberately not this.

**It is not gated on a scope.** Nothing here reaches outside what the operator
already gave the bot when they created it, so a deployment-wide switch would
only be able to say "no channel bot may know its own channel's name".

## The one worth gating

`read_channel_history` puts other people's messages into a run transcript that
somebody reads weeks later. It is a read, so it is not `side_effecting` and it
does not ask by default — but it is the obvious candidate for a `tool_approval`
override on a binding, and it is why the four tools are declared separately
rather than as one capability-wide flag.

## Where it appears

Nowhere except a channel run. `_build` returns `None` when the run has no bound
directory, which is every run from the dashboard, the API, the widget and a
schedule. The binding stays valid on such an agent — the same published agent
answers in a browser and on Mattermost, and only one of those is a channel.
