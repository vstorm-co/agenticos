"""The device hub: a person's own computers, reached through the desktop app (#2305).

External callers use what is re-exported here; the frames and the routing are
package-internal.
"""

from app.services.device_hub._hub import (
    DESKTOP_PLATFORMS,
    Device,
    admit,
    call,
    configure,
    connected,
    serve,
    wait_for,
)
from app.services.device_hub._protocol import Capabilities
from app.services.device_hub.exceptions import (
    DeviceCallFailed,
    DeviceCallTimedOut,
    DeviceUnavailable,
)
from app.services.device_hub.workspace import DeviceWorkspace, LocalMode, LocalTarget

__all__ = [
    "DESKTOP_PLATFORMS",
    "Capabilities",
    "Device",
    "DeviceCallFailed",
    "DeviceCallTimedOut",
    "DeviceUnavailable",
    "DeviceWorkspace",
    "LocalMode",
    "LocalTarget",
    "admit",
    "call",
    "configure",
    "connected",
    "serve",
    "wait_for",
]
