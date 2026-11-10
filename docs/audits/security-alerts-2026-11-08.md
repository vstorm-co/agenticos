# Native dependency and OAuth alert review, 2026-11-08

Reviewed against `c8458754291e185ed4c0f05a8d112f772881d86d`.

## Code scanning 103: navigation cookie, not authorization

The flagged condition in `frontend/src/components/agents/connect-server-dialog.tsx`
only decides whether to remember a return path in the `mcp_oauth_return` cookie.
It does not grant access or bypass an OAuth exchange. The callback route validates
that browser-controlled path with `safeMcpOAuthReturn` / `isSafeReturnPath` before
redirecting. Its code/state exchange always reaches the backend. The backend
resolves the issued state, enforces its expiry and, for connected accounts, checks
the initiating user and browser nonce. The optional cookie is not that nonce.

Disposition: false positive. Keep the navigation behavior. Existing tests cover
hostile and malformed return paths, callbacks and consent navigation.

## Dependabot 4 and 35: GLib iterator backport

Both native lockfiles contained registry `glib 0.18.5`, affected by
[RUSTSEC-2024-0429](https://rustsec.org/advisories/RUSTSEC-2024-0429.html).
The current stable Tauri v2 GTK dependency requires the 0.18 ABI, so adding a
second GLib 0.20 dependency would not repair the GTK dependency chain.

Both root manifests patch GLib to upstream commit
`ea720152f28e293ef4362ee844ee5cc499f32d2a`, the two-line backport in
[gtk-rs-core #2009](https://github.com/gtk-rs/gtk-rs-core/pull/2009) of
[the original fix](https://github.com/gtk-rs/gtk-rs-core/pull/1343).
It changes the out-argument to a mutable reference. This is an unreleased,
immutable source pin, not a claim that registry 0.18.5 is fixed.

The four linked macro/sys crates must use the same source to satisfy Cargo's
native-library `links` contract. Comparing their Rust sources with the previously
locked registry packages found no code changes. The only changed Rust source
across these five packages is `glib/src/variant_iter.rs` and its two-line fix.

Keep these overrides synchronized until Tauri's entire GTK dependency chain
can use an officially fixed GLib release. Then remove the overrides and update
the Linux regression test's GLib dev dependency together. An advisory matcher
that considers only `0.18.5`, ignoring its Git revision, may still report it;
any disposition must identify this backport rather than accept the original bug.

## Dependabot 36: remove the legacy mobile HTML build path

The mobile build explicitly enabled `tauri-utils/build`, which pulled
`kuchikiki -> selectors 0.24 -> phf_generator 0.8 -> rand 0.7.3`.
Use `build-2`, the feature already selected by the locked `tauri-build 2.7.4`.
It retains `tauri_utils::build::link_apple_library`, used by the iOS build,
without enabling the legacy HTML implementation. Regenerating the mobile lock
removes that chain and all `rand` packages; it does not replace rand 0.7 by an
API-incompatible version or change Tauri's version.

## Verification

- 144 focused frontend tests pass across the OAuth helpers, hooks, callback routes
  and connect dialog. No frontend implementation change is needed for alert 103.
- In an isolated copy of the upstream GLib workspace, Rust 1.99.1 with release
  optimization reproduces SIGSEGV both in its three string-iterator tests and in
  the new application regression test when the two-line fix is reverted.
  Restoring the pinned fix makes all four tests pass.
- The new Linux application test covers forward/backward iteration, exhaustion,
  `nth`, `nth_back` and `last`. Apps CI runs it with GLib optimized at level 2,
  because an ordinary debug build can conceal the unsoundness.
- Native application compilation and platform-specific behavior require the
  existing macOS, Windows and Linux Apps CI matrix. The local GLib reproduction
  is not a substitute for those builds.
