# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyobjc-framework-Quartz>=10; sys_platform == 'darwin'",
# ]
# ///
"""computerd - one desktop, served to AgenticOS's `computer_use` capability.

Three endpoints behind a bearer token:

    GET  /screenshot   the main screen as PNG; `x-screen-width` / `x-screen-height`
                       name the space the pointer moves in (points on a Retina Mac,
                       pixels on X11), `x-platform` what the panel calls it
    POST /actions      {"actions": [{"action": "click", "x": 10, "y": 20}, ...]}
                       carried out in order; 400 {"error": ...} on the first refusal
    GET  /apps         the applications a `launch` action may name, as JSON

and `GET /health`, unauthenticated, for a container's health check.

`launch` and `/apps` are the container's only: there the desktop's own account
runs `computerd.py launcher <socket>`, which lists and opens its menu's
applications with `desktop_apps.py` (the backend's `_desktop_apps.py`, copied in
by the Dockerfile), and the entrypoint names that socket in `COMPUTERD_LAUNCHER`.
Without it both are refused, and the model is pointed at the desktop's own
launcher.

Standard library only on Linux (it shells out to `scrot` and `xdotool`, so X11
only: a Wayland session reaches nothing but its XWayland windows that way); on
macOS it needs Quartz, which the inline script metadata above declares, so

    COMPUTERD_TOKEN=... uv run deploy/computer/computerd.py

is the whole installation. macOS asks for Screen Recording and Accessibility for
the terminal that runs it, the first time; until both are granted screenshots
show only the wallpaper and clicks do nothing.

Another desktop - a Wayland compositor, Windows - is a `Driver` subclass picked
in `main()`; the class says what it owes.

Settings, all from the environment:

    COMPUTERD_TOKEN   required; the API key the organization's vault holds for this desktop
    COMPUTERD_HOST    default 127.0.0.1 - set 0.0.0.0 only on a network you trust
    COMPUTERD_PORT    default 8765
    COMPUTERD_LAUNCHER  the container's; the socket of the launcher running as the desktop's user
"""

from __future__ import annotations

import json
import os
import platform
import re
import secrets
import shutil
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

MAX_TEXT = 2000
MAX_BODY = 256 * 1024
MAX_ERROR = 200
APP_NAME = re.compile(r"\w[^/\\\x00-\x1f\x7f]{0,63}")  # as `Launch.app`: no path, option or control character
NO_LAUNCH = (
    "This desktop cannot open applications by name. Use its own launcher: cmd+space "
    "and the name on a Mac, the Start menu elsewhere."
)


class Refused(Exception):
    """An action this desktop will not or cannot carry out; the text goes back to the caller."""


def png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise Refused("screenshot is not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def capture_png(argv: list[str]) -> bytes:
    """Run a command that writes a screenshot to the path it is given, and read it back.

    Into a directory only this process can read, removed with the picture, so no
    screen is left on the host's disk for another user to find.
    """
    with tempfile.TemporaryDirectory(prefix="computerd-") as directory:
        shot = Path(directory) / "screen.png"
        subprocess.run([*argv, str(shot)], check=True, timeout=30)
        return shot.read_bytes()


def _int(action: dict[str, Any], key: str, *, low: int = 0, high: int = 100_000, default: int | None = None) -> int:
    value = action.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise Refused(f"'{key}' must be an integer between {low} and {high}")
    return value


class Driver(ABC):
    """One desktop's screen, pointer and keyboard - what a new desktop implements.

    Subclass it and pick the subclass in `main()`. `perform` has already checked
    every argument against the ranges below, so a driver only carries the action
    out. Coordinates are in the space `screenshot` reports: the model clicks where
    it saw something, so `(x, y)` has to land on that spot of the last screenshot.
    Raise `Refused` for what this desktop cannot do; its text goes back to the
    model, so say what to change.
    """

    name: str
    """What the panel calls this desktop (`x-platform`): "Linux", "macOS"."""

    @abstractmethod
    def screenshot(self) -> tuple[bytes, int, int]:
        """The main screen as PNG, and the width and height pointer coordinates are in.

        The image may be larger than that space - a Retina Mac's is twice its
        points - and AgenticOS scales between the two.
        """

    @abstractmethod
    def click(self, x: int, y: int, button: str, count: int) -> None:
        """Click `button` (left, right or middle) at a point, `count` (1 to 3) times."""

    @abstractmethod
    def move(self, x: int, y: int) -> None:
        """Move the pointer without pressing anything."""

    @abstractmethod
    def drag(self, x: int, y: int, to_x: int, to_y: int) -> None:
        """Press the left button at one point, move to another and release it there."""

    @abstractmethod
    def scroll(self, x: int, y: int, direction: str, amount: int) -> None:
        """Scroll with the pointer at a point: up, down, left or right, `amount` (1 to 20) notches."""

    @abstractmethod
    def type_text(self, text: str) -> None:
        """Type text into whatever has focus, newlines and non-ASCII characters included."""

    @abstractmethod
    def key(self, chord: str) -> None:
        """Press a chord such as `ctrl+shift+t`, `enter` or `cmd+space`; `split_chord` parses it."""


def split_chord(chord: str) -> list[str]:
    parts = [part.strip().lower() for part in chord.split("+") if part.strip()]
    if not parts:
        raise Refused(f"{chord!r} names no key")
    return parts


class _Launcher(socketserver.StreamRequestHandler):
    """One request from computerd - `list` or `launch <app>` - and its JSON answer, a line each."""

    def handle(self) -> None:
        # Beside this file in the image only, and only the launcher needs it.
        import desktop_apps

        request = self.rfile.readline(256).decode(errors="replace").strip()
        env = dict(os.environ)
        reply: dict[str, Any]
        try:
            match request.split(" ", 1):
                case ["list"]:
                    reply = {"apps": [asdict(app) for app in desktop_apps.installed(env)]}
                case ["launch", app] if APP_NAME.fullmatch(app):
                    desktop_apps.launch(desktop_apps.find(app, desktop_apps.installed(env)))
                    reply = {"ok": True}
                case _:
                    reply = {"error": "expected 'list' or 'launch <app>'"}
        except desktop_apps.AppError as exc:
            reply = {"error": str(exc)}
        self.wfile.write(json.dumps(reply).encode() + b"\n")


def ask_launcher(request: str) -> dict[str, Any]:
    """Have the desktop's own account list or open its applications - see `serve_launcher`."""
    launcher = os.environ.get("COMPUTERD_LAUNCHER")
    if not launcher:
        raise Refused(NO_LAUNCH)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(40)
            conn.connect(launcher)
            conn.sendall(request.encode() + b"\n")
            reply = json.loads(conn.makefile("rb").readline())
    except (OSError, ValueError) as exc:
        raise Refused(f"the desktop's launcher did not answer: {exc}") from exc
    if "error" in reply:
        raise Refused(reply["error"])
    return reply


def serve_launcher(path: str) -> None:
    """List and open applications for computerd, as the desktop's own account.

    The socket is this account's and its directory's group's only; the
    entrypoint makes that group computerd's, so computerd can ask and nothing
    else in the container can.
    """
    os.umask(0o007)
    Path(path).unlink(missing_ok=True)
    with socketserver.UnixStreamServer(path, _Launcher) as server:
        server.serve_forever()


class X11Driver(Driver):
    """Any X11 display, through `scrot` and `xdotool`."""

    name = "Linux"

    _KEYS = {
        "enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape", "tab": "Tab",
        "space": "space", "backspace": "BackSpace", "delete": "Delete", "del": "Delete", "home": "Home",
        "end": "End", "pageup": "Prior", "page_up": "Prior", "pagedown": "Next", "page_down": "Next",
        "up": "Up", "down": "Down", "left": "Left", "right": "Right", "insert": "Insert",
        "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "option": "alt", "shift": "shift",
        "cmd": "super", "command": "super", "super": "super", "meta": "super", "win": "super",
    }
    _BUTTONS = {"left": "1", "middle": "2", "right": "3"}
    _WHEEL = {"up": "4", "down": "5", "left": "6", "right": "7"}

    def __init__(self) -> None:
        for tool in ("scrot", "xdotool"):
            if shutil.which(tool) is None:
                sys.exit(f"computerd: {tool} is not installed")

    def _xdotool(self, *args: str) -> None:
        result = subprocess.run(["xdotool", *args], capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            raise Refused(f"xdotool failed: {result.stderr.strip()[:200]}")

    def screenshot(self) -> tuple[bytes, int, int]:
        data = capture_png(["scrot", "--overwrite", "--pointer"])
        width, height = png_size(data)
        return data, width, height

    def click(self, x: int, y: int, button: str, count: int) -> None:
        self._xdotool("mousemove", "--sync", str(x), str(y), "click", "--repeat", str(count), self._BUTTONS[button])

    def move(self, x: int, y: int) -> None:
        self._xdotool("mousemove", "--sync", str(x), str(y))

    def drag(self, x: int, y: int, to_x: int, to_y: int) -> None:
        self._xdotool(
            "mousemove", "--sync", str(x), str(y), "mousedown", "1",
            "mousemove", "--sync", str(to_x), str(to_y), "mouseup", "1",
        )

    def scroll(self, x: int, y: int, direction: str, amount: int) -> None:
        self._xdotool("mousemove", "--sync", str(x), str(y), "click", "--repeat", str(amount), self._WHEEL[direction])

    def type_text(self, text: str) -> None:
        self._xdotool("type", "--delay", "12", "--", text)

    def key(self, chord: str) -> None:
        self._xdotool("key", "--", "+".join(self._KEYS.get(part, part) for part in split_chord(chord)))

class MacDriver(Driver):
    """The Mac's main display, through `screencapture` and Quartz events."""

    name = "macOS"

    _KEYCODES = {
        "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12,
        "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
        "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34,
        "p": 35, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46,
        ".": 47, "`": 50,
        "enter": 36, "return": 36, "tab": 48, "space": 49, "backspace": 51, "esc": 53, "escape": 53,
        "delete": 117, "del": 117, "home": 115, "end": 119, "pageup": 116, "page_up": 116,
        "pagedown": 121, "page_down": 121, "left": 123, "right": 124, "down": 125, "up": 126,
        "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101,
        "f10": 109, "f11": 103, "f12": 111,
        "cmd": 55, "command": 55, "super": 55, "meta": 55, "win": 55, "shift": 56, "alt": 58, "option": 58,
        "ctrl": 59, "control": 59,
    }

    def __init__(self) -> None:
        import Quartz  # ty: ignore[unresolved-import] - macOS only, from the script's own metadata

        self.q = Quartz
        self._flags = {
            "cmd": Quartz.kCGEventFlagMaskCommand, "command": Quartz.kCGEventFlagMaskCommand,
            "super": Quartz.kCGEventFlagMaskCommand, "meta": Quartz.kCGEventFlagMaskCommand,
            "win": Quartz.kCGEventFlagMaskCommand, "shift": Quartz.kCGEventFlagMaskShift,
            "alt": Quartz.kCGEventFlagMaskAlternate, "option": Quartz.kCGEventFlagMaskAlternate,
            "ctrl": Quartz.kCGEventFlagMaskControl, "control": Quartz.kCGEventFlagMaskControl,
        }
        if not Quartz.CGPreflightScreenCaptureAccess():
            Quartz.CGRequestScreenCaptureAccess()
            print("computerd: grant Screen Recording to this terminal, then restart it", file=sys.stderr)
        if not Quartz.CGPreflightPostEventAccess():
            Quartz.CGRequestPostEventAccess()
            print("computerd: grant Accessibility to this terminal, then restart it", file=sys.stderr)

    def _bounds(self) -> tuple[int, int]:
        rect = self.q.CGDisplayBounds(self.q.CGMainDisplayID())
        return int(rect.size.width), int(rect.size.height)

    def screenshot(self) -> tuple[bytes, int, int]:
        data = capture_png(["screencapture", "-x", "-m", "-C", "-t", "png"])
        width, height = self._bounds()
        return data, width, height

    def _post(self, event: Any) -> None:
        self.q.CGEventPost(self.q.kCGHIDEventTap, event)

    def _mouse(self, kind: int, x: int, y: int, button: int, clicks: int = 1) -> None:
        event = self.q.CGEventCreateMouseEvent(None, kind, (x, y), button)
        self.q.CGEventSetIntegerValueField(event, self.q.kCGMouseEventClickState, clicks)
        self._post(event)

    def click(self, x: int, y: int, button: str, count: int) -> None:
        q = self.q
        down, up, code = {
            "left": (q.kCGEventLeftMouseDown, q.kCGEventLeftMouseUp, q.kCGMouseButtonLeft),
            "right": (q.kCGEventRightMouseDown, q.kCGEventRightMouseUp, q.kCGMouseButtonRight),
            "middle": (q.kCGEventOtherMouseDown, q.kCGEventOtherMouseUp, q.kCGMouseButtonCenter),
        }[button]
        self.move(x, y)
        for click in range(1, count + 1):
            self._mouse(down, x, y, code, click)
            self._mouse(up, x, y, code, click)

    def move(self, x: int, y: int) -> None:
        self._mouse(self.q.kCGEventMouseMoved, x, y, self.q.kCGMouseButtonLeft)
        time.sleep(0.05)

    def drag(self, x: int, y: int, to_x: int, to_y: int) -> None:
        q = self.q
        self.move(x, y)
        self._mouse(q.kCGEventLeftMouseDown, x, y, q.kCGMouseButtonLeft)
        steps = 20
        for i in range(1, steps + 1):
            px = round(x + (to_x - x) * i / steps)
            py = round(y + (to_y - y) * i / steps)
            self._mouse(q.kCGEventLeftMouseDragged, px, py, q.kCGMouseButtonLeft)
            time.sleep(0.01)
        self._mouse(q.kCGEventLeftMouseUp, to_x, to_y, q.kCGMouseButtonLeft)

    def scroll(self, x: int, y: int, direction: str, amount: int) -> None:
        self.move(x, y)
        dy = {"up": amount, "down": -amount}.get(direction, 0)
        dx = {"left": amount, "right": -amount}.get(direction, 0)
        event = self.q.CGEventCreateScrollWheelEvent(None, self.q.kCGScrollEventUnitLine, 2, dy, dx)
        self._post(event)

    def _keystroke(self, code: int, flags: int = 0) -> None:
        for down in (True, False):
            event = self.q.CGEventCreateKeyboardEvent(None, code, down)
            if flags:
                self.q.CGEventSetFlags(event, flags)
            self._post(event)
        time.sleep(0.01)

    def type_text(self, text: str) -> None:
        # Unicode strings rather than keycodes, so the text arrives as written
        # whatever the keyboard layout - except a newline, which an app only
        # treats as Return when it is one.
        for char in text:
            if char == "\n":
                self._keystroke(self._KEYCODES["return"])
                continue
            units = len(char.encode("utf-16-le")) // 2
            for down in (True, False):
                event = self.q.CGEventCreateKeyboardEvent(None, 0, down)
                self.q.CGEventKeyboardSetUnicodeString(event, units, char)
                self._post(event)
            time.sleep(0.008)

    def key(self, chord: str) -> None:
        parts = split_chord(chord)
        *modifiers, main = parts
        flags = 0
        for modifier in modifiers:
            if modifier not in self._flags:
                raise Refused(f"'{modifier}' is not a modifier")
            flags |= self._flags[modifier]
        if main not in self._KEYCODES:
            raise Refused(f"'{main}' is not a key this desktop knows")
        self._keystroke(self._KEYCODES[main], flags)

def perform(driver: Driver, action: dict[str, Any]) -> None:
    kind = action.get("action")
    if kind == "click":
        button = action.get("button", "left")
        if button not in {"left", "right", "middle"}:
            raise Refused("'button' must be left, right or middle")
        driver.click(_int(action, "x"), _int(action, "y"), button, _int(action, "count", low=1, high=3, default=1))
    elif kind == "move":
        driver.move(_int(action, "x"), _int(action, "y"))
    elif kind == "drag":
        driver.drag(_int(action, "x"), _int(action, "y"), _int(action, "to_x"), _int(action, "to_y"))
    elif kind == "scroll":
        direction = action.get("direction", "down")
        if direction not in {"up", "down", "left", "right"}:
            raise Refused("'direction' must be up, down, left or right")
        driver.scroll(_int(action, "x"), _int(action, "y"), direction, _int(action, "amount", low=1, high=20, default=3))
    elif kind == "type":
        text = action.get("text")
        if not isinstance(text, str) or not 0 < len(text) <= MAX_TEXT:
            raise Refused(f"'text' must be 1 to {MAX_TEXT} characters")
        driver.type_text(text)
    elif kind == "key":
        keys = action.get("keys")
        if not isinstance(keys, str) or not 0 < len(keys) <= 64:
            raise Refused("'keys' must be 1 to 64 characters")
        driver.key(keys)
    elif kind == "launch":
        app = action.get("app")
        if not isinstance(app, str) or not APP_NAME.fullmatch(app):
            raise Refused("'app' must be an application's name: up to 64 characters, no slash or control character")
        ask_launcher(f"launch {app}")
    elif kind == "wait":
        seconds = action.get("seconds", 1.0)
        if not isinstance(seconds, int | float) or not 0 < seconds <= 10:
            raise Refused("'seconds' must be above 0 and at most 10")
        time.sleep(seconds)
    else:
        raise Refused(f"unknown action {kind!r}")


def make_handler(driver: Driver, token: str) -> type[BaseHTTPRequestHandler]:
    lock = threading.Lock()  # one desktop, one pointer: never two requests driving it at once
    expected = f"Bearer {token}".encode()

    class Handler(BaseHTTPRequestHandler):
        server_version = "computerd/0.1"

        def log_message(self, format: str, *args: Any) -> None:
            sys.stderr.write(f"computerd: {self.command} {self.path} {args[1] if len(args) > 1 else ''}\n")

        def _json(self, status: HTTPStatus, body: object) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            given = self.headers.get("authorization", "").encode()
            if secrets.compare_digest(given, expected):
                return True
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return False

        def do_GET(self) -> None:
            if self.path == "/health":
                self._json(HTTPStatus.OK, {"ok": True, "platform": driver.name})
                return
            if self.path not in {"/screenshot", "/apps"}:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            if not self._authorized():
                return
            if self.path == "/apps":
                try:
                    self._json(HTTPStatus.OK, ask_launcher("list")["apps"])
                except Refused as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)[:MAX_ERROR]})
                return
            try:
                with lock:
                    image, width, height = driver.screenshot()
            except (Refused, subprocess.SubprocessError, OSError) as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"screenshot failed: {exc}"[:200]})
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", "image/png")
            self.send_header("content-length", str(len(image)))
            self.send_header("x-screen-width", str(width))
            self.send_header("x-screen-height", str(height))
            self.send_header("x-platform", driver.name)
            self.end_headers()
            self.wfile.write(image)

        def do_POST(self) -> None:
            if self.path != "/actions":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            if not self._authorized():
                return
            length = int(self.headers.get("content-length") or 0)
            if not 0 < length <= MAX_BODY:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "body missing or too large"})
                return
            try:
                body = json.loads(self.rfile.read(length))
                actions = body["actions"]
                if not isinstance(actions, list) or not all(isinstance(a, dict) for a in actions):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "expected {\"actions\": [ ... ]}"})
                return
            done = 0
            try:
                with lock:
                    for action in actions:
                        perform(driver, action)
                        done += 1
            except Refused as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)[:MAX_ERROR], "done": done})
                return
            self._json(HTTPStatus.OK, {"ok": True, "done": done})

    return Handler


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "launcher":
        serve_launcher(sys.argv[2])
        return
    token = os.environ.get("COMPUTERD_TOKEN", "")
    if len(token) < 16:
        sys.exit("computerd: set COMPUTERD_TOKEN to at least 16 characters (the key in the organization's vault)")
    host = os.environ.get("COMPUTERD_HOST", "127.0.0.1")
    port = int(os.environ.get("COMPUTERD_PORT", "8765"))
    driver: Driver = MacDriver() if platform.system() == "Darwin" else X11Driver()
    server = ThreadingHTTPServer((host, port), make_handler(driver, token))
    print(f"computerd: {driver.name} desktop on http://{host}:{port}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
