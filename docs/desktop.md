# The desktop app

AgenticOS runs in a browser, and that is how most people use it. The desktop app is
for whoever wants more of it on their own computer: the console in a window of its
own, a quick ask from anywhere, blobby on the desktop, and - the part a browser
cannot do - the person's own agents working in a folder on this computer and on its
screen. Nothing about the platform needs it.

> **Screenshot pending — the desktop app, blobby and quick ask.**

The application inside the window is the same Next.js console the server already
serves, loaded from the server, so it carries the same sign-in, the same
permissions and the same tenant checks a browser tab would. It is a
[Tauri](https://tauri.app) shell in `desktop/`.

!!! note "It is a shell, not a build of the frontend"

    `frontend/` is a Next.js application with a server half - route handlers
    proxying to the backend, session cookies they set, middleware picking the
    locale, and pages rendered on the server. None of that runs inside a desktop
    binary, so the shell does not try: it opens the deployment's URL the way a
    browser would. A deployment is what you install; the app is how you open it.

## Running it

Rust from [rustup](https://rustup.rs) and the platform's webview - WebKit on macOS,
WebView2 on Windows, WebKitGTK on Linux - are the prerequisites; Tauri's own
[prerequisites page](https://v2.tauri.app/start/prerequisites/) has the per-platform
list. The Tauri CLI is pinned in `desktop/package.json`, and `make install` fetches it
with everything else.

```bash
make desktop-dev     # opens the shell
make desktop-build   # a .app / .dmg, .msi or .deb/.AppImage for this machine
make desktop-check   # rustfmt, clippy with warnings denied, and the tests
```

The first launch asks where AgenticOS is:

- **On this computer.** The app checks for Docker, sets up the published images
  with the console and the API on loopback only, creates your organization and its
  owner, and from then on starts, stops and updates that stack from the menu bar.
- **On your organization's server.** Type its address; a bare host
  (`agenticos.acme.com`) is opened over HTTPS. You sign in through your own
  browser (see [Signing in](#signing-in)).

!!! warning "Plain `http://` is for this machine only"

    `localhost`, `127.0.0.1` and `::1` may be reached in the clear; any other host
    is refused until it is `https://`. The console posts the password and gets the
    token back on that connection, and a LAN is exactly where somebody else can
    read it.

An address nothing answers on is refused too: the shell opens a TCP connection
before it points the webview anywhere, because WebKit paints a refused connection
as a blank white window.

The settings live in `server.json` in the platform's configuration directory for
the app - `~/Library/Application Support/co.vstorm.agenticos/` on macOS,
`%APPDATA%\\co.vstorm.agenticos\\` on Windows, `~/.config/co.vstorm.agenticos/` on
Linux. A file that no longer parses is set aside as `server.json.invalid` and a
fresh one is written. The server is changed under **Settings…** (`⌘,`), from the
tray menu, or by launching with `--server <address>`.

**Change server…** is also a permanent button above your account in the console
sidebar. It opens the connection form directly; a collapsed sidebar shows its
server icon. You can change the address without using blobby.

## An application, not a tab

On macOS the console's sidebar holds the traffic lights and drags the window, the
window remembers its size and place, and closing it keeps the app in the menu bar.
The menu bar has File, Edit, View, Go (`⌘1`-`⌘5`, `⌘[` and `⌘]`) and Window; a tray
menu does the same on Windows and Linux. Native notifications carry Approve and
Reject for a waiting approval, and the Dock or taskbar shows how many are waiting.
**Settings → Desktop app** opens the app at login, keeps it running with the window
closed, and turns the badge on or off.

The top of the content has a reserved window-drag row outside its scroll area,
so page actions and panel close buttons stay clickable. The web Architect launcher
stays tucked into the desktop console's right edge and slides out on hover,
leaving the corner free for card actions and native Blobby.

**Pinned agents**: an agent's page offers Pin to Dock (Pin to taskbar elsewhere).
A pinned agent is in the Dock's menu and the tray menu, one click from a new chat
with it. A file dropped on the Dock icon, or on blobby, starts a chat with that
file attached.

## Blobby

A creature in the agents' avatar style that sits on the desktop while the console
is open, minimised or closed: one of a cast of six, the face of one of your agents,
or a face of your own. It says when an approval is waiting, something new is in
your inbox or your runs are in progress, and opens it on a click. Drag it anywhere;
pinch it, scroll over it with `⌘` held or use the slider in Settings to resize it.
Its own tab in Settings picks the character, how chatty it is and whether it shows
activity at all.

Its window is transparent, which on macOS needs `macOSPrivateApi` in
`tauri.conf.json` - and that rules out the Mac App Store, not a place a self-hosted
console was going.

## Quick ask and voice

**Open AgenticOS** (`⌘⇧O` on macOS, `Ctrl+Shift+O` elsewhere) brings the console
forward from any app. Change or clear it in **Settings → Shortcuts**. The menu bar,
tray and Blobby menus show the active shortcuts for opening AgenticOS, Quick Ask
and Screenshot to New Chat, and update when a binding changes. A shortcut that
could not be registered is not advertised in the menu.

**Quick ask** (`⌥Space`, rebindable) opens a floating panel to ask any agent from
anywhere, without bringing the console forward. On macOS it can carry what you
were looking at: the text selected in another app, the clipboard, or the files
selected in Finder, each shown before it is sent and only once you allowed
AgenticOS to read the selection.

Hold `⌥⇧Space` to dictate into quick ask; a voice call with the default agent has
a shortcut of its own. **Settings → Shortcuts** rebinds them all: a combination
needs at least one modifier, one another application already holds is refused with
the old binding kept, and **Clear** switches it off.

**Screenshot to a new chat** (`⌘⇧A`) shows the system's crosshair; the region you
pick lands in a fresh chat, already attached. The first press asks macOS for
Screen Recording, which takes effect after a restart.

## Work on this computer

The one thing a browser cannot do: a chat whose agent has a sandbox can work in a
folder on the computer the app runs on instead of in the cloud. The agent's file
and shell tools - list, read, write, edit, run - reach that folder through the app.

**Link the computer once.** In the chat settings, choose **Work on → This computer**
to link it directly. Confirm in the native dialog, then choose a folder and its
access mode in the same panel. **Settings → Desktop app → This computer → Let
agents work here** offers the same linking action. The app gets its own session
for this computer and keeps its refresh token in the system keychain. It holds one
outbound WebSocket to the server's device hub (`/api/v1/ws/device`); nothing listens
on the computer. **Unlink** ends that session.

**Choose it per chat.** In the desktop app the chat's settings offer **Work on:
Cloud / This computer**. Choosing this computer asks for a folder in the native
picker and how far the agent may go in it:

This computer becomes selected only after you approve a folder. The access
selector shows that folder's approved mode; changing it opens the native folder
picker again to confirm the new permission. Cancelling keeps the previous choice.
The folder and mode stay selected when settings close and when a new chat gets its ID.

| Mode | What the agent may do | How it is held to it |
|---|---|---|
| Read only | Read files; nothing is written and no command runs | The app refuses writes and commands |
| Write in the folder | Read, write inside the folder, run commands | Commands run under Seatbelt on macOS and bubblewrap on Linux, writable only in the folder and the temporary directories |
| Full access | Commands run as you, unsandboxed | Every command is shown in a native dialog to allow first |

Windows offers read only and full access. Linux offers writing in the folder only
when `bwrap` is installed.

**The computer decides, not the server.** The folders you picked, with their modes,
are kept in the app's settings, and every operation names a folder and a mode that
the app checks against them: a folder you never picked, a mode wider than you
allowed, or a path that climbs out of the folder is refused on the computer,
whatever the server asked. The choice is remembered per conversation, and a new
chat starts in the cloud.

**Only your own runs.** A chat reaches your computer only when it is your own -
never an API key, a widget visitor or someone else's chat - and a
[trigger](triggers.md) only when it acts as its creator, who points it at a folder
of their computer under the trigger's **Work on**.

**When the computer is away.** A run that asked for this computer and finds the app
not connected waits up to ten minutes for it, and the chat says so. An operation
that finds the app gone mid-run - a closed lid, a changed network - waits up to five
minutes for it to come back on the same session, then carries on. While a run's
operation is in flight, the tray says an agent is working on this computer.

The server checks the sign-in before forwarding each local operation. Revoked or expired sessions refuse new work; the heartbeat also closes idle connections. Operations already in progress are cancelled when the desktop socket closes.

## The screen

[Computer use](reference/capabilities.md) can drive this computer's own screen. In
a chat working on this computer, its `auto` desktop - the default - is this screen;
`local` asks for nothing else.

- **Asked first.** The first screenshot of a session asks, in a native dialog,
  whether the agent may see and control this screen, for an hour.
- **Framed while it acts.** An outline frames the screen while the agent holds it.
- **Stoppable at once.** `⌘⌥Esc` (`Ctrl+Alt+Esc` elsewhere) takes the screen back;
  the next action is refused until you allow it again.
- **The operating system asks too.** macOS needs AgenticOS under Privacy & Security
  in both Screen Recording and Accessibility; a refusal names them.

Every desktop a run works, this one included, is shown live in the chat and on the
run's live view, where **Take over** hands it to you between the agent's steps and
**Give back** returns it. The live view of this computer's screen is yours alone,
whoever else may watch runs.

## Signing in

The one navigation the console window refuses. Everything else loads in the
window; a click on **Continue with Google** opens in your own browser instead,
and the result comes back to the app (#1532).

What happens, in order:

1. The console's own `/api/oauth/<provider>/login` runs **in the window**, where
   it can read the httpOnly cookie holding a staged invitation and attach it.
2. The window then sees a navigation to the *deployment's*
   `/api/v1/oauth/<provider>/login`, hands it to the system browser with
   `client=desktop` and a freshly minted `desktop_nonce` appended, and does not
   follow it.
3. You sign in there, in a real browser with your own passwords, your own
   extensions and whatever second factor you use.
4. The deployment's callback sees that this attempt was a desktop one - recorded
   in the session at the *start* under that attempt's OAuth `state`, never read
   off the return - and redirects to `agenticos://auth/callback?code=…` with a
   single-use code that expires in a minute, plus the nonce it was given.
5. The operating system hands that link to the app. The shell sends the console
   window to `<your server>/auth/callback?code=…`, which swaps the code for the
   token pair server-to-server; the window's own cookies are set.

**A deep link is something any process on your machine can fire**, so what one is
allowed to do here is narrow: send the console to one path, on the server *you*
configured, carrying a code that redeems exactly once - and only one carrying the
nonce this app minted for this attempt. On Windows and Linux a single-instance lock
hands a second launch's arguments to the first. The deployment has to agree about
the scheme - `DESKTOP_DEEP_LINK_SCHEME`, `agenticos` unless somebody changed it -
and about its own public address.

## What it deliberately does not do

- **No navigation guard.** A link that leaves the server's origin opens inside the
  window, because an OAuth flow - connecting an MCP server - has to come back to
  the same webview for its cookie to land. The window's title names any other host
  it shows.
- **No local run without a sandbox.** Working on this computer replaces where an
  agent's sandbox tools run; an agent with no sandbox has no such tools to move.
- **No standing access.** Linking the computer grants nothing on its own: a run
  reaches only the folders you picked, in the modes you picked, and the screen only
  after you allow it.

## Where it sits in the tree

- `desktop/ui/` - the first-run pages and the screen outline, static files.
- `desktop/core/` - the parts both sides must agree on, free of the runtime: the
  device frames, the endpoints and the back-off, tested on their own.
- `desktop/src-tauri/` - the shell: windows, menus, blobby, quick ask, the device
  link (`device.rs`), the local executor (`local_work.rs`) and the screen
  (`screen.rs`).
- `backend/app/services/device_hub/` - the server's half: presence in Redis, so any
  API host or worker reaches a computer, and `DeviceWorkspace`, the sandbox
  workspace carried out by the app.

## Local browser, models and MCP

After pairing the desktop app, approve a folder under **Work on**. The same picker
can use a local model, selected local MCP services, and a local browser for that
run. These options require an agent with a sandbox binding and your own paired
session. Phone apps do not invoke desktop commands.

Add services under **Settings → Desktop app → Local services**. A native dialog
confirms each grant. Models use an Ollama or OpenAI-compatible HTTP endpoint
(for example `http://127.0.0.1:11434/v1`) and an installed model ID. MCP uses an
already running Streamable HTTP server (for example `http://127.0.0.1:8000/mcp`).

Only loopback endpoints are accepted; redirects and embedded credentials are
refused. The desktop stores the address and the API sends an opaque grant ID.
Requests and responses are limited to 8 MiB, with a two-minute service deadline.
MCP servers must accept requests without a token and return finite HTTP responses;
standalone SSE subscriptions and starting stdio processes are not supported.
Remove a grant to refuse subsequent calls. The organization profile is kept for attribution without opening its cloud credential.
Local inference has no cloud fallback;
other capabilities configured with separate models retain their own settings.

**Local browser** routes the existing `browser_use` tools to a visible Chromium
window on the paired computer. Install Chrome, Chromium, Edge or Brave first.
Each browse asks for native consent, uses a temporary profile and closes it when
the browse ends or the device disconnects. Existing personal tabs and passwords
are not imported. The chat receives DOM observations and live preview frames;
saved sign-ins are not copied to the server. A capability configured with
`connection: local` refuses to run without this local selection.

## Installers and updates

The **Apps** GitHub Actions workflow checks native crates on macOS, Windows and
Linux and builds Android debug APKs and an iOS simulator app. Full native checks
run in CI. Local `make desktop-check` remains available for a focused change.
The **App release** workflow attaches installers, signed updater artifacts, an
Android APK and a Homebrew cask to an existing published stable `v1.MINOR.PATCH`
release whose commit is on `main`. It does not create a platform release. The cask
is a downloadable asset; publishing a Homebrew tap is a separate operator step.
The desktop menu's **Check for Updates…** requires a build with the updater public
key and verifies the downloaded signature before installation.

Configure the `apps-release` GitHub environment before running a release:

- Variable `AGENTICOS_UPDATER_PUBLIC_KEY`; secrets `TAURI_SIGNING_PRIVATE_KEY`
  and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (one persistent updater key pair).
- macOS: `APPLE_CERTIFICATE` (base64 P12), `APPLE_CERTIFICATE_PASSWORD`,
  `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD` (app-specific),
  and `APPLE_TEAM_ID` for Developer ID signing and notarization.
- Optional Windows Authenticode: `WINDOWS_CERTIFICATE_BASE64` (PFX) and
  `WINDOWS_CERTIFICATE_PASSWORD`. Without them the installer is unsigned.
- Android: `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`,
  `ANDROID_KEY_ALIAS` and `ANDROID_KEY_PASSWORD`. Keep the same keystore for updates.
- TestFlight: repository variable `AGENTICOS_TESTFLIGHT_ENABLED=true`; secrets
  `IOS_CERTIFICATE_BASE64`, `IOS_CERTIFICATE_PASSWORD`, `IOS_PROFILES_BASE64_JSON`
  (JSON array of base64 profiles for the app, widgets and share extension),
  `APP_STORE_CONNECT_KEY_P8`, `APP_STORE_CONNECT_KEY_ID`,
  `APP_STORE_CONNECT_ISSUER_ID` and `APPLE_TEAM_ID`. Create the app identifiers,
  shared App Group and App Store Connect app first. Existing APNs deployment
  credentials are still required for push notifications.

Store credentials stay in CI; release jobs delete temporary signing files.
TestFlight upload remains disabled until explicitly enabled. Store approval,
provisioning and signed-device delivery require the operator's accounts and
cannot be verified by an unsigned local build.


## Recap

- **The console stays on the server.** The shell opens it; nothing is bundled.
- **Native where it matters.** Menus, notifications, pinned agents, blobby, quick
  ask and voice from anywhere.
- **Your agents can work on this computer** - in folders you pick, in modes you
  pick, sandboxed by the operating system, and only for your own runs.
- **And on its screen**, asked first, framed while it acts and stopped with one
  shortcut.
