"""Where the desktop is: the agent's own sandbox, or a `computerd` daemon the operator runs.

Both answer the same two questions - what is on the screen, and do this - and
neither is told how the model's screenshot was scaled; `_actions.to_native` has
already moved every point into the backend's own input space by the time an
action arrives here.

**The sandbox** is the run's workspace - the container or cloud sandbox the
`sandbox` capability opened on one of the organization's connections. A click is
an `xdotool` command run there and a screenshot is a `scrot` file read back, so
the desktop needs nothing of its own: no address, no token, no provider. It is
the same machine the agent's shell and file tools work on, shared by whoever
shares the workspace, and it is put away with it.

**A daemon** is the operator's machine: their own Linux desktop or Mac, or a
desktop container they keep running. It is reached over HTTP with the token
the binding names in the organization's vault, and its host has to be on
`COMPUTER_DAEMON_ALLOWED_HOSTS` - the same reasoning as `BROWSER_CDP_ALLOWED_HOSTS`,
since the URL is in a spec an agent's editor writes. The allowlist says where
this deployment may send a request; the token says who may drive the desktop,
so it belongs to the organization that runs it rather than to the deployment.
One daemon is one desktop: every run holding its token shares it.
"""

import logging
import struct
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

import anyio
import httpx
from pydantic_ai.workspaces import SupportsCommands, Workspace, WorkspaceError

from app.agents.capabilities.computer_use._actions import (
    Click,
    Drag,
    Key,
    Move,
    Scroll,
    TypeText,
    Wait,
)
from app.core.config import settings
from app.core.sanitize import UrlRefusedError

logger = logging.getLogger(__name__)

NativeAction = Click | Move | Drag | Scroll | TypeText | Key | Wait

DISPLAY = ":0"
"""The X display a sandbox's desktop runs on."""

NO_DESKTOP = 3
"""The start script's exit code for a sandbox without the desktop's programs."""


class ComputerError(Exception):
    """The desktop could not be reached or refused an action.

    Its text is written for the model - it is returned as the tool's answer - so
    it never carries a URL, a token or a provider's raw response.
    """


@dataclass(frozen=True)
class Capture:
    """A screenshot as the backend took it, and the space its pointer moves in.

    The two sizes differ on a Retina Mac, where the picture is in pixels and the
    pointer in points; on X11 they are the same.
    """

    image: bytes
    width: int
    height: int


class Computer(Protocol):
    """One desktop."""

    label: str

    async def capture(self) -> Capture:
        """Take a screenshot of the whole screen."""
        ...

    async def perform(self, action: NativeAction) -> None:
        """Carry out one action, in native coordinates.

        Raises:
            ComputerError: The desktop refused it or could not be reached.
        """
        ...

    async def close(self) -> None:
        """Release what the desktop holds open, once the run is done with it."""
        ...


ComputerFactory = Callable[[Workspace], Awaitable[Computer]]
"""Opens the run's desktop; handed the run's workspace, which only the sandbox uses."""


def png_size(data: bytes) -> tuple[int, int]:
    """The width and height in a PNG's header, without decoding the picture."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ComputerError("The desktop answered with something that is not a screenshot.")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


_X11_KEYS = {
    "enter": "Return",
    "return": "Return",
    "esc": "Escape",
    "escape": "Escape",
    "tab": "Tab",
    "space": "space",
    "backspace": "BackSpace",
    "delete": "Delete",
    "del": "Delete",
    "home": "Home",
    "end": "End",
    "pageup": "Prior",
    "page_up": "Prior",
    "pagedown": "Next",
    "page_down": "Next",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "insert": "Insert",
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
    "cmd": "super",
    "command": "super",
    "super": "super",
    "meta": "super",
    "win": "super",
}

_SCROLL_BUTTONS = {"up": 4, "down": 5, "left": 6, "right": 7}
_MOUSE_BUTTONS = {"left": 1, "middle": 2, "right": 3}


def x11_keys(chord: str) -> str:
    """A chord as `xdotool key` spells it: `ctrl+shift+t`, `Return`, `super`."""
    parts = [part.strip() for part in chord.split("+") if part.strip()]
    if not parts:
        raise ComputerError(f"{chord!r} names no key.")
    return "+".join(_X11_KEYS.get(part.lower(), part) for part in parts)


def xdotool(action: NativeAction) -> list[str] | None:
    """The `xdotool` command that carries out an action on an X11 display.

    `None` for a wait, which is a sleep here rather than a process on the desktop.
    An argv rather than a shell line, so typed text reaches `xdotool` as one
    argument whatever it holds.
    """
    match action:
        case Click():
            return [
                *("xdotool", "mousemove", "--sync", str(action.x), str(action.y)),
                *("click", "--repeat", str(action.count), str(_MOUSE_BUTTONS[action.button])),
            ]
        case Move():
            return ["xdotool", "mousemove", "--sync", str(action.x), str(action.y)]
        case Drag():
            return [
                *("xdotool", "mousemove", "--sync", str(action.x), str(action.y), "mousedown", "1"),
                *("mousemove", "--sync", str(action.to_x), str(action.to_y), "mouseup", "1"),
            ]
        case Scroll():
            return [
                *("xdotool", "mousemove", "--sync", str(action.x), str(action.y)),
                *("click", "--repeat", str(action.amount), str(_SCROLL_BUTTONS[action.direction])),
            ]
        case TypeText():
            return ["xdotool", "type", "--delay", "12", "--", action.text]
        case Key():
            return ["xdotool", "key", "--", x11_keys(action.keys)]
        case _:
            return None


def check_daemon_url(url: str) -> None:
    """Refuse a daemon URL this deployment's operator has not vetted.

    Checked at publish and again each time a run opens the daemon, so a host the
    operator has since taken off `COMPUTER_DAEMON_ALLOWED_HOSTS` is not sent the
    token by an agent published while it was on. Exact, case-folded host matching;
    an empty list refuses every daemon. The URL is a base the daemon's paths are
    appended to, so a query or a fragment, which would swallow them, is refused;
    so are credentials, which would be stored and exported in the spec.

    Raises:
        UrlRefusedError: The URL is missing, malformed, or names a host that is
            not allowed.
    """
    if not url:
        raise UrlRefusedError(
            "Computer use needs a daemon_url: the computerd endpoint of the desktop to drive"
        )
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UrlRefusedError("A daemon_url must be an http or https URL with a host")
    if parsed.username or parsed.password:
        raise UrlRefusedError(
            "Keep the credentials out of the daemon_url; the daemon's token comes from the vault"
        )
    if "?" in url or "#" in url:
        raise UrlRefusedError(
            "A daemon_url is the daemon's address alone, with no query or fragment"
        )
    try:
        _ = parsed.port
    except ValueError as exc:
        # Not `exc`'s text: it quotes the port as given, which may be a secret
        # pasted after a colon.
        raise UrlRefusedError("The daemon_url's port must be a number from 0 to 65535") from exc
    allowed = {host.strip().lower() for host in settings.COMPUTER_DAEMON_ALLOWED_HOSTS}
    if parsed.hostname.lower() not in allowed:
        raise UrlRefusedError(
            f"This deployment does not allow computer use against '{parsed.hostname}'. "
            f"Add it to COMPUTER_DAEMON_ALLOWED_HOSTS"
        )


class DaemonComputer:
    """A desktop served by `computerd` - see `deploy/computer/README.md`."""

    def __init__(
        self, base_url: str, token: str, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._owned = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self.label = "Desktop"

    async def _request(
        self, method: str, path: str, json: dict[str, object] | None = None
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method, f"{self._base}{path}", headers=self._headers, json=json
            )
        except httpx.HTTPError as exc:
            logger.warning("computerd unreachable: %s", type(exc).__name__)
            raise ComputerError(
                "The desktop could not be reached. It may be stopped or restarting."
            ) from exc
        if response.status_code == 401:
            raise ComputerError("The desktop refused this deployment's token.")
        if response.status_code >= 400:
            raise ComputerError(f"The desktop refused the action: {_error_text(response)}")
        return response

    async def capture(self) -> Capture:
        """Take a screenshot; the daemon names its input space in two headers."""
        response = await self._request("GET", "/screenshot")
        platform = response.headers.get("x-platform")
        if platform:
            self.label = platform
        image = response.content
        width, height = png_size(image)
        return Capture(
            image=image,
            width=int(response.headers.get("x-screen-width", width)),
            height=int(response.headers.get("x-screen-height", height)),
        )

    async def perform(self, action: NativeAction) -> None:
        """Send one action; the daemon answers once it has been carried out."""
        await self._request("POST", "/actions", json={"actions": [action.model_dump()]})

    async def close(self) -> None:
        """Close the client this desktop made; one it was handed is its caller's."""
        if self._owned:
            await self._client.aclose()


def _error_text(response: httpx.Response) -> str:
    """The daemon's own one-line reason, or the status when it gave none."""
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    error = body.get("error") if isinstance(body, dict) else None
    return str(error)[:200] if error else f"HTTP {response.status_code}"


def _desktop_start(width: int, height: int) -> str:
    """The script that starts the sandbox's display and desktop, unless they already run.

    Run on every run's first use rather than once per sandbox: a sandbox that
    hibernated or restarted between turns kept its files and lost its processes.
    A restarted container keeps its `/tmp` too, and Xvfb refuses a display whose
    lock survived the last one. Both are started with `setsid nohup`, so they
    outlive the command that started them.

    Each half is checked on its own, so a display that survived its desktop gets
    the desktop back rather than screenshots of an empty screen. The desktop is
    its session: `xfce4-session` restarts the window manager and the desktop
    when one crashes, so a session still running is left to do that.
    """
    display = f"xdpyinfo -display {DISPLAY} >/dev/null 2>&1"
    return (
        f"{display} && pgrep -x xfce4-session >/dev/null && exit 0\n"
        f"for tool in Xvfb xdpyinfo startxfce4 xdotool scrot; do command -v $tool >/dev/null || exit {NO_DESKTOP}; done\n"
        f"if ! {display}; then\n"
        f"rm -f /tmp/.X{DISPLAY[1:]}-lock /tmp/.X11-unix/X{DISPLAY[1:]}\n"
        f"setsid nohup Xvfb {DISPLAY} -ac -screen 0 {width}x{height}x24 -nolisten tcp >/dev/null 2>&1 &\n"
        f"for _ in $(seq 100); do {display} && break; sleep 0.1; done\n"
        "fi\n"
        "if ! pgrep -x xfce4-session >/dev/null; then\n"
        f"DISPLAY={DISPLAY} setsid nohup dbus-launch --exit-with-session startxfce4 >/tmp/xfce.log 2>&1 &\n"
        "fi\n"
        "for _ in $(seq 600); do pgrep -x xfwm4 >/dev/null && pgrep -x xfdesktop >/dev/null && exit 0; sleep 0.1; done\n"
        "exit 1\n"
    )


class SandboxComputer:
    """The desktop in the run's sandbox, driven by commands run there.

    A click is one command round trip, which is what E2B's own desktop SDK does
    too. The screenshot is written under `/tmp` rather than the working directory,
    so it never shows up among the files the agent and the person see, and removed
    once read, so a later shell in the same sandbox - the agent's, a delegate's,
    the next run's - finds no picture of the screen there.
    """

    label = "Linux"

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace
        # One file per run's desktop: runs sharing a workspace share its `/tmp`.
        self._shot = f"/tmp/agenticos-screen-{uuid4().hex}.png"  # noqa: S108 - inside the sandbox

    async def _run(self, argv: list[str], what: str) -> None:
        try:
            result = await self._workspace.run(argv, env={"DISPLAY": DISPLAY}, timeout=60)
        except (WorkspaceError, OSError) as exc:
            logger.warning("sandbox desktop %s failed: %s", what, type(exc).__name__)
            raise ComputerError(
                f"The sandbox could not {what}. It may be stopped or restarting."
            ) from exc
        if result.exit_code != 0:
            said = (result.stderr or result.stdout).strip()[:200] or f"exit {result.exit_code}"
            raise ComputerError(f"The desktop refused to {what}: {said}")

    async def capture(self) -> Capture:
        """Take a screenshot; on X11 the picture and the pointer share one space."""
        await self._run(["scrot", "--overwrite", "--pointer", self._shot], "take a screenshot")
        try:
            image = await self._workspace.read_bytes(self._shot)
        except (WorkspaceError, OSError) as exc:
            logger.warning("sandbox screenshot unreadable: %s", type(exc).__name__)
            raise ComputerError("The sandbox did not return the screenshot it took.") from exc
        finally:
            await self._discard()
        width, height = png_size(image)
        return Capture(image=image, width=width, height=height)

    async def _discard(self) -> None:
        try:
            await self._workspace.remove(self._shot)
        except (WorkspaceError, OSError) as exc:
            # Failing the screenshot over a copy left behind would only make the
            # model take another, and leave that one behind too.
            logger.warning("sandbox screenshot not removed: %s", type(exc).__name__)

    async def close(self) -> None:
        """Nothing is held open: each screenshot is removed once read."""

    async def perform(self, action: NativeAction) -> None:
        """Carry out one action with `xdotool` inside the sandbox."""
        argv = xdotool(action)
        if argv is None:
            assert isinstance(action, Wait)
            await anyio.sleep(action.seconds)
            return
        await self._run(argv, f"run the {action.action} action")


async def open_sandbox_desktop(workspace: Workspace, *, width: int, height: int) -> SandboxComputer:
    """The desktop in the run's sandbox, started if it is not running.

    Raises:
        ComputerError: The run has no sandbox that runs commands, its runtime has
            no desktop installed, or the desktop did not come up. The model is
            told which.
    """
    if not workspace.attached or not isinstance(workspace.backend, SupportsCommands):
        raise ComputerError(
            "Computer use works on the agent's sandbox, and this run has none that runs "
            "commands. Add the Sandbox capability on a sandbox connection."
        )
    try:
        result = await workspace.run(_desktop_start(width, height), shell=True, timeout=90)  # noqa: S604
    except (WorkspaceError, OSError) as exc:
        logger.warning("sandbox desktop could not start: %s", type(exc).__name__)
        raise ComputerError("The sandbox could not be reached to start its desktop.") from exc
    if result.exit_code == NO_DESKTOP:
        raise ComputerError(
            "This sandbox has no desktop installed. Run the agent's sandbox on the "
            "`desktop` runtime."
        )
    if result.exit_code != 0:
        raise ComputerError("The desktop in the sandbox did not start.")
    return SandboxComputer(workspace)
