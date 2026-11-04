"""Why a call to a person's computer did not come back with an answer."""

from app.core.exceptions import ExternalServiceError


class DeviceUnavailable(ExternalServiceError):
    """No app is connected for that computer right now - closed, asleep or offline.

    The expected outcome when a person's laptop lid is shut, not a fault: the run
    that asked parks until the app is back rather than failing.
    """


class DeviceCallFailed(ExternalServiceError):
    """The app answered, and the answer is a refusal or an error.

    `message` is the app's own sentence - a path outside the chosen folder, a
    command the mode does not allow - which the tool hands the model as it is.
    """


class DeviceCallTimedOut(ExternalServiceError):
    """The app took the call and did not answer in time; it has been told to stop."""
