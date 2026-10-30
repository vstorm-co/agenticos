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

## Availability and self-installation

!!! info "Mobile builds are available for development, not public distribution"

    We build the mobile app in CI, but do not currently publish it through TestFlight,
    the App Store or Google Play, or provide a supported mobile release download.
    To use the native app now, build and install it yourself and connect it to an
    AgenticOS deployment operated by you or your organization. We do not provide
    a hosted AgenticOS server or Apple signing accounts with the app.

The **Apps** workflow builds an Android debug APK and an unsigned iOS simulator
app. These are development checks, not store releases. An iOS simulator build
cannot be installed on a physical iPhone. Running on a real device requires your
own signing and provisioning for the app and its extensions.

From a clone, install Rust and the platform toolchain: Xcode on macOS for iOS,
or the Android SDK, NDK and JDK for Android. Then:

```bash
cd mobile
bun install --frozen-lockfile
bun run ios        # iOS development on macOS
# or
bun run android    # Android development
```

Enter the address of your deployment when the app starts. It must be reachable
from the phone; `localhost` on a phone refers to the phone, not your development
computer. The [browser/home-screen version](#installing-the-console-instead)
remains an option without building the native app.

Public mobile distribution is disabled by default in the release workflow.
Enabling it later requires `AGENTICOS_MOBILE_RELEASES_ENABLED=true`; iOS also
requires `AGENTICOS_TESTFLIGHT_ENABLED=true` and the signing configuration in
[app releases](desktop.md#installers-and-updates). The regular CI builds remain enabled.

## Signing in

Scanning shows the target account’s name and email first. Confirm the account to sign in; cancel leaves the current session unchanged. Previewing never consumes the code or extends its one-minute lifetime.

**Settings → Mobile app** in the console shows a QR code; scanning it with the app
lets you confirm signing in as you. A code works once, for a minute, and the phone's session
is opened only after confirmation, under the phone's own name. Typing the server's
address and signing in works too. The session survives restarts, and the app
locks behind Face ID, Touch ID or the fingerprint after five minutes away.

**Active sessions**, under Settings → Profile, lists every signed-in device:
"AgenticOS for iOS 0.2.0" for the app, the browser otherwise, and which of them
receive push. Revoking one there signs that app out at once.

If an initial connection or sign-in return has not finished loading after 30
seconds, the app returns to the server form with the saved address and a
connection message. Retry or enter another address. A cached offline page that
loads successfully stays open.

## Connection readiness and saved servers

After signing in, **Finish setting up this phone** checks the account, an available
published agent, app lock and notifications. Existing accounts receive the same
review when settings are still missing. Continue postpones optional setup; revisit
it under **Settings → Mobile app**. A changed set of missing settings is reviewed
again. Camera access is requested when scanning, microphone access when starting
voice, never by readiness checks. Denied iOS notifications offer a system-settings
button; returning to the app rechecks the permission.

**Settings → Mobile app → Switch server** opens saved connections. Give a server a
name, scan another pairing code, or enter another address. Up to 20 servers are
kept. Existing installations migrate their current address automatically. Returning
to a saved server opens its dashboard and uses its persistent session. Cookies and
offline storage are not copied between origins; signing out or changing account
continues to clear that account's device cache. Different saved servers must use
different hostnames: cookies are not isolated by port. Removing a saved entry does
not erase its browser storage; sign out first before sharing the phone.

Switching unregisters push from the previous server before opening the picker;
connectivity to that server is required if it has a push registration. Enable push
on the next server explicitly. The app does not keep background push from several
servers enabled together. Organization-managed server and lock policies take
precedence; disabling the app lock requires device authentication.

Switching also clears old Live Activities, pending actions and widget pins.
Native notification taps are bound to the sign-in that registered push, so a
delayed notification cannot open a different server’s conversation.

Changing the bound account clears already displayed Android notifications.
Switching servers also removes pinned agents from the iOS app-icon quick actions.


## Notification privacy

Phone notification preferences belong to the current sign-in. **Settings →
Notifications** can hide notification text; chat settings can mute a conversation.
Both are applied on the server before an APNs or Web Push payload is sent, so they
work with the app closed. A visible, focused chat renews a 90-second suppression
lease every 30 seconds. Leaving the chat or putting the app in the background
clears focus; a process killed without cleanup leaves at most the lease lifetime.
These choices affect push, not the in-app inbox or ongoing Live Activities.

The test reports acceptance by the push service, not confirmed display on a
particular phone. Check the lock screen or notification center. Android uses
UnifiedPush and offers an ntfy installation guide when no distributor is installed;
iOS reports a missing organization APNs configuration separately from denied OS
permission. No Firebase dependency is added.


## Push

| Where | Through | Turned on in |
|---|---|---|
| iPhone | Apple's push service, with the organization's own APNs key (Admin → Settings) | The app's Settings → Notifications |
| Android | ntfy (ntfy.sh or a company's own server), not Google's | The app's Settings → Notifications, with the ntfy app installed |
| A browser, or the console added to a home screen | Web Push, with the deployment's own key | Settings → Notifications |

Each event's notifications - email, push - are chosen per event under Settings →
Notifications. A notification opens its page through the app's lock.

Push registered by a sign-in stops when that session is revoked or expires. A
linked token is delivered to only when its session belongs to the same user.
Older subscriptions with no recorded session retain their standing permission;
remove and register them again to bind them to the current device.

APNs previews are shortened to fit the complete 4 KiB payload; an oversized
routing URL opens the dashboard instead. An APNs topic or environment mismatch
keeps the device registration so an administrator can repair the configuration.
If at least one device accepted a push before the delivery deadline, the sweep
marks it sent rather than retrying devices already notified.


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

The sign-in form and chat fit the visible area above the keyboard, including
the status bar and home indicator. Touch controls keep a full tap target even
when their icon is small; actions such as copying and dismissing tips remain
visible without hovering. Native sign-in is not covered by the browser cookie
banner.

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
