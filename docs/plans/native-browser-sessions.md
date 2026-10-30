# Native browser sessions

Continue browser responsiveness in PR #2326. Desktop local browsing uses a real
Tauri child WebView mounted inside the console's browser panel. The page can only
send a one-way takeover notification for itself; it has no console, file or device
permissions. Only the trusted console may mount it or change its controls.
Console grants match their exact WebView label, so a browsed page visiting the
console's own origin does not inherit its parent window's permissions.
The existing DOM reader and element identity checks are shared with Chromium.
A native adapter handles evaluation, navigation and DOM input. Scripted DOM input
is not equivalent to trusted CDP input; tasks requiring Chromium or vision retain
the existing isolated Chromium path rather than pretending the engines match.

Native tabs belong to the paired computer, organization, user, agent and
conversation. A run leases a tab exclusively, then releases it without destroying
its page. Tabs close explicitly, on device disconnect/sign-out, or on bounded
idle eviction. Changed domain policy must not reuse an incompatible tab. Native
navigation enforces the same allowlist for manual navigation and redirects.
Manual trusted input records a takeover before an agent can issue its next action.

Built in remains remote Chromium. Its changes should bound frame delivery under
slow readers, avoid duplicate image delivery through both chat and image sockets,
and measure the image/transport path separately from model latency. No codec or
provider change is justified without a comparison.

Verification must cover lease exclusion, identity/policy isolation, release and
close, manual takeover, DOM adapter compatibility, native viewport cleanup and
slow-reader backpressure. Scoped tests run locally; platform builds and the full
suites run in CI. An isolated native test harness must establish actual WebView
compatibility before the native path becomes the desktop default.

The native WebKit smoke harness has passed on macOS: promise evaluation, page
replacement and redirects, DOM click and typing, takeover, conversation reuse,
exclusive and stale leases, renderer mount ownership,
domain refusal and disconnect cleanup. It uses a hidden isolated window and a
loopback HTTP fixture, with no model, device connection or personal browser.
Run `cargo run --locked --example native_browser_smoke` from `desktop/src-tauri`.
Renderer mounts carry a token so a stale React cleanup cannot hide a newly mounted
view. Full console navigations hide all children; device changes close them.

The native smoke fixture also applies a restrictive Content Security Policy and
checks that the page can pause its own agent but cannot call a console command,
even when the console capability matches the page's origin. Script evaluation
does not depend on JavaScript `eval`, inline scripts or an `unsafe-eval` policy.

Active runs renew their native lease every 30 seconds, including with preview
disabled. Native commands require a fresh lease; after two minutes without
renewal a new run may acquire the same conversation tab. UI metadata polls keep
the tab active but do not renew a crashed run's lease. Release is idempotent for
closed/idle tabs and rejects a token belonging to a different active run.

The redirect check reproduced and guards against treating HTTP redirects as
manual takeover. Only trusted physical input and console controls pause the
agent; page navigation still passes the domain policy before it loads.

Browser panels now dock beside the chat when their available area is at least
900 CSS pixels wide. The separator supports pointer capture and keyboard arrows;
width stays between 35% and 65%. Explicit fullscreen keeps the same renderer and
lease mounted. Native pixels hide during resize and over source/file overlays or
dialogs, then return at the measured DOM bounds. Phones remain fullscreen.
