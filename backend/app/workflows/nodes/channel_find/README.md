# channel.find

Finds channels whose name contains `query`. `channel_id` is a channel the bot
is in: on Mattermost it names the team to search. Telegram has no channel search
for a bot, and the step says so.

## The bot

A bot speaks for the whole organization, so a step that acts as one needs
`channels:manage`: the graph's author to publish, the run's principal on every
run. A bot deleted or switched off, or a member who lost the permission, stops
the step with `CHANNEL_NOT_USABLE`.

## Failures

| Code | Meaning |
|---|---|
| `CHANNEL_NOT_USABLE` | The bot is gone, off, or no longer yours to use |
| `CHANNEL_UNSUPPORTED` | The platform does not let a bot do this |
| `CHANNEL_CALL_FAILED` | The platform did not answer; retried when the step allows it |
