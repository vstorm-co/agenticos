# The desktop app

The console in a window of its own: a dock icon, its own place in the app switcher,
and nothing else changed. The application inside the window is the same Next.js
console the server already serves, loaded from the server, so it carries the same
sign-in, the same permissions and the same tenant checks a browser tab would.

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
opened over HTTPS. Anything that is not a web address is refused on the form, and
so is an address nothing answers on: the shell opens a TCP connection before it
points the webview anywhere, because WebKit paints a refused connection as a blank
white window. The same probe runs on every launch, so a stack that is down puts you
back on the form with the reason rather than in front of an empty window.

The answer is stored as `server.json` in the platform's configuration directory for
the app - `~/Library/Application Support/co.vstorm.agenticos/` on macOS,
`%APPDATA%\\co.vstorm.agenticos\\` on Windows, `~/.config/co.vstorm.agenticos/` on
Linux - and read again on every launch. A wrong address is fixed from **Shell →
Change server…**, or by editing that file.

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

**Shell → Shortcuts…** rebinds it: click the field, hold the modifiers and press a
key. A combination needs at least one modifier - a global shortcut on a bare letter
would swallow typing in every application - and one that another application
already holds is refused with the old binding kept. **Clear** switches it off.
Bindings are stored beside the server address.

!!! note "Two modifiers on their own cannot be a shortcut"

    Left-Command plus Right-Command is a chord, not a key: the operating system's
    hotkey registration, which is what the shell uses, needs a non-modifier key in
    the combination. Detecting a modifier-only chord means an accessibility event
    tap that watches every key press, and asking every user to grant that. Not this
    version.

The first press asks macOS whether AgenticOS may record the screen; refused, the
capture comes back as the desktop picture rather than an error, so grant it in
System Settings → Privacy & Security → Screen Recording. The picture reaches the
composer the way a chosen file does: the shell runs a script in the console page
that hands the PNG to the composer's file input, so the upload, the size limit and
the preview are the console's own. Windows and Linux have no capture wired yet.

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
  webview for its cookie to land. "Shell → Change server…" is the way back if a
  page has no link home.

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
  attached; rebound under Shell → Shortcuts…
- **Nothing local yet.** Local execution is a sandbox connection kind to design,
  not a flag on this shell.
