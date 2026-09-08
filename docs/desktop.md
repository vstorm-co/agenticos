# The desktop app

The console in a window of its own: a dock icon, its own place in the app switcher,
and nothing else changed. The application inside the window is the same Next.js
console the server already serves, loaded from the server, so it carries the same
sign-in, the same permissions and the same tenant checks a browser tab would.

It is a [Tauri](https://tauri.app) shell in `desktop/`, and it holds exactly one
setting: the address of the server. The first launch asks for it, "Server → Change
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

The first time, the window shows a form asking where the server is. A bare host
(`agenticos.acme.com`) is opened over HTTPS; `http://localhost:3000` reaches a
`make dev` stack. Anything that is not a web address is refused on the form, never
handed to the webview.

The answer is stored as `server.json` in the platform's configuration directory for
the app (`~/Library/Application Support/co.vstorm.agenticos/` on macOS), and read
again on every launch.

## What it deliberately does not do

- **No local execution.** The shell has no access to the machine beyond one JSON
  file. An agent running commands on the laptop it is opened from is a different
  feature with a different permission model - a third sandbox connection kind next
  to Docker and Daytona, bound to one person's machine rather than to the
  organization - and it is not this one.
- **No offline mode.** With the server unreachable the window shows the webview's
  own error page; "Server → Reload" retries.
- **No navigation guard.** A link that leaves the server's origin opens inside the
  window rather than in the system browser, because an OAuth flow - signing in,
  connecting an MCP server - leaves the origin and has to come back to the same
  webview for its cookie to land. "Server → Change server…" is the way back if a
  page has no link home.

## Where it sits in the tree

`desktop/ui/` is the connect form, three static files with no build step.
`desktop/src-tauri/` is the Rust side: one command that reads the stored address,
one that validates and stores a new one and points the webview at it, and a menu.
`desktop-check` is not part of `make lint` or `make check`: CI has no Rust toolchain
yet, and `tests/test_ci_parity.py` would refuse a `check` that ran a step CI does
not. Run it before pushing a change under `desktop/`.

## Recap

- **The console stays on the server.** The shell opens it; nothing is bundled.
- **One setting, one file.** The server address, asked once, changeable from the
  menu.
- **Nothing local yet.** Local execution is a sandbox connection kind to design,
  not a flag on this shell.
