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

Without a saved preference, the desktop starts with **System** theme and **Glass**
look. An explicit saved theme or look takes precedence.

In **Chat controls → Computer use**, select **Local computer** to give this conversation screenshot, mouse and keyboard tools even when the agent has no Computer use binding. The choice is independent of Browser and Work on: it does not grant a folder or command access, and the published agent stays unchanged. The initiating person must have their own paired device connected; native screen consent and operating-system permissions still apply.

## Running it

Before choosing a local installation or connecting to a server, the first-run wizard
offers optional Screen Recording and Accessibility permissions on macOS. Each button
opens the relevant system settings; setup never captures the screen or controls the
computer. Continue works without either permission. Returning from System Settings
refreshes their status; macOS may require an app restart. Microphone and folder access
remain requested when those features are used.

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

**Change server…** is in the account dropdown at the foot of the console
sidebar. Open your account name or the avatar on a collapsed sidebar, then
choose it to open the connection form. It remains available when blobby is hidden.

### Docker and multiple local instances

Creating an instance opens a dedicated step with grouped workspace, owner and
provider fields. **Cancel** returns to the instance list. Blobby stays hidden
during setup and returns with the console, following its saved visibility setting.

On macOS, **Download Docker Desktop** downloads the official installer for Apple
silicon or Intel, shows progress and opens the disk image. Finish installation
in the system window, then choose **Open Docker Desktop** and **Check again**.
The app also finds Docker's per-user CLI installation. Other operating systems
open Docker's download page. No installation starts from a status check alone.

Choose **New instance**, name it and enter its organization and owner. The app
assigns free loopback ports and creates a separate Compose project with its own
database, media volume, network, workspace directory and deployment keys. Local
session cookies have an instance namespace so switching installations does not
replace another one's login. The frontend images must include this support;
setup refuses an older image before creating the owner or opening a session.

The local screen lists saved instances, their addresses and whether they are
running. **Start and connect** starts the selected instance; **Finish setup**
retries an interrupted installation using its existing files and keys. The menu
bar's Start, Stop and Update act on the connected managed instance. Connecting
to an externally started development stack does not make it managed by the app.

Metadata lives in `local-instances.json` in the configuration directory; new
instance files are under `local-stacks/<id>/` in the app's data directory. Existing
`local-stack/` installations keep their original Compose project and data.
Passwords and provider keys are passed to bootstrap without storing them in
these files or putting them on the Docker command line. Deployment keys stay
in the instance's private `.env`; provider keys are stored by the server's vault.
The native setup controls use a neutral keyboard focus indicator and do not
focus choice buttons automatically.

## Connection setup and app readiness

The account menu also opens **App readiness** directly, including from Desktop settings. The checklist replaces the floating setup counter so it never covers page controls.

The connection review is centered on the native glass material, even when the
console uses an opaque saved look. Its status rows stay mounted while checking.
Connecting and Continue show progress immediately; the dashboard is prefetched
while you review setup. Entry motion respects Reduce Motion.

Connecting to a server opens **App readiness**, including for an existing account.
It checks sign-in, the computer connection, an available published agent, the
assistant model, shortcuts and macOS permissions. Permissions are requested only
when you choose **Enable**. You can continue with optional items unfinished and
return from **Settings → Desktop app** or the native **Activity & Access** menu.
The console remembers a dismissed review per account, organization and server;
an explicit new connection offers a fresh review. Status errors remain visible
and can be retried. Returning from System Settings refreshes the permission checks.

Screenshot and screen-control failures point to Screen Recording or Accessibility;
microphone failures in Quick Ask link to the same readiness screen. After granting
Screen Recording, the screenshot repair offers the interactive region picker again.
macOS may require restarting the app before a changed grant takes effect.

**Settings → Desktop app → Notifications** controls completed runs, failures,
approvals, questions and other updates. Previews are hidden by default; private
approval notifications open the app to review the request rather than offering a
blind approval. Chat settings can mute notifications for that conversation.
A notification is suppressed while its conversation is focused in the console
or Quick Ask. OS notification permissions and Focus settings still control delivery.

**Activity & Access** lists active work and requests needing attention. Open an
entry to continue in the console; **Stop** is available when this app holds the
conversation's originating connection. Other server runs remain accessible through
**Open**. The menu also revokes individual folder or whole-computer grants and
returns screen control to you.

The header offers **New chat** (`⌘N` or `Ctrl+N`), **Continue in the console** and
**Close**. New chat clears the previous conversation selection and draft context;
the composer stays below the transcript with a visible send button.

Quick Ask supports `@mention` with the same available resources as the chat composer.
Use arrow keys and Enter or Tab to select; Escape dismisses the suggestions first.
Deleting a mention removes its resource binding from the next message.

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

Chat fills the content area from the top, without the reserved drag row or page
padding. Drag the window from the chat-list header; its buttons remain clickable.

**Appearance** in the account menu offers both the light/dark mode and Standard,
Glass, Graphite, Midnight and Paper, with previews. The trigger names the current
style. These are the same choices as **Settings → Profile → Appearance**; changing
a style keeps the color mode and survives restarting the app.

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

Quick Ask keeps the full transcript: your questions, earlier answers, streamed tool
activity and results use the console’s message renderer. Approval requests, follow-up
questions and connection requests can be handled in the panel. Queued offline text
stays visible and the stop button stops the run. Attachments and cited sources open
in the panel; scrolling up pauses automatic following until you return to the bottom.

Use the paperclip to select files, paste an image from the clipboard, or drop files
onto Quick Ask. Attachments appear before sending and can be removed individually.
The deployment's chat upload limit applies here too. Sending and starting a new chat
wait for uploads to finish; a failed upload keeps your draft. You can send a file
without adding text.

The pin button keeps Quick Ask above other applications when you click elsewhere.
Unpin it to restore automatic dismissal on loss of focus. The close button, Escape
in the composer and the Quick Ask shortcut can still hide a pinned panel. The pin
lasts for the current desktop session, including page reloads.

## Work on this computer

The one thing a browser cannot do: a desktop chat can work in a
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

| Mode                | What the agent may do                              | How it is held to it                                                                                                    |
| ------------------- | -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Read only           | Read files; nothing is written and no command runs | The app refuses writes and commands                                                                                     |
| Write in the folder | Read, write inside the folder, run commands        | Commands run under Seatbelt on macOS and bubblewrap on Linux, writable only in the folder and the temporary directories |
| Full access         | Commands run as you, unsandboxed                   | Every command is shown in a native dialog to allow first                                                                |

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

In the Builder, **Sandbox → Computer** stores `backend: local` with no path or
native consent. Each person approves their own target in desktop chat. Without a
selection, the run asks for it instead of opening a cloud sandbox. When creating a
project, **Project sandbox → Computer · your files** opens the personal folder
selector; other members keep the project’s shared workspace.

**Whole computer.** Desktop chat also offers **Whole computer** without a folder
picker. One native warning grants access for this conversation: file tools can reach
absolute paths anywhere your account can access and commands run as you, without
individual native prompts. Operating system permissions and the agent's approval
rules still apply. **Revoke whole-computer access** or choosing **Cloud** blocks new
operations; commands already running are not interrupted. Consent survives app
restarts, is scoped to this server and conversation, and a draft binds on its first
operation. A new chat needs its own consent. This mode does not crawl the home
directory or automatically collect files as attachments.

Local browser and file tools are available in desktop chat even when the agent has
no Browser or Sandbox binding. Selection adds the binding only to this run, keeps
existing domain restrictions and approval rules, and does not change the published
agent. Internal attachment snapshots use file listings rather than running a shell.

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

The desktop main window reserves its drag strip separately from a compact 16px content inset. On macOS the window controls have a 32px reserved row, keeping the sidebar brand and page heading aligned without the browser layout’s extra top gap.

The console, Blobby and Quick Ask share a named persistent WebView profile; private
agent browser tabs remain isolated. Moving from an older profile may require one sign-
in. In Glass, the drag strip uses the content background. The dashboard scrollport
smooths keyboard navigation and discrete mouse-wheel steps while leaving fine trackpad
input native; reduced motion disables the smoothing.

The console keeps its session in persistent HttpOnly cookies, including a refresh cookie
renewed as the session is used. Reopening the app restores that session while it remains
valid. A temporary server failure or rate limit keeps the desktop account and retries
its session check when the connection returns or the window regains focus. A rejected or
revoked token still requires sign-in. If no account is available locally, an unavailable
server shows a retry instead of sending you to sign in.

The one navigation the console window refuses. Everything else loads in the
window; a click on **Continue with Google** opens in your own browser instead,
and the result comes back to the app (#1532).

What happens, in order:

1. The console's own `/api/oauth/<provider>/login` runs **in the window**, where
   it can read the httpOnly cookie holding a staged invitation and attach it.
2. The window then sees a navigation to the _deployment's_
   `/api/v1/oauth/<provider>/login`, hands it to the system browser with
   `client=desktop` and a freshly minted `desktop_nonce` appended, and does not
   follow it.
3. You sign in there, in a real browser with your own passwords, your own
   extensions and whatever second factor you use.
4. The deployment's callback sees that this attempt was a desktop one - recorded
   in the session at the _start_ under that attempt's OAuth `state`, never read
   off the return - and redirects to `agenticos://auth/callback?code=…` with a
   single-use code that expires in a minute, plus the nonce it was given.
5. The operating system hands that link to the app. The shell sends the console
   window to `<your server>/auth/callback?code=…`, which swaps the code for the
   token pair server-to-server; the window's own cookies are set.

**A deep link is something any process on your machine can fire**, so what one is
allowed to do here is narrow: send the console to one path, on the server _you_
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

- **No standing access.** Linking the computer grants nothing on its own: a run
  reaches only approved folders or a separately approved whole-computer conversation, and the screen only
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

After pairing the desktop app, select **Browser → Local browser** to override
the agent's browser for this conversation. This choice is independent of **Work on**:
it needs no folder grant or Sandbox capability and keeps the agent's cloud sandbox.
Local models and MCP services require an approved folder or whole-computer target;
the run receives its own Sandbox binding.
Phone apps do not invoke desktop commands.

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

**Local browser** uses a native page inside the console's browser panel after
consent on the paired computer. Clicking, scrolling and typing happen locally;
the page does not travel as screenshots. Its private session does not import
personal browser tabs or passwords. Page text still reaches the agent's model.
Manual input takes control from the agent; **Return to agent** gives it back.

On a wide chat, the browser opens beside the conversation, for both local and
remote browsing. Drag the divider or use its arrow keys to change the width.
**Maximize** uses the full screen; **Back beside the chat** restores the panel.
Narrow chat areas and phones use the full screen automatically.

A native tab belongs to this computer, organization, person, agent and
conversation. It stays open between runs; `browser_read` resumes it. Only one run
may lease it at a time. The run renews its lease automatically; if its backend
stops, the lease becomes available again after two minutes. **Close tab** destroys it; closing the panel only hides
it. Disconnecting the paired device closes all its tabs. At most eight tabs are
kept, and tabs idle for two hours may be evicted when another is opened.

Disable **Use the native local browser** in the browser capability to choose
Chromium compatibility. Tasks using vision or language/time-zone overrides also
use the existing isolated
Chromium window instead. Install Chrome, Chromium, Edge or Brave for that path;
its temporary profile closes with the run. Native DOM actions use scripted
input, which some sites distinguish from Chromium's trusted CDP input. Native
pages expose no console or file commands: their only shell permission is a
one-way notification that the person took control. A binding with
`connection: local` still requires the local browser selection.

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
