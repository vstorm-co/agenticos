"""The applications a Linux desktop's menu shows, and opening one of them.

One implementation for every Linux desktop computer use drives. A sandbox runs
this file's source with `python3 -c`, and the computerd image copies it in
beside the daemon. So it is the standard library only, and it runs as the
desktop's own account, which is whose menu it reads.

Run as a script: `list` prints the applications as JSON, and `launch <app>`
opens the one with that name or id and waits for its window. A refusal is a
sentence on stderr and exit 1.
"""

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

OPEN_SECONDS = 10
"""How long `exo-open` may take to start the application.

Together with `WINDOW_SECONDS` a launch stays inside the 30 seconds the backend
waits for computerd's answer.
"""

WINDOW_SECONDS = 10.0
"""How long `launch` waits for the application's window before returning anyway.

Some applications never show one (a tray icon), or bring an existing window to
the front, and the screenshot after the action shows what happened.
"""


class AppError(Exception):
    """An application that cannot be found or opened; the text is for the model."""


@dataclass(frozen=True)
class App:
    """One entry the menu shows."""

    id: str
    """The desktop entry's file name without `.desktop`: `org.mozilla.firefox`."""
    name: str
    """What the menu calls it: the name in the desktop's language, else the untranslated one."""
    path: str


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


def _main_group(text: str) -> dict[str, str]:
    """The `[Desktop Entry]` group's keys; an action's own `Name` is in another group."""
    keys: dict[str, str] = {}
    main = False
    for line in text.splitlines():
        if line.startswith("["):
            main = line.strip() == "[Desktop Entry]"
        elif main:
            key, sep, value = line.partition("=")
            if sep:
                keys.setdefault(key.strip(), value.strip())
    return keys


def installed(env: dict[str, str]) -> list[App]:
    """Every application the menu shows, by name.

    The XDG search path, the user's own directory first: an entry there shadows
    a system one with the same id even when it is hidden, which is how a user
    hides a system application.
    """
    home = env.get("XDG_DATA_HOME") or f"{env.get('HOME', '')}/.local/share"
    system = env.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    order = _locale_keys(env.get("LC_ALL") or env.get("LC_MESSAGES") or env.get("LANG", ""))
    apps: dict[str, App | None] = {}
    for directory in [home, *system.split(":")]:
        for path in sorted(Path(directory, "applications").glob("*.desktop")):
            if path.stem in apps:
                continue
            try:
                keys = _main_group(path.read_text(errors="replace"))
            except OSError:
                continue
            default = keys.get("Name", "")
            if not default or "true" in (keys.get("NoDisplay"), keys.get("Hidden")):
                apps[path.stem] = None
                continue
            name = next((keys[f"Name[{k}]"] for k in order if keys.get(f"Name[{k}]")), default)
            apps[path.stem] = App(id=path.stem, name=name, path=str(path))
    return sorted((app for app in apps.values() if app), key=lambda app: app.name.casefold())


def find(query: str, apps: list[App]) -> App:
    """The application a `launch` names: its id, else its name, exactly, ignoring case.

    The id first, because ids are unique and names are not: the ambiguity
    refusal points at the ids, and one of them may be another entry's name.

    Raises:
        AppError: Nothing has that name or id, or several share the name.
    """
    wanted = query.casefold()
    found = [app for app in apps if app.id.casefold() == wanted] or [
        app for app in apps if app.name.casefold() == wanted
    ]
    if len(found) == 1:
        return found[0]
    if found:
        ids = ", ".join(app.id for app in found)
        raise AppError(
            f"'{query}' is the name of {len(found)} applications. Launch one by its id: {ids}."
        )
    raise AppError(
        f"No application is called '{query}'. Call computer_apps for the installed ones."
    )


def _screen() -> tuple[set[str], str]:
    """The visible windows' ids, and which one has the focus."""

    def xdotool(*args: str) -> str:
        return subprocess.run(
            ["xdotool", *args], capture_output=True, text=True, timeout=10, check=False
        ).stdout

    windows = xdotool("search", "--onlyvisible", "--name", "")
    return set(windows.split()), xdotool("getactivewindow").strip()


def launch(app: App) -> None:
    """Open an application, and return once a new window shows, the focus moves or `WINDOW_SECONDS` pass.

    `exo-open` runs the entry as the menu would. It gets a session of its own
    and no pipes: the application inherits both, and a pipe it held open would
    hold this command open until the application quit.

    Raises:
        AppError: `exo-open` failed or did not return.
    """
    windows, focus = _screen()
    try:
        code = subprocess.run(
            ["exo-open", app.path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            timeout=OPEN_SECONDS,
            check=False,
        ).returncode
    except subprocess.TimeoutExpired as exc:
        raise AppError(f"{app.name} did not open within {OPEN_SECONDS} seconds.") from exc
    if code != 0:
        raise AppError(f"{app.name} could not be opened (exo-open exit {code}).")
    deadline = time.monotonic() + WINDOW_SECONDS
    while time.monotonic() < deadline:
        now, active = _screen()
        if now - windows or active != focus:
            return
        time.sleep(0.2)


def main(argv: list[str], env: dict[str, str]) -> int:
    """`list`, or `launch <app>`; what the sandbox and computerd's launcher run."""
    try:
        match argv:
            case ["list"]:
                print(json.dumps([asdict(app) for app in installed(env)]))
                return 0
            case ["launch", query]:
                launch(find(query, installed(env)))
                return 0
    except AppError as exc:
        print(exc, file=sys.stderr)
        return 1
    print("Expected 'list' or 'launch <app>'.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], dict(os.environ)))
