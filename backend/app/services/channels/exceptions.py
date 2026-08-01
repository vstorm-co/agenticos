"""Failures a channel adapter raises at itself, not at a request.

These never reach an HTTP handler: a channel supervisor is a background task
started from the lifespan, and there is nobody to return a status code to. They
exist so a supervisor can tell "this session ended" from "this bot cannot be
started at all", which are two loops apart.
"""

from app.core.exceptions import AppException


class ChannelNotConfigured(AppException):
    """A bot is missing something a restart cannot supply.

    A missing Slack app-level token or Mattermost server URL is an ordinary row
    state, not corruption - the operator has not pasted it yet. Retrying a
    coroutine that returns immediately on that state is what put the API into a
    100% CPU spin with the event loop starved and every other task, including
    the health check, never scheduled again.

    A supervisor that catches this stops. Nothing it does will change the row;
    the operator has to.
    """

    message = "Channel bot is not configured"
    code = "CHANNEL_NOT_CONFIGURED"
