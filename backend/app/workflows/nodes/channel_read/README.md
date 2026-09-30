# <platform>.messages.read

`slack.messages.read` and `mattermost.messages.read`. Reads the latest `limit`
messages in `channel_id`, or in `thread_id`, as the step's bot, oldest first.
There is no Telegram step: Telegram does not let a bot read history.

## The bot

Each platform's step takes a bot of that platform only, checked at publish and
on every run. A bot speaks for the whole organization, so a step that acts as
one needs `channels:manage`: the graph's author to publish, the run's principal
on every run. A bot deleted or switched off, or a member who lost the
permission, stops the step with `CHANNEL_NOT_USABLE`.

## Failures

| Code | Meaning |
|---|---|
| `CHANNEL_NOT_USABLE` | The bot is gone, off, or no longer yours to use |
| `CHANNEL_UNSUPPORTED` | The platform does not let a bot do this |
| `CHANNEL_CALL_FAILED` | The platform did not answer; retried when the step allows it |
