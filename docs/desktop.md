# The desktop app

AgenticOS runs in a browser, and that is how most people use it. The desktop app is
an add-on for whoever wants it on the dock: the console in a window of its own, plus
a pet and a screenshot shortcut. Nothing about the platform needs it.

<figure markdown>
  ![Amigo, the desktop pet, saying: No more caramba.](assets/desktop_no_more_caramba_pet.png){ width="270" }
  <figcaption>Amigo, one of five pets. No more caramba in your AI.</figcaption>
</figure>

The application inside the window is the same Next.js console the server already
serves, loaded from the server, so it carries the same sign-in, the same
permissions and the same tenant checks a browser tab would.

It is a [Tauri](https://tauri.app) shell in `desktop/`, and it holds exactly one
setting: the address of the server. The first launch asks for it, "Shell → Change
server…" asks again, and everything in between is the console.

!!! note "It is a shell, not a build of the frontend"

    `frontend/` is a Next.js application with a server half - ninety-odd route
    handlers proxying to the backend, session cookies they set, middleware picking
    the locale, and pages rendered on the server. None of that runs inside a
    desktop binary, so the shell does not try: it opens the deployment's URL the way
    a browser would. A deployment is what you install; the app is how you open it.

## Running it

Rust from [rustup](https://rustup.rs) and the platform's webview - WebKit on macOS,
WebView2 on Windows, WebKitGTK on Linux - are the prerequisites; Tauri's own
[prerequisites page](https://v2.tauri.app/start/prerequisites/) has the per-platform
list. The Tauri CLI is pinned in `desktop/package.json`, and `make install` fetches it
with everything else.

```bash
make desktop-dev     # opens the shell; type the address of a console
make desktop-build   # a .app / .dmg, .msi or .deb/.AppImage for this machine
make desktop-check   # rustfmt, clippy with warnings denied, and the tests
```

The first time, the window shows a form asking where the server is, filled in with
`http://localhost:3000` - a `make dev` stack. A bare host (`agenticos.acme.com`) is
opened over HTTPS. Anything that is not a web address is refused on the form.

!!! warning "Plain `http://` is for this machine only"

    `localhost`, `127.0.0.1` and `::1` may be reached in the clear; any other host
    is refused until it is `https://`. The console posts the password and gets the
    token back on that connection, and a LAN is exactly where somebody else can
    read it.

An address nothing answers on is refused too: the shell opens a TCP connection
before it points the webview anywhere, because WebKit paints a refused connection
as a blank white window. The same probe runs on every launch, so a stack that is
down puts you back on the form with the reason rather than in front of an empty
window.

The answer is stored as `server.json` in the platform's configuration directory for
the app - `~/Library/Application Support/co.vstorm.agenticos/` on macOS,
`%APPDATA%\\co.vstorm.agenticos\\` on Windows, `~/.config/co.vstorm.agenticos/` on
Linux - and read again on every launch.

A file that no longer parses - a typo while editing it by hand - is set aside as
`server.json.invalid` at the next launch, and the connect form saves a fresh one.

A wrong address is fixed in four ways, whichever is nearest: **Settings…** (`⌘,`,
also on the tray icon and in the pet's right-click menu, so it is reachable even
when the window shows the wrong site), **Shell → Change server…**, editing that
file, or launching with `--server http://localhost:3000` from a terminal, which
also saves it.

## The pet

A small pixel-art creature in a transparent, always-on-top window of its own: it
sits on the desktop while the console is open, minimised or closed, the way
Codex's pets do. Drag it anywhere; click it and it waves; double-click it and it
hops and brings the console forward, reopening it if you had closed the window.
Left alone it idles, looks around, strolls a little way along the screen and turns
back at the edge, and now and then dozes.

Hover over it and a **+ New chat** button appears above its head; it puts the
console on a fresh conversation, opening the window if it was closed. Click it and
it says something, in a bubble, in its own voice. Stroke it - the cursor back and
forth over it a few times - and it closes its eyes and a heart comes up. While it
stands about, its eyes follow the cursor. After dark it dozes where it would have
strolled. Dropped after a drag, it lands with a little hop.

Right-click the pet for its menu: a new chat, the console, which pet it is, and
whether it is shown. The same menu is on the tray icon (the menu bar extra on
macOS) and under **Pet** in the menu bar, and all three are one set of items, so a
checkmark changed in one is changed in the others.

**Show pet** (Cmd/Ctrl+Shift+P) tucks it away and brings it back; the same menu
picks which pet it is - Orbit, a round one with an antenna; Boxy, a terminal
on legs; Ghost, which floats; Sprout, a seed with a leaf; Amigo, in a sombrero
and a moustache, for no more caramba in your AI. Where it was left,
whether it is shown and which pet it is are stored beside the server address, so
the pet is where you put it on the next launch. Under the operating system's
reduce-motion setting it stands still, and stays draggable.

The art is composed at runtime in `desktop/ui/pet-sprites.js`: each pet is one
body and a description of where its eyes, feet and arm go, and every animation is
a few lines of positions shared by all five rather than a sprite sheet per pet.
What each says is in `pet-lines.js`; the behaviour, and every rule about when a
stroke counts or where the eyes point, is in `pet-engine.js`, pure and tested.
Its own window is what makes it a pet rather than a widget, and what it costs:
`macOSPrivateApi` in `tauri.conf.json`, because a transparent window on macOS
needs it, which rules out the Mac App Store - not a place a self-hosted console
was going.

!!! note "It does not yet know what the agents are doing"

    Codex's pet carries a bubble that says a run is in progress or an approval is
    waiting. Ours cannot yet: the console is a remote page with no IPC into the
    shell, and giving it one means a capability with `remote` URLs plus a hook in
    the frontend that reports activity. That is the follow-up; the pet here is
    company, not a status light.

## Screenshot to a new chat

Press the shortcut - `⌘⇧A` by default, wherever you are - and the crosshair from
Cmd+Shift+4 appears. Pick a region and the console comes to the front on a fresh
chat with the picture already attached, ready for the question. Escape cancels.
The same action is in the pet's menu and on the tray icon.

**Settings…** (`⌘,`, under Shell, on the tray icon and in the pet's right-click
menu) rebinds it: click the field, hold the modifiers and press a key. A combination needs at least one modifier - a global shortcut on a bare letter
would swallow typing in every application - and one that another application
already holds is refused with the old binding kept. **Clear** switches it off.
Bindings are stored beside the server address. A binding that could not be taken
at launch, because another application got there first, is named on the same page
so it can be replaced rather than sit there looking bound.

!!! note "Two modifiers on their own cannot be a shortcut"

    Left-Command plus Right-Command is a chord, not a key: the operating system's
    hotkey registration, which is what the shell uses, needs a non-modifier key in
    the combination. Detecting a modifier-only chord means an accessibility event
    tap that watches every key press, and asking every user to grant that. Not this
    version.

The first press asks macOS whether AgenticOS may record the screen. Until it may,
nothing can be captured - the system's own tool exits quietly with no crosshair -
so the shell checks first, opens System Settings → Privacy & Security → Screen
Recording, and the pet says "Allow screen recording, then restart me." The grant
goes to the *responsible* application: the AgenticOS bundle once it is packaged,
but under `make desktop-dev` the terminal the binary was launched from, or the IDE
hosting it - which is the one to tick in that list. A grant takes effect
after a restart.

The picture reaches the composer the way a chosen file does: the shell runs a
script in the console page that hands the PNG to the composer's file input, so the
upload, the size limit and the preview are the console's own. It is handed only to
the chat page on the configured server's origin - never to another site the window
may have wandered to - and only within two minutes of the press; a capture that
went nowhere is dropped. Windows and Linux have no capture wired yet.

## What it deliberately does not do

- **No local execution.** The shell has no access to the machine beyond one JSON
  file. An agent running commands on the laptop it is opened from is a different
  feature with a different permission model - a third sandbox connection kind next
  to Docker and Daytona, bound to one person's machine rather than to the
  organization - and it is not this one.
- **No offline mode.** With the server unreachable the window shows the webview's
  own error page; "Shell → Reload" retries.
- **No navigation guard.** A link that leaves the server's origin opens inside the
  window rather than in the system browser, because an OAuth flow - signing in,
  connecting an MCP server - leaves the origin and has to come back to the same
  webview for its cookie to land. `⌘,` or "Shell → Change server…" is the way back
  if a page has no link home.
- **Sign-in stays in the window, and the window says it is Safari.** WebKit's
  bare user agent is what Google refuses as an embedded browser
  (`disallowed_useragent`); the console window carries Safari's version tokens on
  the same engine, so Google sign-in works. The handoff Google prefers - the
  system browser and a deep link back - needs a one-time exchange the backend does
  not have yet, and is [#1532](https://github.com/vstorm-co/agenticos/issues/1532).

## Where it sits in the tree

`desktop/ui/` is the connect form and the pet, static files with no build step;
`bun test` runs the pet's sprite and behaviour tests there. `desktop/src-tauri/` is
the Rust side: the commands the two pages call, the two windows, and the menu.
`desktop-check` is not part of `make lint` or `make check`: CI has no Rust toolchain
yet, and `tests/test_ci_parity.py` would refuse a `check` that ran a step CI does
not. Run it before pushing a change under `desktop/`.

## Recap

- **The console stays on the server.** The shell opens it; nothing is bundled.
- **One file of settings.** The server address, asked once, and where the pet was
  left, both changeable from the menu.
- **A screenshot is a shortcut away.** `⌘⇧A`, a region, a fresh chat with it
  attached; rebound under Settings (`⌘,`).
- **Nothing local yet.** Local execution is a sandbox connection kind to design,
  not a flag on this shell.
