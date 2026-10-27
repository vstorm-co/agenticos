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

**An E2B desktop** is a sandbox of the run's own on the organization's E2B
account, opened from E2B's `desktop` template - which runs the same programs the
sandbox desktop drives - and killed when the run lets go of it. It needs no
Sandbox capability: it is a screen and nothing else, for an agent whose files
live elsewhere.

**The person's own computer** is the one a chat set to "Work on: This computer"
already works on (#2305): the desktop app takes the screenshot and moves the
pointer, after the person allowed it there, with an outline on the screen while
it does and a shortcut that stops it. It is reached through the device hub, the
way that chat's file and shell tools are, so it needs no address and no token.
"""

import base64
import logging
import struct
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import anyio
import httpx
from pydantic_ai.workspaces import SupportsCommands, Workspace, WorkspaceError

from app.agents.capabilities.computer_use._actions import (
    AnyAction,
    Click,
    Drag,
    Key,
    Launch,
    Move,
    Scroll,
    TypeText,
    Wait,
)
from app.agents.capabilities.sandbox._e2b import E2BWorkspace
from app.core.config import settings
from app.core.sanitize import UrlRefusedError
from app.services.device_hub import (
    DeviceCallFailed,
    DeviceCallTimedOut,
    DeviceUnavailable,
    DeviceWorkspace,
    call,
)

logger = logging.getLogger(__name__)

NativeAction = AnyAction
"""An action whose points `_actions.to_native` has moved into the backend's own space."""

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

    `None` for a wait, which is a sleep here rather than a process on the desktop,
    and for a launch, which is not `xdotool`'s.
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


_LIST_APPS = r"""
printf 'locale\t%s\n' "${LC_ALL:-${LC_MESSAGES:-$LANG}}"
IFS=:
for dir in "${XDG_DATA_HOME:-$HOME/.local/share}" ${XDG_DATA_DIRS:-/usr/local/share:/usr/share}; do
  for f in "$dir"/applications/*.desktop; do
    [ -f "$f" ] && printf '%s\t%s\n' "$f" "$(awk '
      /^\[/ { main = ($0 == "[Desktop Entry]") }
      main && /^(Name(\[[^]]*\])?|NoDisplay|Hidden)=/' "$f" | tr '\n' '\t')"
  done
done
exit 0
"""
"""The locale, then each desktop entry on the menu's search path, the user's own first.

One `path<TAB>key=value<TAB>...` line an entry, holding the main group's `Name`,
its translations, `NoDisplay` and `Hidden`; `find_app` picks the locale's name.
"""

# A session of its own, so the application outlives the command; no output,
# because the application inherits it and a pipe it holds open would hold the
# command open until the application quit.
_OPEN_APP = 'exec setsid -w timeout 20 exo-open "$1" </dev/null >/dev/null 2>&1'


@dataclass(frozen=True)
class _App:
    """A desktop entry the menu shows."""

    path: str
    stem: str
    name: str
    """What this desktop's menu calls it: the locale's own `Name`, else the untranslated one."""
    names: frozenset[str]
    """Casefolded: its file name, its untranslated `Name` and `name`, any of which launches it."""


def _locale_keys(locale: str) -> list[str]:
    """The `Name[...]` keys a locale such as `pl_PL.UTF-8` reads, most specific first.

    The desktop entry specification's order: `lang_COUNTRY@MODIFIER`,
    `lang_COUNTRY`, `lang@MODIFIER`, `lang`; the untranslated `Name` comes after.
    """
    rest, _, modifier = locale.partition("@")
    lang, _, country = rest.partition(".")[0].partition("_")
    if lang in {"", "C", "POSIX"}:
        return []
    keys = [f"{lang}_{country}@{modifier}"] if country and modifier else []
    keys += [f"{lang}_{country}"] if country else []
    keys += [f"{lang}@{modifier}"] if modifier else []
    return [*keys, lang]


def _parse_apps(listing: str) -> list[_App]:
    """The entries `_LIST_APPS` found, as the menu shows them.

    An entry earlier on the search path shadows a later one with the same file
    name even when it is hidden, which is how a user hides a system application.
    """
    head, _, body = listing.partition("\n")
    order = _locale_keys(head.removeprefix("locale\t"))
    apps: dict[str, _App | None] = {}
    for line in body.splitlines():
        path, *fields = line.split("\t")
        keys: dict[str, str] = {}
        for field in fields:
            key, _, value = field.partition("=")
            keys.setdefault(key, value.strip())
        stem = PurePosixPath(path).stem
        default = keys.get("Name", "")
        if not default or "true" in (keys.get("NoDisplay"), keys.get("Hidden")):
            apps.setdefault(stem, None)
            continue
        name = next((keys[f"Name[{k}]"] for k in order if keys.get(f"Name[{k}]")), default)
        names = frozenset(n.casefold() for n in (stem, default, name))
        apps.setdefault(stem, _App(path=path, stem=stem, name=name, names=names))
    return [app for app in apps.values() if app is not None]


def find_app(query: str, listing: str) -> str:
    """The desktop entry a `launch` names, from `_LIST_APPS`'s listing.

    Its file name, or its name in the desktop's locale or untranslated, exactly,
    or else the one entry with the query in one of those. Matching is case-insensitive,
    and an entry earlier on the search path shadows a later one with the same
    file name. Two entries the query names equally are never guessed between:
    a system Firefox and a Flatpak one are both called Firefox.

    Raises:
        ComputerError: None or several match; the model is told the names to choose from.
    """
    apps = _parse_apps(listing)
    wanted = query.casefold()
    found = [app for app in apps if wanted in app.names] or [
        app for app in apps if any(wanted in name for name in app.names)
    ]
    if len(found) == 1:
        return found[0].path
    if found:
        options = ", ".join(sorted(f"{app.name} ({app.stem})" for app in found))
        raise ComputerError(
            f"'{query}' could be any of: {options}. Launch one by its full name or the name in brackets."
        )
    names = ", ".join(sorted({app.name for app in apps})[:60]) or "none"
    raise ComputerError(f"No application called '{query}' is installed. These are: {names}.")


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
    # Long enough for the list of applications a `launch` that matched none is answered with.
    return str(error)[:1000] if error else f"HTTP {response.status_code}"


E2B_DESKTOP_TEMPLATE = "desktop"
"""E2B's own desktop template: Xvfb, XFCE, xdotool and scrot, what `SandboxComputer` drives."""

E2B_CLEANUP_SECONDS = 10.0


async def _release_e2b(provider: E2BWorkspace, workspace: Workspace) -> None:
    ref = workspace.ref
    if ref is None:
        return
    # Cleanup must survive cancellation without masking why opening or using
    # the desktop failed, or holding the run open on an unavailable provider.
    with anyio.move_on_after(E2B_CLEANUP_SECONDS, shield=True) as cleanup:
        try:
            await provider.destroy(ref)
        except Exception:
            logger.warning("e2b desktop not killed", exc_info=True)
    if cleanup.cancel_called:
        logger.warning("e2b desktop cleanup timed out")


class E2BComputer:
    """An E2B desktop of the run's own, driven as the sandbox desktop is, and killed after."""

    label = "Linux (E2B)"

    def __init__(
        self, provider: E2BWorkspace, workspace: Workspace, desktop: SandboxComputer
    ) -> None:
        self._provider = provider
        self._workspace = workspace
        self._desktop = desktop

    async def capture(self) -> Capture:
        return await self._desktop.capture()

    async def perform(self, action: NativeAction) -> None:
        await self._desktop.perform(action)

    async def close(self) -> None:
        """Kill the sandbox: nothing else ends it before its lifetime runs out, on their bill."""
        await _release_e2b(self._provider, self._workspace)


async def open_e2b_desktop(api_key: str, *, width: int, height: int) -> E2BComputer:
    """A fresh E2B desktop on the organization's key.

    Raises:
        ComputerError: E2B refused the key or did not start the desktop.
    """
    if not api_key:
        raise ComputerError(
            "Computer use on E2B needs the organization's E2B key. Name it from the "
            "vault on the capability."
        )
    provider = E2BWorkspace(api_key=api_key, template=E2B_DESKTOP_TEMPLATE)
    workspace = Workspace(provider.backend(None))
    try:
        desktop = await open_sandbox_desktop(workspace, width=width, height=height)
    except BaseException:
        await _release_e2b(provider, workspace)
        raise
    return E2BComputer(provider, workspace, desktop)


LOCAL_SCREEN_SECONDS = 60.0
"""How long one screen operation on the person's computer may take - the first
one waits for them to answer the app's "let your agent use this screen?"."""


class LocalComputer:
    """The person's own screen, through the desktop app on that computer."""

    label = "Your computer"

    def __init__(self, session_id: UUID) -> None:
        self._session_id = session_id

    async def _call(self, op: str, args: dict[str, object]) -> dict[str, object]:
        try:
            return await call(self._session_id, op, dict(args), timeout=LOCAL_SCREEN_SECONDS)
        except DeviceUnavailable as exc:
            raise ComputerError(
                "Your computer is not connected: open the AgenticOS app on it."
            ) from exc
        except DeviceCallTimedOut as exc:
            raise ComputerError("Your computer did not answer in time.") from exc
        except DeviceCallFailed as exc:
            raise ComputerError(exc.message) from exc

    async def capture(self) -> Capture:
        """Take a screenshot; the app names the space its pointer moves in."""
        value = await self._call("screen.capture", {})
        platform = value.get("platform")
        if isinstance(platform, str) and platform:
            self.label = platform
        image = base64.b64decode(str(value.get("data", "")))
        width, height = png_size(image)
        native_width, native_height = value.get("width"), value.get("height")
        return Capture(
            image=image,
            width=native_width if isinstance(native_width, int) else width,
            height=native_height if isinstance(native_height, int) else height,
        )

    async def perform(self, action: NativeAction) -> None:
        """Send one action; the app answers once it has been carried out."""
        if isinstance(action, Launch):
            raise ComputerError(
                "This computer cannot open applications by name. Use its own launcher: "
                "cmd+space and the name on a Mac, the Start menu elsewhere, then wait."
            )
        if isinstance(action, Wait):
            await anyio.sleep(action.seconds)
            return
        await self._call("screen.act", {"action": action.model_dump()})

    async def close(self) -> None:
        """Tell the app the run is done with the screen, so its outline goes."""
        try:
            await self._call("screen.release", {})
        except ComputerError:
            logger.info("local screen release not delivered")


def open_local_desktop(workspace: Workspace) -> LocalComputer:
    """The person's own computer, when the run works on it.

    Raises:
        ComputerError: The chat is not working on the person's computer.
    """
    backend = workspace.backend if workspace.attached else None
    if not isinstance(backend, DeviceWorkspace):
        raise ComputerError(
            "Computer use on your own computer works in a chat set to work on this "
            "computer, from the desktop app."
        )
    return LocalComputer(backend.session_id)


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

    async def _run(self, argv: list[str], what: str) -> str:
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
        return result.stdout

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
        if isinstance(action, Launch):
            listing = await self._run(["sh", "-c", _LIST_APPS], "list its applications")
            entry = find_app(action.app, listing)
            await self._run(["sh", "-c", _OPEN_APP, "launch", entry], f"open {action.app}")
            return
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
