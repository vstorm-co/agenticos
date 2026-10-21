# Computer use (`computer_use`)

Two tools, `computer_screenshot` and `computer_act`. The model looks at a
desktop, sends a few mouse and keyboard actions in that screenshot's pixels and
gets a new screenshot back. Unlike `browser_use`, the desktop can run any application, not only a
web page. #2094 is the issue.

## Where the desktop is

- **`daemon`**: a `computerd` process the operator runs. It can serve a Linux
  desktop in a container (`deploy/computer/Dockerfile`) or a Mac's own screen.
  The deployment reaches it over HTTP with `COMPUTER_DAEMON_TOKEN`. Its host
  must be on `COMPUTER_DAEMON_ALLOWED_HOSTS`, and publish checks that.
  `daemon_url` is in the spec, so it is under tenant control; this works the
  same way as `BROWSER_CDP_ALLOWED_HOSTS`.
  One daemon is one desktop: every run pointed at it shares the machine.
- **`e2b`**: an E2B sandbox (`desktop` template), one per conversation. It is
  found again on the next turn through the metadata key `agenticos_session`,
  which holds the organization and the conversation. The organization is
  included so that two tenants sharing one E2B key can never land on the same
  sandbox. The key is a vault secret with purpose `e2b`, required only for this
  backend. The SDK ships as the `computer` extra.

## Decisions

**Look and act are separate tools.** `computer_screenshot` changes nothing.
`computer_act` clicks and types on a real machine, so it is side-effecting.
Approval is opt-in, as for every tool: `tool_approval: {computer_act: required}`
holds the actions alone, so whoever approves a batch approves it against a
screenshot the model has already shown. The approved batch runs in a resumed
run, which is a new one with nothing looked at yet, so `computer_act` measures
the screen first rather than refuse the batch. The gate stores the batch as JSON
and runs it from there, so `computer_act` validates its actions again.

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

**Limits:** `max_actions_per_call` bounds one batch. `max_actions` bounds a run;
past it the tool tells the model to stop and report what is left. A `type`
action carries at most 2000 characters.

## Not yet

- A shareable live link for Slack and Mattermost, and a continuous stream
  (noVNC) between steps.
- A live window for a run resumed after approval. The continuation runs over
  HTTP, not the conversation's socket, so it has no `browser_events` sink and
  the chat records it as a line, as it does a resumed `browser_use` run.
- Per-organization daemons in the vault, as `sandbox_connections` does for the
  sandbox. For now the daemon token belongs to the deployment.
