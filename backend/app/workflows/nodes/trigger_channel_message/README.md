# trigger.channel_message

A workflow a message to one of the organization's Slack, Mattermost or Telegram
bots starts. Publishing a version with this trigger hands the bot's messages to
the workflow, and each one that fits starts one run as the member who published
it. Reply with the same platform's **Send a message** step, binding its
`channel_id` and `thread_id` to this trigger's, and the answer lands in the
thread the message came from.

## Which messages

Only those the bot would have answered with its own agent: the message passed
the bot's access policy, its sender is admitted the way the bot admits anyone,
and in a channel it named the bot. A message naming an agent by `@handle` still
goes to that agent. Of those, **Where** picks direct messages, channels and
groups, or both, and **Only when the message contains** a word or phrase,
ignoring case. A message that does not fit is answered by the bot's agent as
before, so a workflow can take one kind of request and leave the rest.

A bot's messages start one workflow at most: publishing a second one on the same
bot is refused while the first is live. Listening to a bot needs
`channels:manage`, like speaking as it. A voice note reaches the run as its
transcript; other attachments are not handed on.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `ChannelMessageTriggerOutput` | `text`, `sender`, `platform`, `bot_id`, `channel_id`, `thread_id`, `chat_type`, `message_id` |
