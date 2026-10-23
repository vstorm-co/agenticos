# The phone app

The console works in a phone's browser, and it can be added to a home screen as an
app. The AgenticOS phone app, for iOS and Android, adds what only an app can do:
the lock screen, the Dynamic Island, widgets, the Share sheet, push while it is
closed, and a lock of its own. Like the [desktop app](desktop.md) it is a shell
around the deployment's own console, so the sign-in, the permissions and the
tenant checks are the console's.

> **Screenshot pending — the phone app, a live activity and the widgets.**

It is a [Tauri](https://tauri.app) app in `mobile/`, with the native halves -
Swift for iOS, Kotlin for Android - under `mobile/src-tauri/`.

## Signing in

**Settings → Mobile app** in the console shows a QR code; scanning it with the app
signs the app in as you. A code works once, for a minute, and the phone's session
is opened only when it scans, under the phone's own name. Typing the server's
address and signing in works too. The session survives restarts, and the app
locks behind Face ID, Touch ID or the fingerprint after five minutes away.

**Active sessions**, under Settings → Profile, lists every signed-in device:
"AgenticOS for iOS 0.2.0" for the app, the browser otherwise, and which of them
receive push. Revoking one there signs that app out at once.

## Push

| Where | Through | Turned on in |
|---|---|---|
| iPhone | Apple's push service, with the organization's own APNs key (Admin → Settings) | The app's Settings → Notifications |
| Android | ntfy (ntfy.sh or a company's own server), not Google's | The app's Settings → Notifications, with the ntfy app installed |
| A browser, or the console added to a home screen | Web Push, with the deployment's own key | Settings → Notifications |

Each event's notifications - email, push - are chosen per event under Settings →
Notifications. A notification opens its page through the app's lock.

## Outside the app

**Live activities** - the lock screen and the Dynamic Island on iOS, an ongoing
notification on Android - show what is live for you:

- your runs in progress, with a clock;
- an approval waiting for you, with Reject and Approve;
- a question an agent is waiting on you to answer, which opens its conversation;
- a voice call in progress, with its clock, saying when the agent asks something.

A decision taken from the lock screen waits for Face ID or the fingerprint, then
goes through the same request as the queue's buttons.

**Widgets.** The glance widget counts the approvals waiting for you and your runs
in flight, with the time they were counted, and the share of the organization's
monthly budget left when it has a cap. The pinned agents widget opens a new chat
with an agent you pinned on its page; on Android the pin also places a launcher
shortcut wearing the agent's face. The counts are the console's own, refreshed
whenever it reads them.

**Shortcuts.** The app icon's long-press menu, Shortcuts and Siri, the Action
Button and Control Center on iOS, and a Quick Settings tile on Android start a
voice call, dictation, a new chat or the approvals.

**Share to AgenticOS.** Any app's Share sheet offers AgenticOS: text, links,
photos and files (up to 20 MB each) land in a new message. Nothing is attached
while the app is locked.

## In the app

- **A chat like a messenger.** The composer's `+` opens Camera, Photos and Files,
  then voice input and commands, the call, the model and approvals. Opening the
  chat offers a photo taken a moment ago; only the photos you tap reach the
  message.
- **Gestures.** Swipe a waiting approval right to approve it or left to reject it,
  and pull a page down to read it again, with a haptic tap when letting go would
  act.
- **Pages move like the phone's own.** A page opened slides in from the trailing
  edge and one gone back to from the leading edge. Reduced motion turns it off.

## Without a network

The phone app, the desktop app and the console added to a home screen keep a copy
on the device for seven days: the conversation list, the twenty conversations
opened last with their newest files, the approvals queue, and the dashboard's
spend, failures and conversations to pick up again. The copy is sealed with a key
no script can read out and deleted on sign-out or a switch of organization; a
plain browser tab keeps nothing.

Offline, the console shows that copy under a banner saying when it was saved. A
message written offline waits above the composer, survives closing the app, and
sends when the connection returns; one the server refuses comes back marked "Not
sent" with the reason.

## Installing the console instead

In a browser that can install it, a strip under the console's header offers to:
its own window, push and a home-screen icon, without the native extras above. On
an iPhone it says how - Share, then Add to Home Screen. Dismissed once, it does not
come back in that browser.

## Device management

An organization can set the server the app connects to, lock it so the person
cannot point the app elsewhere, and force the biometric lock on or off - keys
`serverUrl`, `serverLocked` and `biometricLock` (`person` | `on` | `off`) in
Android's managed configurations and iOS's managed app configuration (AppConfig).
A policy that cannot be read is ignored rather than locking anybody out.

## Where it sits in the tree

- `mobile/src-tauri/src/` - the Rust plugins the console calls: live activities
  (`live.rs`), widgets (`widget.rs`), pins, share, push and managed configuration.
- `mobile/src-tauri/ios/Sources/AgenticOSNative/` - the iOS plugins and the types
  the widget extension shares with the app.
- `mobile/src-tauri/gen/apple/Widgets/` - the widgets, controls and live activity.
- `mobile/src-tauri/gen/android/` - the Android project: the plugins, the widgets
  and their layouts.
- `frontend/src/components/mobile/` - the console's half: what is live, the widget's
  counts, the actions the app hands back.

## Recap

- **The console stays on the server.** The app opens it and adds the phone's own
  surfaces.
- **Live outside the app**: runs, approvals, questions and calls on the lock
  screen; counts, budget and pinned agents on widgets.
- **Push without Google** on Android, with the organization's own key on iPhone.
- **A copy on the device**, sealed, for when there is no network.
