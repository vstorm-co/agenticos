# Computer use (`computer_use`)

Four tools. With `computer_screenshot` and `computer_act` the model looks at a
desktop, sends a few mouse and keyboard actions in that screenshot's pixels and
gets a new screenshot back. `computer_apps` lists the applications a `launch`
action may open, and `computer_save_screenshot` keeps a screenshot for the user.
Unlike `browser_use`, the desktop can run any application, not only a web page.
#2094 is the issue.

## Where the desktop is

The settings ask `desktop` first: `sandbox` or `daemon`.

- **`sandbox`**, the default: a desktop inside the agent's own sandbox, the
  container the `sandbox` capability opens on one of the organization's
  connections. A click is an `xdotool` command run there and a screenshot is a
  `scrot` file read back, both through the run's `ctx.workspace`, so computer
  use has no address, token or provider of its own. The shell, the files and
  the desktop are one machine: the agent can write a file with its file tools
  and open it on the screen. The sandbox needs the `desktop` runtime (Xvfb,
  XFCE, Firefox, xdotool, scrot), and publish refuses an agent whose desktop is
  in a sandbox it does not have or on any other runtime - the spec's, else the
  connection's default, and naming neither is refused too. A sandbox's key
  includes its runtime, so moving an agent to `desktop` opens a new container
  rather than reattaching to the workbench one. `open_sandbox_desktop` starts
  the display on each run's first use, because a sandbox that hibernated
  between turns kept its files and lost its processes.
- **`daemon`**: a `computerd` process the operator runs, on their own Linux
  desktop (X11), on a Mac's own screen or in a container
  (`deploy/computer/Dockerfile`). A run reaches it over HTTP with the
  daemon's token, an API key in the organization's vault that the binding
  names (`secret=` with `required_when` the daemon). Its host must be on
  `COMPUTER_DAEMON_ALLOWED_HOSTS`, checked by `check_daemon_url` at publish
  and again in `_open`, so a host the operator removes is not sent the token
  by an agent published before. `daemon_url` is in the spec, so it is under
  tenant control; this works the same way as `BROWSER_CDP_ALLOWED_HOSTS`. The
  allowlist is the deployment's, so any organization can name an allowed
  host; the token is what keeps one organization off another's desktop, which
  is why it is not a deployment setting.
  One daemon is one desktop: every run holding its token shares the machine.
  The container runs computerd and the desktop as two accounts, so an agent
  with a terminal on that desktop cannot read the token.

## Decisions

**Look and act are separate tools.** `computer_screenshot` changes nothing.
`computer_act` clicks and types on a real machine, so it is side-effecting.
Approval is opt-in, as for every tool: `tool_approval: {computer_act: required}`
holds the actions alone, so whoever approves a batch approves it against a
screenshot the model has already shown. The approved batch runs in a resumed
run, which is a new one with nothing looked at yet, so `computer_act` measures
the screen first rather than refuse the batch. The gate stores the batch as JSON
and runs it from there, so `computer_act` validates its actions again.
`computer_apps` only reads the menu, so it is not side-effecting either; it is a
tool rather than an action so that holding `computer_act` never holds a look at
what is installed.

**A park forgets nothing the run needs.** Every answer carries a `Seen` in its
`metadata`: the run's id, the screenshot's `Screen` and the actions taken so
far. The metadata is stored with the run's messages and never sent to the
model. A resumed run reads back the last one: a batch runs only if the screen
measured now is the `Screen` it was chosen on, and `max_actions` carries on
from the count when the run is the same one. A history with no screenshot
behind the batch is steered to take one.

**The model's screenshots are not kept.** Each is an `ephemeral_image`
(`app/agents/ephemeral_media.py`), and `dump_messages` puts a sentence in its
place wherever a run's messages are stored: the parked state, a parked
delegate's history, the manifest and a compacted conversation. The tool row
in the transcript says the same. `computer_save_screenshot` is the one the user
keeps.

**Coordinates are scaled in one place.** The model sees at most
`screen_width`x`screen_height`. `_actions.Screen.to_native` maps every point
back into the backend's input space: X11 pixels on Linux, or the points of a
Retina Mac that the daemon reports in `x-screen-width`/`x-screen-height`. No
backend knows the model saw anything else. A point outside the last screenshot
is steered back before anything runs.

**Every `computer_act` answer includes a fresh screenshot.** The model needs to
see the screen after its actions to choose its next ones. Returning the screenshot
here saves one round trip per step.

**The live view reuses the browser window.** Frames are sent as `BrowserEvent`s
on the `/ws/agent` socket under one `call_id` per run: the tool-call id of the
first `computer_screenshot`, because the chat draws a window under the call it
names (`browseCalls` in `frontend/src/components/chat/turn-parts.tsx`). Every
later call draws there, so a session is one window rather than one per call.
`ComputerToolset` counts the run's entries, as `BrowserToolset` does, and sends
`browser_finished` once, on the last exit.

**The user's screenshot is a tool of its own.** What the model looks at is
scaled down, re-encoded as JPEG and taken dozens of times a run; keeping every
one would bury the chat. `computer_save_screenshot` is the deliberate one: the
PNG as the backend took it, stored organization-scoped through
`app/services/generated_media.py` (a platform service, so image generation
need not be bound) and returned as a `desktop_screenshot` payload the chat draws
(`tool-results/desktop-screenshot.tsx`). With a workspace open it is written to
`output/` too, which is what a channel reply posts and what a testing agent's
report can link. It changes nothing on the desktop, so it is not side-effecting.

**Opening an application:** `computer_apps` lists what the desktop's menu
shows, and a `launch` action opens one of them by its name or id, because
finding an icon in a screenshot and clicking it is the slowest and least
reliable way there. Listing and opening are the same code everywhere:
`_desktop_apps.py`, standard library only, which a sandbox runs with
`python3 -c` and the computerd image copies in beside the daemon. It reads the
desktop entries on the XDG search path and its subdirectories (whose names
prefix the id), an earlier directory's shadowing a later one with the same id,
and names each in the desktop's locale. It leaves out what the menu would not
show: hidden entries, ones that are not applications, another desktop's
(`OnlyShowIn` and `NotShowIn`, read for XFCE when `XDG_CURRENT_DESKTOP` is
unset, as it is outside the session) and ones whose `TryExec` is missing. A launch
must match an id or a name exactly, ignoring case, so it is never a guess: a
name two entries share (a system and a Flatpak Firefox) is answered with their
ids. It opens the entry with `exo-open` and returns once a new window shows or
the focus moves. If neither happens within ten seconds the launch fails, so the
rest of its batch does not type into the window that had the focus before. The name is validated to a name - no slash, no leading
dash, no control character - so it can never be a path or an option; other
punctuation is allowed, because real names have it. computerd's container
lists and opens through a launcher running as `desk`: computerd itself holds
the token.

Only Linux desktops launch: a sandbox's, E2B's and computerd's container. A
computerd without its container's launcher, on a Mac or a person's own Linux
desktop, and the person's own computer through the desktop app refuse
`launch` and `computer_apps`. The desktop app's instructions name that
computer's own launcher instead. A daemon cannot be told apart in advance, so
its instructions say to call `computer_apps` first and fall back to the
computer's own launcher if it is refused.

**Limits:** `max_actions_per_call` bounds one batch. `max_actions` bounds a run;
past it the tool tells the model to stop and report what is left. A `type`
action carries at most 2000 characters.

## Not yet

- A shareable live link for Slack and Mattermost, and a continuous stream
  (noVNC) between steps.
- A live window for a run resumed after approval. The continuation runs over
  HTTP, not the conversation's socket, so it has no `browser_events` sink and
  the chat records it as a line, as it does a resumed `browser_use` run.
- A per-organization host allowlist. The hosts are the deployment's
  (`COMPUTER_DAEMON_ALLOWED_HOSTS`); the token that opens one is the
  organization's.
- A saved screenshot in a channel reply when the run has no workspace. Channels
  post the files a turn wrote, so a daemon desktop with no Sandbox capability
  reaches Slack as a sentence, as image generation without one does.
- An approval bound to the pixels. A resumed batch is refused on a screen of
  another shape, but a desktop is never the same twice - a clock, a cursor, a
  notification - so the same shape with different contents still runs.
- Two runs on one desktop at once. Each run has a session of its own,
  delegations included, but a daemon, or a sandbox shared with delegates, is
  one screen, and nothing queues one run's clicks behind another's.
- A cloud desktop. A cloud sandbox provider (E2B, for one) would arrive as a
  sandbox connection kind, and its desktop would come with it.
- `launch` on a Mac or a self-hosted Linux desktop, whether through computerd
  or the person's own computer in the desktop app. Neither has a launcher yet,
  so the model is told to use the computer's own.
- A sandbox desktop is not hidden from the shell: an agent with `execute` can
  run `xdotool` itself, past an approval held on `computer_act`.

## Environment picker

The Builder shows short environment names and the requirements of the selected
option underneath. Stored values stay `auto`, `e2b`, `sandbox`, `local` and
`daemon`. **Docker / Sandbox** reuses the agent's configured Sandbox connection
(Docker or E2B, on the `desktop` runtime); **E2B** opens a separate desktop for the
run using the capability's vault key. **Local** requires the paired app and a
chat working on that computer. **Remote computer** uses an approved computerd
address and its token. Automatic retains its existing Local → E2B → sandbox
resolution; the form does not change execution or migrate existing specs.
