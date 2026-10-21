"""Where the desktop is: a `computerd` daemon the operator runs, or an E2B sandbox.

Both answer the same two questions - what is on the screen, and do this - and
neither is told how the model's screenshot was scaled; `_actions.to_native` has
already moved every point into the backend's own input space by the time an
action arrives here.

**A daemon** is the operator's machine: a Linux desktop in a container, or a Mac.
It is reached over HTTP with `COMPUTER_DAEMON_TOKEN`, and its host has to be on
`COMPUTER_DAEMON_ALLOWED_HOSTS` - the same reasoning as `BROWSER_CDP_ALLOWED_HOSTS`,
since the URL is in a spec an agent's editor writes. One daemon is one desktop:
every run pointed at it shares it, which is why it suits a dedicated machine and
not a tenant-per-desktop deployment.

**E2B** is a Firecracker microVM per conversation, created on first use and found
again by its metadata on the next turn, so the desktop a person was watching is
the one the follow-up question acts on. It dies on E2B's own timeout, refreshed on
every connect - nothing here has to remember to delete it.
"""

import logging
import shlex
import struct
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol, cast

import anyio
import httpx

from app.agents.capabilities.computer_use._actions import (
    Click,
    Drag,
    Key,
    Move,
    Scroll,
    TypeText,
    Wait,
)

logger = logging.getLogger(__name__)

NativeAction = Click | Move | Drag | Scroll | TypeText | Key | Wait

MISSING_EXTRA = (
    "E2B desktops are not installed in this deployment. Build the backend with the "
    '`computer` extra (BACKEND_EXTRAS="--extra computer").'
)

DISPLAY = ":0"
"""The X display a sandbox's desktop runs on."""

E2B_SESSION_KEY = "agenticos_session"
"""The metadata key a sandbox is found again by on the next turn."""


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


ComputerFactory = Callable[[], Awaitable[Computer]]


class _CommandResult(Protocol):
    stdout: str


class _Commands(Protocol):
    def run(self, cmd: str, *, envs: dict[str, str], timeout: float) -> _CommandResult: ...


class _Files(Protocol):
    def read(self, path: str, format: Literal["bytes"]) -> bytearray: ...  # noqa: A002 - the SDK's keyword


class E2BSandbox(Protocol):
    """The part of the E2B SDK's sandbox this module uses.

    Declared rather than imported because the SDK is an optional extra, and a
    test hands in a fake with exactly these two attributes.
    """

    @property
    def commands(self) -> _Commands: ...
    @property
    def files(self) -> _Files: ...


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


def xdotool(action: NativeAction) -> str | None:
    """The shell command that carries out an action on an X11 display.

    `None` for a wait, which is a sleep here rather than a process on the desktop.
    Every value reaching the shell is either an int or `shlex.quote`d.
    """
    match action:
        case Click():
            return (
                f"xdotool mousemove --sync {action.x} {action.y} "
                f"click --repeat {action.count} {_MOUSE_BUTTONS[action.button]}"
            )
        case Move():
            return f"xdotool mousemove --sync {action.x} {action.y}"
        case Drag():
            return (
                f"xdotool mousemove --sync {action.x} {action.y} mousedown 1 "
                f"mousemove --sync {action.to_x} {action.to_y} mouseup 1"
            )
        case Scroll():
            return (
                f"xdotool mousemove --sync {action.x} {action.y} "
                f"click --repeat {action.amount} {_SCROLL_BUTTONS[action.direction]}"
            )
        case TypeText():
            return f"xdotool type --delay 12 -- {shlex.quote(action.text)}"
        case Key():
            return f"xdotool key -- {shlex.quote(x11_keys(action.keys))}"
        case _:
            return None


class DaemonComputer:
    """A desktop served by `computerd` - see `deploy/computer/README.md`."""

    def __init__(
        self, base_url: str, token: str, *, client: httpx.AsyncClient | None = None
    ) -> None:
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


def _error_text(response: httpx.Response) -> str:
    """The daemon's own one-line reason, or the status when it gave none."""
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    error = body.get("error") if isinstance(body, dict) else None
    return str(error)[:200] if error else f"HTTP {response.status_code}"


class E2BComputer:
    """A desktop in an E2B sandbox, one per session key.

    The SDK is synchronous, so every call runs in a worker thread; a click is one
    command round trip to the sandbox, which is what E2B's own desktop SDK does.
    """

    label = "Linux (E2B)"

    def __init__(self, sandbox: E2BSandbox) -> None:
        self._sandbox = sandbox

    def _run(self, command: str) -> str:
        return self._sandbox.commands.run(command, envs={"DISPLAY": DISPLAY}, timeout=60).stdout

    def _shoot(self) -> bytes:
        path = "/tmp/agenticos-screenshot.png"  # noqa: S108 - inside the sandbox, which is the session's alone
        self._run(f"scrot --overwrite --pointer {path}")
        return bytes(self._sandbox.files.read(path, format="bytes"))

    async def capture(self) -> Capture:
        """Take a screenshot; on X11 the picture and the pointer share one space."""
        try:
            image = await anyio.to_thread.run_sync(self._shoot)
        except Exception as exc:
            logger.warning("E2B screenshot failed: %s", type(exc).__name__)
            raise ComputerError("The E2B desktop did not return a screenshot.") from exc
        width, height = png_size(image)
        return Capture(image=image, width=width, height=height)

    async def perform(self, action: NativeAction) -> None:
        """Carry out one action with `xdotool` inside the sandbox."""
        if isinstance(action, Wait):
            await anyio.sleep(action.seconds)
            return
        command = xdotool(action)
        assert command is not None
        try:
            await anyio.to_thread.run_sync(self._run, command)
        except Exception as exc:
            logger.warning("E2B action failed: %s", type(exc).__name__)
            raise ComputerError(f"The E2B desktop refused the {action.action} action.") from exc


@dataclass(frozen=True)
class E2BSettings:
    """How a sandbox is created, and how long it outlives its last use."""

    api_key: str
    session: str
    template: str = "desktop"
    width: int = 1280
    height: int = 800
    timeout_seconds: int = 900


def _desktop_start(width: int, height: int) -> str:
    """The script that starts a new sandbox's display and desktop, and waits for both.

    E2B's `desktop` template has the X server and XFCE installed but not running.
    This is what the `e2b-desktop` package does on create, done here so the extra
    needs only `e2b`: that package pins `pillow<13`, and an extra's pin moves the
    whole lock. Both are started with `nohup`, so they outlive the command.
    """
    return (
        f"nohup Xvfb {DISPLAY} -ac -screen 0 {width}x{height}x24 -nolisten tcp >/dev/null 2>&1 &\n"
        f"for _ in $(seq 100); do xdpyinfo -display {DISPLAY} >/dev/null 2>&1 && break; sleep 0.1; done\n"
        f"DISPLAY={DISPLAY} nohup startxfce4 >/dev/null 2>&1 &\n"
        "for _ in $(seq 600); do pgrep -x xfwm4 >/dev/null && pgrep -x xfdesktop >/dev/null && exit 0; sleep 0.1; done\n"
        "exit 1\n"
    )


def _open_e2b(settings: E2BSettings) -> E2BSandbox:
    """Find this session's sandbox, or create it. Blocking - run in a thread."""
    try:
        from e2b import Sandbox, SandboxQuery  # ty: ignore[unresolved-import] - the `computer` extra
    except ImportError as exc:
        raise ComputerError(MISSING_EXTRA) from exc

    query = SandboxQuery(metadata={E2B_SESSION_KEY: settings.session})
    paginator = Sandbox.list(query=query, limit=1, api_key=settings.api_key)
    existing = paginator.next_items() if paginator.has_next else []
    if existing:
        sandbox = Sandbox.connect(
            existing[0].sandbox_id, timeout=settings.timeout_seconds, api_key=settings.api_key
        )
    else:
        sandbox = Sandbox.create(
            template=settings.template,
            timeout=settings.timeout_seconds,
            metadata={E2B_SESSION_KEY: settings.session},
            api_key=settings.api_key,
        )
        try:
            sandbox.commands.run(_desktop_start(settings.width, settings.height), timeout=90)
        except Exception:
            sandbox.kill()
            raise
    return cast(E2BSandbox, sandbox)


async def open_e2b(settings: E2BSettings) -> E2BComputer:
    """This session's E2B desktop, created on first use.

    Raises:
        ComputerError: The extra is missing, or E2B refused - a bad key, a plan
            limit, an outage. The model is told which of the first two it was.
    """
    try:
        sandbox = await anyio.to_thread.run_sync(_open_e2b, settings)
    except ComputerError:
        raise
    except Exception as exc:
        logger.warning("E2B sandbox could not be opened: %s", type(exc).__name__)
        raise ComputerError(
            "The E2B desktop could not be started. Check the E2B key bound to this "
            "capability and the account's sandbox limits."
        ) from exc
    return E2BComputer(sandbox)
