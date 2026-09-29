# channel.read

Reads the latest `limit` messages in `channel_id`, or in `thread_id`, as the
step's bot, oldest first. Slack and Mattermost let a bot read a channel it is
in; Telegram does not let a bot read history, and the step says so.

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
