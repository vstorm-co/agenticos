# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyobjc-framework-Quartz>=10; sys_platform == 'darwin'",
# ]
# ///
"""computerd - one desktop, served to AgenticOS's `computer_use` capability.

Two endpoints behind a bearer token:

    GET  /screenshot   the main screen as PNG; `x-screen-width` / `x-screen-height`
                       name the space the pointer moves in (points on a Retina Mac,
                       pixels on X11), `x-platform` what the panel calls it
    POST /actions      {"actions": [{"action": "click", "x": 10, "y": 20}, ...]}
                       carried out in order; 400 {"error": ...} on the first refusal

and `GET /health`, unauthenticated, for a container's health check.

Standard library only on Linux. It shells out to `scrot` and `xdotool` on X11,
and to `spectacle` and `dotool` in a KDE Plasma session on Wayland (chosen when
`WAYLAND_DISPLAY` is set; `dotool` needs write access to `/dev/uinput`). On macOS
it needs Quartz, which the inline script metadata above declares, so

    COMPUTERD_TOKEN=... uv run deploy/computer/computerd.py

is the whole installation. macOS asks for Screen Recording and Accessibility for
the terminal that runs it, the first time; until both are granted screenshots
show only the wallpaper and clicks do nothing.

Settings, all from the environment:

    COMPUTERD_TOKEN   required; AgenticOS's COMPUTER_DAEMON_TOKEN
    COMPUTERD_HOST    default 127.0.0.1 - set 0.0.0.0 only on a network you trust
    COMPUTERD_PORT    default 8765
"""

from __future__ import annotations

import json
import os
import platform
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol

MAX_TEXT = 2000
MAX_BODY = 256 * 1024


class Refused(Exception):
    """An action this desktop will not or cannot carry out; the text goes back to the caller."""


def png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise Refused("screenshot is not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _int(action: dict[str, Any], key: str, *, low: int = 0, high: int = 100_000, default: int | None = None) -> int:
    value = action.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise Refused(f"'{key}' must be an integer between {low} and {high}")
    return value


class Driver(Protocol):
    name: str

    def screenshot(self) -> tuple[bytes, int, int]: ...
    def click(self, x: int, y: int, button: str, count: int) -> None: ...
    def move(self, x: int, y: int) -> None: ...
    def drag(self, x: int, y: int, to_x: int, to_y: int) -> None: ...
    def scroll(self, x: int, y: int, direction: str, amount: int) -> None: ...
    def type_text(self, text: str) -> None: ...
    def key(self, chord: str) -> None: ...


def split_chord(chord: str) -> list[str]:
    parts = [part.strip().lower() for part in chord.split("+") if part.strip()]
    if not parts:
        raise Refused(f"{chord!r} names no key")
    return parts


class X11Driver:
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
        self._shot = Path(tempfile.gettempdir()) / f"computerd-{os.getpid()}.png"

    def _xdotool(self, *args: str) -> None:
        result = subprocess.run(["xdotool", *args], capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            raise Refused(f"xdotool failed: {result.stderr.strip()[:200]}")

    def screenshot(self) -> tuple[bytes, int, int]:
        subprocess.run(["scrot", "--overwrite", "--pointer", str(self._shot)], check=True, timeout=30)
        data = self._shot.read_bytes()
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


class KdeWaylandDriver:
    """A KDE Plasma session on Wayland, through `spectacle` and `dotool`.

    Wayland hands no client the screen or the pointer, so `scrot` and `xdotool`
    reach nothing but XWayland windows. Spectacle is a client KWin lets capture
    the whole screen. `dotool` writes to `/dev/uinput`, a virtual keyboard and
    mouse below the compositor, and its `mouseto` places the pointer as a
    fraction of the screen through an absolute device, so pointer acceleration
    cannot bend a click.

    One `dotool` process lives as long as the daemon: a new one is a new virtual
    device, and the compositor drops what it is sent before it has noticed one.
    """

    name = "Linux"

    _KEYS = {
        "return": "enter", "escape": "esc", "del": "delete", "page_up": "pageup", "page_down": "pagedown",
        "control": "ctrl", "option": "alt", "cmd": "super", "command": "super", "meta": "super", "win": "super",
    }
    _WHEEL = {"up": ("wheel", 1), "down": ("wheel", -1), "left": ("hwheel", -1), "right": ("hwheel", 1)}
    _SETTLE = 0.05
    """Seconds between actions: `dotool` does not say when the compositor has one."""

    def __init__(self) -> None:
        for tool in ("spectacle", "dotool"):
            if shutil.which(tool) is None:
                sys.exit(f"computerd: {tool} is not installed")
        self._shot = Path(tempfile.gettempdir()) / f"computerd-{os.getpid()}.png"
        self._size: tuple[int, int] | None = None
        self._dotool: subprocess.Popen[str] | None = None

    def _send(self, *lines: str) -> None:
        if self._dotool is None or self._dotool.poll() is not None:
            self._dotool = subprocess.Popen(["dotool"], stdin=subprocess.PIPE, text=True)
            time.sleep(1.0)
        assert self._dotool.stdin is not None
        try:
            for line in lines:
                self._dotool.stdin.write(line + "\n")
                self._dotool.stdin.flush()
                time.sleep(self._SETTLE)
        except BrokenPipeError as exc:
            raise Refused("dotool stopped; check that this user may write to /dev/uinput") from exc

    def _to(self, x: int, y: int) -> str:
        if self._size is None:
            self.screenshot()
        assert self._size is not None
        width, height = self._size
        return f"mouseto {min((x + 0.5) / width, 1.0):.6f} {min((y + 0.5) / height, 1.0):.6f}"

    def screenshot(self) -> tuple[bytes, int, int]:
        subprocess.run(
            ["spectacle", "--background", "--nonotify", "--fullscreen", "--pointer", "--output", str(self._shot)],
            check=True,
            timeout=30,
            capture_output=True,
        )
        data = self._shot.read_bytes()
        width, height = png_size(data)
        self._size = (width, height)
        return data, width, height

    def click(self, x: int, y: int, button: str, count: int) -> None:
        self._send(self._to(x, y), *[f"click {button}"] * count)

    def move(self, x: int, y: int) -> None:
        self._send(self._to(x, y))

    def drag(self, x: int, y: int, to_x: int, to_y: int) -> None:
        self._send(self._to(x, y), "buttondown left", self._to(to_x, to_y), "buttonup left")

    def scroll(self, x: int, y: int, direction: str, amount: int) -> None:
        axis, sign = self._WHEEL[direction]
        self._send(self._to(x, y), f"{axis} {sign * amount}")

    def type_text(self, text: str) -> None:
        # `dotool` reads one command a line, so a newline in the text is a key press.
        commands: list[str] = []
        for index, line in enumerate(text.split("\n")):
            if index:
                commands.append("key enter")
            if line:
                commands.append(f"type {line}")
        self._send(*commands)

    def key(self, chord: str) -> None:
        self._send("key " + "+".join(self._KEYS.get(part, part) for part in split_chord(chord)))


class MacDriver:
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
        self._shot = Path(tempfile.gettempdir()) / f"computerd-{os.getpid()}.png"
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
        subprocess.run(["screencapture", "-x", "-m", "-C", "-t", "png", str(self._shot)], check=True, timeout=30)
        width, height = self._bounds()
        return self._shot.read_bytes(), width, height

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

        def _json(self, status: HTTPStatus, body: dict[str, Any]) -> None:
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
            if self.path != "/screenshot":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            if not self._authorized():
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
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)[:200], "done": done})
                return
            self._json(HTTPStatus.OK, {"ok": True, "done": done})

    return Handler


def main() -> None:
    token = os.environ.get("COMPUTERD_TOKEN", "")
    if len(token) < 16:
        sys.exit("computerd: set COMPUTERD_TOKEN to at least 16 characters (AgenticOS's COMPUTER_DAEMON_TOKEN)")
    host = os.environ.get("COMPUTERD_HOST", "127.0.0.1")
    port = int(os.environ.get("COMPUTERD_PORT", "8765"))
    driver: Driver
    if platform.system() == "Darwin":
        driver = MacDriver()
    elif os.environ.get("WAYLAND_DISPLAY"):
        driver = KdeWaylandDriver()
    else:
        driver = X11Driver()
    server = ThreadingHTTPServer((host, port), make_handler(driver, token))
    print(f"computerd: {driver.name} desktop on http://{host}:{port}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
