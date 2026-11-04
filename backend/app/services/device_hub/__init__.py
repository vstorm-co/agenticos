"""The device hub: a person's own computers, reached through the desktop app (#2305).

External callers use what is re-exported here; the frames and the routing are
package-internal.
"""

from app.schemas.local_target import LocalMode, LocalTarget
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
from app.services.device_hub.local_context import LocalContext, local_skills_context
from app.services.device_hub.services import describe as describe_service
from app.services.device_hub.services import mcp_toolset as local_mcp_toolset
from app.services.device_hub.services import model_spec as local_model_spec
from app.services.device_hub.workspace import DeviceWorkspace

__all__ = [
    "DESKTOP_PLATFORMS",
    "Capabilities",
    "Device",
    "DeviceCallFailed",
    "DeviceCallTimedOut",
    "DeviceUnavailable",
    "DeviceWorkspace",
    "LocalContext",
    "LocalMode",
    "LocalTarget",
    "admit",
    "call",
    "configure",
    "connected",
    "describe_service",
    "local_mcp_toolset",
    "local_model_spec",
    "local_skills_context",
    "serve",
    "wait_for",
]
