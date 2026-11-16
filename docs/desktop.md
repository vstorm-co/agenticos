# The desktop app

Native OAuth uses S256 PKCE. The app retains a private verifier; the callback carries only its public challenge. The verifier is sent in the exchange request body, never a URL. Signing out clears native phone notification previews.

Unlinking, signing out or changing servers clears approved folders, local services, whole-computer and screen consents. Pairing previews the account before consuming the single-use code. Shared routine folder permissions survive session expiry and re-pairing to the same verified account and server. They remain inactive until that identity is verified again; explicit unlinking, sign-out or changing server/account removes them.

A published delegate that needs this computer can ask through the same chat, even when its main agent runs in the cloud. Consent belongs to the main agent starting the run. Local coding delegates request full access; nested delegates use that approved device workspace without sharing it with unrelated cloud delegates. Cancelling or timing out a command terminates its descendant processes too.

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

Returning from System Settings refreshes readiness even when the webview stays visible. If Screen Recording is enabled but access is still denied, quit and reopen the running copy, then refresh. Permissions can differ between an installed build and an ad-hoc test copy.

Local ACP tasks stop after 16,384 inbound events or 8 MiB of cumulative serialized updates, including session replay. The error is explicit and the adapter is closed.

A committed publisher certificate pin requires the matching signing material: a missing MACOS_SELF_SIGNED_P12 stops the release. Ad-hoc release signing is available only with an unpinned distribution.

## Installing the app

Download the package for your computer from the [GitHub release](https://github.com/vstorm-co/agenticos/releases/latest). You do not need Rust or development tools to install a release.

- **macOS:** choose Apple silicon or Intel, open the `.dmg`, then drag AgenticOS to **Applications** along the arrow. Launch it from Applications and eject the disk image.
- **macOS without the warning:** `curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/install_macos.sh | bash` downloads the release, checks its SHA-256 against the one published with it, copies the app to Applications and clears the download flag from that one app. `brew install --cask vstorm-co/agenticos/agenticos` does the same through [the project's tap](https://github.com/vstorm-co/homebrew-agenticos). Releases are not notarized by Apple, so a `.dmg` downloaded in a browser still asks for **Open Anyway**. Once the project pins the certificate its releases are signed with (`scripts/macos_signing_identity.txt`), the script also refuses an app signed by any other.
- **Windows:** open the `setup.exe` installer. It follows your system language and installs for your user without requiring administrator rights. Open AgenticOS from the Start menu. An `.msi` package is also available for managed deployments.
- **Linux:** open the `.deb` or `.rpm` package in your distribution's software installer. For a portable installation, mark the `.AppImage` executable in its file properties and open it.

The first launch guides you through connecting to a server or creating a local instance. Docker is needed only for a local instance; the wizard detects it and offers a download when missing. Installation does not grant screen or microphone access.

[Why macOS shows this warning](howto/macos-warning.md).

### Desktop widgets on macOS

On macOS 14 or later, launch the installed app once, then right-click the desktop, choose **Edit Widgets** and search for **AgenticOS**. The small widget opens Quick Ask; the medium widget also opens Chat, Inbox and Activity. Widgets follow the system appearance and contain shortcuts only, with no account data. A widget click never starts recording or a call.

Release CI builds native packages for Mac (Apple silicon and Intel), Windows and Linux. macOS packages use the configured stable self-signed certificate, with ad-hoc signing only for an unpinned distribution. These builds are not notarized by Apple. After copying the app to Applications, try opening it once. If macOS blocks it because the developer cannot be verified, choose **System Settings → Privacy & Security → Open Anyway** and confirm. Managed computers may prohibit this exception. See [Apple’s instructions](https://support.apple.com/en-us/102445). Updater downloads still require a valid signature from the release updater key.

After an ad-hoc update, macOS may request microphone, Screen Recording, Accessibility or Keychain access again. If device pairing is lost, reconnect the device. Updater signatures verify the package but do not provide a stable Apple signing identity.

When the release workflow has a stable self-signed certificate (`scripts/create_macos_signing_cert.sh` makes one), macOS keeps the Screen Recording and Microphone grants across updates, because they are bound to the signing identity. Create it once and never replace it: a new certificate asks every user again. Self-signing does not remove the Gatekeeper warning; only Developer ID signing and notarization do.

## Running it

The first-run wizard starts with a language choice and whether to create a local
workspace or connect to your organization's server. Screen Recording,
Accessibility and Microphone are optional features offered through App readiness
or when used, rather than a required step before choosing a connection.

When connecting the desktop app, you can paste the original invitation link instead of only a server address. The app connects to that link’s server and opens the invitation, preserving its destination through sign-in. It does not accept the invitation automatically or store its token in native settings. Optional connection review waits until the invitation is finished.

The native start and console support English, Polish, German and Turkish. Your
native choice is carried to the console; an existing account's saved language
still takes precedence. Local setup asks for one workspace name; a separate
organization name is an advanced option. After connection review, **Get started**
opens the common first-task flow. A local workspace can still send material to
a remote AI provider; local installation alone does not mean offline AI.

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

Choose **Set up this computer** to prepare the local runtime. AgenticOS downloads
Docker Desktop 4.97.0 for your processor and verifies its pinned SHA-256 checksum.
macOS checks the installer with Gatekeeper, verifies Docker Inc's signing identity
and requests system authorization.
Windows runs the signed installer; missing WSL features are prepared with system
authorization. Restart Windows when requested and reopen AgenticOS to continue.
x86-64 Ubuntu, Debian and Fedora use their system package installer. Complete
Docker's own first-run terms.

On Linux, setup adds Docker's signed package source
when missing and requests administrator authorization for packages and KVM access.
Restart when requested. A status check alone never installs software.

Before installation, AgenticOS checks for 4 GB of free storage; the local stack
also requires at least 3 GB of memory visible to its engine. These are startup
checks, not workload sizing guarantees. Image downloads show progress and have a
30-minute limit. **Retry** continues the same instance with its existing keys.
Git, Python, uv and Node.js are not required on the host for ordinary app use.

New instances pin the platform version shipped with the app. Updating the desktop
app does not silently replace a running instance's version. **Update** downloads
the matching platform images, pauses writers and backs up the database, media and
deployment keys under the instance's private `backups/` directory before applying
the update. A failed backup blocks the update. Backups contain personal data and
must be protected. A failed migration is reported; database downgrades are not
automatic.

Opening AgenticOS restarts its saved managed local workspace automatically when
it is stopped, including its installed desktop runtime on supported systems. External servers and
unmanaged development stacks are not started. The app passes Docker's CLI and
credential-helper directories to child processes, including launches from Finder;
you do not need to edit Docker's credential configuration or shell profile.

Public product images use a private anonymous registry configuration, avoiding
credential-helper and keychain prompts. Your existing Docker configuration stays
unchanged. Local installation refuses contexts pointing at a remote engine.

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

A local instance runs the API, the worker, the console, the database and Redis,
and no sandbox service, browser service or object store. Agents get the
files-only workspace. In **Chat controls → Tools & files**, choose
**Work on → This computer** for folder access and **Browser → Local browser**
for browsing. **Computer use** grants screen, mouse and keyboard access separately.

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

Local file operations stay relative to an open handle for the approved directory. Replacing a directory or file with a symlink cannot redirect a write outside it. The grant itself and its parent directories are opened without following symlinks; previews and file lists use the same boundary.

The one thing a browser cannot do: a desktop chat can work in a
folder on the computer the app runs on instead of in the cloud. The agent's file
and shell tools - list, read, write, edit, run - reach that folder through the app.

**Link the computer once.** In the chat settings, choose **Work on → This computer**
to link it directly. Confirm in the native dialog, then choose a folder and its
access mode in the same panel. **Settings → Desktop app → This computer → Link
this computer** offers the same linking action. The app gets its own session
for this computer and keeps its refresh token in the system keychain. It holds one
outbound WebSocket to the server's device hub (`/api/v1/ws/device`); nothing listens
on the computer. **Unlink** ends that session; it asks first and lists what it
clears.

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

Folder commands can read the approved folder and system runtime files, but not
unrelated home-directory files or inherited application credentials. Tools that
need those files require separate whole-computer consent. Direct local file reads
and writes are limited to 10 MiB so oversized transfers cannot disconnect the device.
Larger writes are refused before encoding or sending any file bytes.

Windows offers read only and full access. Linux offers writing in the folder only
when `bwrap` with `--bind-fd` support is installed. The app holds a no-follow directory handle through sandbox startup, so renaming a folder or replacing it with a symbolic link cannot change the approved directory. On Linux, task environment variables are applied inside the sandbox rather than to its launcher; their values are passed through a private descriptor.

Routine folder roots must not contain symbolic links or junctions. Choose the actual folder in the picker; background admission never resolves links in the root path.

**The computer decides, not the server.** The folders you picked, with their modes,
are kept in the app's settings, and every operation names a folder and a mode that
the app checks against them: a folder you never picked, a mode wider than you
allowed, or a path that climbs out of the folder is refused on the computer,
whatever the server asked. The choice is remembered per conversation. New chats inherit the last folder
and tool preferences for this account and organization; project settings take
precedence. Whole-computer consent given in a chat is never inherited; consent
given to an agent holds for that agent (see **Whole computer**).

**Only your own runs.** A chat reaches your computer only when it is your own -
never an API key, a widget visitor or someone else's chat - and a
[trigger](triggers.md) only when it acts as its creator, who points it at a folder
of their computer under the trigger's **Work on**.

**When the computer is away.** An interactive chat run that asked for this computer and finds the app
not connected waits up to ten minutes for it, and the chat says so. An operation
that finds the app gone mid-run - a closed lid, a changed network - waits up to five
minutes for it to come back on the same session, then carries on. While a run's
operation is in flight, the tray says an agent is working on this computer.

The server checks the sign-in before forwarding each local operation. Revoked or expired sessions refuse new work; the heartbeat also closes idle connections. Operations already in progress are cancelled when the desktop socket closes.

In the Builder, **Sandbox → Computer** stores `backend: local` with no path or
native consent. Each person approves their own target in desktop chat. Such an
agent has no cloud workspace, so **Work on** offers no Cloud for it.

You can write to
it before granting anything: it answers what needs no files, and only when a
request needs your files does it ask where it may work - **Whole computer** or a
folder. The run waits for your choice, then the chat continues with the files on
its own. The answer is remembered for that agent on this computer, so its later
chats start there without asking. In the web console, where there is no computer
to grant, it says it cannot reach your files. When creating a
project, **Project sandbox → Computer · your files** opens the personal folder
selector; other members keep the project’s shared workspace.

**Whole computer.** Desktop chat also offers **Whole computer** without a folder
picker. One native warning grants access: for an agent whose workspace is
**Computer**, the warning names the agent and the consent holds for it in every
conversation; otherwise it is for this conversation. File tools can reach
absolute paths anywhere your account can access and commands run as you, without
individual native prompts. Operating system permissions and the agent's approval
rules still apply. **Revoke whole-computer access** or choosing **Cloud** blocks new
operations; commands already running are not interrupted. Consent survives app
restarts and is scoped to this server and to the agent or conversation; a draft binds
a conversation's consent on its first operation. A new chat with another agent needs
its own consent. This mode does not crawl the home
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
  window, because some OAuth flows - connecting an account for a terminal - have to
  come back to the same webview for their cookie to land. The window's title names
  any other host it shows. Connecting an MCP server is not one of them: its consent
  opens in your own browser, where your sign-ins and passkeys are, because the
  callback is authenticated by its `state` alone. Finish there and come back; the
  server appears in the app once it is authorised.

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

## Coding agents on this computer { #coding-agents-on-this-computer }

**Settings → Desktop app → Coding agents on this computer** shows versions and
sign-in status. **Set up** prepares private Node.js 24.19.0 and the pinned coding
adapters from a lockfile, with download integrity checks. You do not need to
install developer tools separately. **Sign in** starts the agent's own browser
OAuth flow; AgenticOS does not read or copy credentials. **Refresh status** checks
sign-in explicitly. Returning focus to the app does not repeatedly probe the
credential store; successful sign-in and setup refresh the status automatically.

In desktop **Chat controls → Tools & files → Coding agent**, choose **Claude Code** or **Codex**, even when the published capability is disabled or absent. The app prepares local file tools and opens the native folder picker unless the current folder already has a full-access grant. Cancelling leaves the previous settings unchanged. **Use agent setting** restores the published configuration.

The choice belongs to this chat. Existing read-only and approval rules still apply, and native startup approval can be remembered for this agent and folder. Switching to Cloud clears the conversation's local coding choice. Chat controls opens above the composer. Its tabs are **Model**, **Tools & files** (Coding agent, Work on, Browser, Computer use and skills) and **Preferences** (approvals and notifications).

Set the **Coding agent** capability to **On this computer**, choose a folder
under **Work on**, and grant it full access. Native approval is remembered for
this agent, folder, adapter version and connection. Removing or reselecting the
folder clears its approval and stops its running agents; account and server
changes clear approvals too. The adapter runs as your operating-system account:
the folder selects its working directory, not an OS sandbox. Whole-computer
access starts a coding agent too, in your home folder or a folder inside it. Task approval and OS permissions still apply.

The capability's approval applies once per task. Inside it, `edit` allows requested operations and `read_only` refuses changes. Claude read-only disables bypass permissions and exposes only reading tools. Codex read-only selects its native read-only sandbox mode. Local agents use their own model settings; subscription usage is unpriced, so the run's reported cost is a floor.

Later tasks resume the named session (`main` when a task names none) for this conversation, agent, harness, folder, account and access policy; several sessions run at once, up to eight on one computer, each in the chat's folder or a folder inside it. `fresh_session` explicitly starts over. Resume identifiers stay in desktop settings, outside your repository, and are cleared when you unlink or change accounts. If a saved session cannot load, the task fails explicitly; start fresh when appropriate. Processes stop on disconnect, but their saved harness history can be resumed.

A correction sent while a local task is running interrupts its current ACP turn. After the adapter confirms the stop, the same session continues with the correction. The transcript records the applied correction; a message arriving after completion stays available to the parent agent.

After choosing the harness and an approved folder, **Coding model** and **Reasoning level** list choices reported by that installed harness. They belong to this conversation and are applied before a new or resumed task starts. Leave either unset to retain the harness’s own setting. Switching harness clears incompatible overrides. Refresh choices explicitly after changing sign-in or configuration; opening another window does not probe the account again. A removed or unsupported choice is shown and refused, rather than silently substituted. Reading choices starts no model turn and grants no tool permission.

## Your own skills and instructions { #your-own-skills-and-instructions }

**Chat controls → Work on → My skills and instructions** selects which sources a conversation may use: `~/.agents/skills`, `~/.claude/skills` and `~/.codex/skills`. Every new chat starts with these sources off. Files are read in place, without copying or syncing credentials or configuration.

Among enabled sources, a name clash goes to `.agents`, then `.claude`, then `.codex`. Counts reflect the current selection. Links to the same skill folder are deduplicated by the desktop reader. Global instructions use the newer enabled `~/.codex/AGENTS.md`, `~/.claude/AGENTS.md` or `~/.claude/CLAUDE.md` file, including Markdown symlinks.

The approved working folder's `AGENTS.md` and `CLAUDE.md` follow the global instructions. Before entering a subfolder, the agent can call `load_local_instructions` to read the hierarchy from the approved root down to that directory. More specific files follow parent files. This reader never traverses above the approved folder or follows project symlinks. Instruction files cannot widen the run's permissions.

Loaded skill and instruction text travels through your server to the agent's configured model. The source switch controls this AgenticOS context; locally running coding agents retain their own configuration and instruction discovery.

## Diagnostics { #diagnostics }

**Help → Export Diagnostics…** writes one JSON file to a place you choose, to attach to a bug report. It holds the version, the operating system, what macOS has allowed, whether Claude Code and Codex are installed and signed in, the server's address (scheme, host and port only) and the last crashes. It holds no credentials, tokens, conversations or paths under your home folder, and nothing is sent anywhere. A crash is written to `crash.log` in the app's data folder as it happens.

If desktop 1.38.1 stays at **Linked — reconnecting…** and local chats say
**Waiting for your computer**, check the exported crash locations for
`rustls` / `crypto/mod.rs`. This desktop TLS startup defect is fixed in a newer
desktop release. Install that release and reopen the app; updating only the
server does not replace the desktop client. Existing pairing and folder grants
do not need to be reset for this fix.

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

Native browsing consent is shared by this conversation’s tabs for the current device connection. New tabs and tabs reopened by the agent do not prompt again under the same domain policy. Closing the last tab yourself revokes consent; hiding the panel does not. Disconnecting the device clears it. A different person, agent, conversation or domain policy requires its own consent.

Computer use and Web browser settings use environment cards with short descriptions. New Computer use bindings explicitly select Docker / Sandbox. Automatic is no longer offered in the picker; existing automatic configurations remain readable and unchanged until a person chooses an environment. Docker Compose includes sandboxd and its desktop runtime. An operator can register another sandbox host URL and key under Connections → Sandboxes, then select it and the desktop runtime in the agent’s Sandbox settings.

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

The Apps workflow also builds development installers and tests installation without UI automation: copying the Mac app from its DMG, silent installation and removal on Windows, Debian installation and removal, and portable AppImage extraction. It verifies the embedded macOS widget and signatures, persistent session isolation, and rejection of tampered updater downloads. These checks use ad-hoc or unsigned builds and do not establish public notarization or store approval.

The **Apps** GitHub Actions workflow checks native crates on macOS, Windows and
Linux and builds Android debug APKs and an iOS simulator app. Full native checks
run in CI. Local `make desktop-check` remains available for a focused change.
The **App release** workflow attaches installers, signed updater artifacts, an
Android APK and a Homebrew cask to an existing published stable `v1.MINOR.PATCH`
release whose commit is on `main`. It does not create a platform release. The cask is also published to the Homebrew tap when a deploy key or token is configured.
The desktop menu's **Check for Updates…** requires a build with the updater public
key and verifies the downloaded signature before installation.

Desktop release builds run in parallel. Each uploads its own signed packages;
one final job validates all four native targets and publishes `latest.json`.
Native CI caches build outputs by operating system, architecture, compiler,
target and build profile. Releases only restore shared dependency downloads.
A failed platform build prevents updater publication.

Mobile publishing is currently disabled. Set the repository variable
`AGENTICOS_MOBILE_RELEASES_ENABLED=true` to opt in to signed Android releases;
iOS also requires the TestFlight flag below. This does not disable regular CI
builds. Until distribution is enabled, follow
[mobile self-installation](mobile.md#availability-and-self-installation).

Configure the `apps-release` GitHub environment before running a release:

- Stable macOS signing: secrets `MACOS_SELF_SIGNED_P12`, `MACOS_SELF_SIGNED_P12_PASSWORD` and variable `MACOS_SELF_SIGNED_IDENTITY`. Publish its public fingerprint in `scripts/macos_signing_identity.txt`.
- Homebrew: secret `HOMEBREW_TAP_DEPLOY_KEY`, a write deploy key restricted to the tap repository. `HOMEBREW_TAP_TOKEN` remains an alternative. Temporary key files are removed on success and failure.
- Variable `AGENTICOS_UPDATER_PUBLIC_KEY`; secrets `TAURI_SIGNING_PRIVATE_KEY`
  and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (one persistent updater key pair).
- Optional macOS Developer ID signing: set the repository variable
  `AGENTICOS_MACOS_SIGNING_ENABLED=true` and configure `APPLE_CERTIFICATE`
  (base64 P12), `APPLE_CERTIFICATE_PASSWORD`,
  `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD` (app-specific),
  and `APPLE_TEAM_ID` for Developer ID signing and notarization. When enabled,
  missing credentials stop the build; there is no fallback to ad-hoc signing.
  With the flag unset or false, macOS uses the configured stable self-signed certificate, or ad-hoc signing when none is configured. Neither is notarized; Apple credentials are ignored in that mode.
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

Quick Ask supports up to eight independent tabs in each window. The tab bar keeps drafts, attachments, selected agents and running answers separate. Recent conversations opens a searchable list and reuses an already open tab; saved chats restore messages and offer earlier history. Inactive tabs do not capture file drops, dictation shortcuts or focus. Recent conversations shows agent avatars in a compact expandable section. It uses only the space its contents need, without reserving blank window height. New chat is the single action for opening a fresh tab. The browser sidebar offers the desktop download; dismissing it pauses reminders for 14 days in that browser account.

Quick Ask has a microphone button for click-to-start dictation as well as hold-to-talk, and the same live voice call controls as chat. Calls use the selected agent’s configured transport, show captions, approvals and questions, and save spoken turns in the conversation. Text sending and dictation wait while a call is active. Leaving the tab or changing its agent ends the call and releases the microphone.

## Local routines { #local-routines }

A refusal from a replacement computer does not prove that the approved computer lost its permission: it may simply be offline. The owner gets a deduplicated notice to reconnect or review access, while the routine and its event payloads keep waiting. A refusal from the originally selected active session still stops the routine for review.

On Linux the app checks that the installed bubblewrap advertises `--bind-fd` before offering folder writes or starting a sandboxed command. Missing, unsupported or unresponsive builds are refused; upgrade bubblewrap to enable this mode.

Routine permission JSON is verified against its current SHA-256 fingerprint in the operating system keychain. Editing it or restoring a copy made before revocation cannot grant access. An unavailable keychain or a mismatch blocks routine access. **Upgrade:** older routine grants have no fingerprint and require fresh approval: explicitly unlink the computer, link it again and review its routines. The same reset recovers an interrupted permission write; the app never trusts an unverified store automatically.

Create a local routine with **Run as me**, choose its folder and select read, write and command access separately. Commands require write access. Saving first creates a paused routine. The first time, the desktop app asks once, natively, to let **all your routines** in this organization work in that folder and the folders inside it, with those operations; choose your home folder for the whole computer.

Every later routine in that folder, now or later, is saved without asking, and the permission holds after the app updates and after you sign in again. Cancelling keeps the same routine paused; retrying completes its setup without creating another routine. A general chat folder grant never authorizes a routine.

**Settings → Desktop → Routine permissions** lists the current account and organization's grants on this computer. Revoke one there to stop future operations. Changing server or account clears them; a permission for one routine, granted by an older app, also ends with its session. Changing a folder or increasing operations needs fresh native confirmation. Browser, screen, local models, local MCP services and whole-computer access are outside a routine folder grant. The published agent must already enable Sandbox; choosing a local target does not enable capabilities.

When the exact approved computer is offline before execution, a durable activation waits in PostgreSQL. The routine row shows the pending count. Scheduled/manual occurrences coalesce while waiting; distinct incoming events retain their own context and activation ID. The existing minute worker checks for reconnection. Offline readiness checks make no model call and do not consume dispatch failure attempts. Start admission commits with the run before its first model call. A started activation is never automatically replayed after a worker crash; an uncertain file or shell operation is never turned into a new run.

Pausing, changing the task or native authority, deleting the routine or reaching its end cancels the old waiting work rather than moving it to another folder. A revoked device session requires review. Three dead or missing pre-admission dispatches stop the routine and create an owner incident; the failed event context remains available in the owner's data export. Completed/cancelled contexts are cleared immediately. Finished wait metadata and failed context follow the organization's run-history retention; live offline waits remain until admission, cancellation or deletion.

Deploy API, workers and desktop together and drain old workers before enabling this contract. Older desktops cannot confirm routine grants; legacy local routines need explicit review. Migration `0272_routine_device_waits.py` adds the waits without changing routine identity. Before downgrading, pause local routines and drain their jobs: downgrade removes pending wait context and does not run it again. Existing parked local runs without the native-target snapshot require a fresh run.

Local access choices belong to the selected agent, not to a global default inherited by other agents. Revoking a folder also removes its remembered choices and coding consents for folders inside it. Older desktop apps keep whole-computer consent within one conversation; upgrade the app to remember it across an agent’s conversations.

While local coding sessions run, `[session:api] Use the EU numbers` redirects the session named `api`. With one active session, an unaddressed correction reaches it; with several, it stays with the parent agent to avoid changing an unrelated task. The parent records the correction once when it continues.

 Sandbox coding tasks in the same toolset queue so their workspace snapshots do not overlap; independent local sessions still run in parallel.
