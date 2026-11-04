"""A host updater's read-only admission flag, shared by API and worker replicas."""

import json

from app.core.config import settings
from app.core.exceptions import AppException


class UpdateInProgress(AppException):
    message = "This deployment is being updated. Please try again later."
    code = "UPDATE_IN_PROGRESS"
    status_code = 503


def draining() -> bool:
    socket = settings.UPDATE_AGENT_SOCKET
    if socket is None:
        return False
    path = socket.parent / "control.json"
    try:
        data: object = json.loads(path.read_bytes())
    # A configured but unreadable flag cannot safely admit more work. The admin
    # and health paths remain reachable through the maintenance middleware.
    except OSError, ValueError:
        return True
    return not isinstance(data, dict) or data.get("draining") is not False


def require_admission() -> None:
    if draining():
        raise UpdateInProgress()
