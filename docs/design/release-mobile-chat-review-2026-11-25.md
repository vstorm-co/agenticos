# Mobile and chat release review — 25 November 2026

Integration base: `0c9e016732e5bb7da4fabdb612526c88aac5e656`
(`#3449`, the authorized console train). This branch does not merge main,
publish a release or deploy. Each selected source is based directly on main
`bb09fedf19b10f897c6a55dbdcd76a212dc9a275`; no unapproved feature parent is imported.

| Source | Exact reviewed head | Result |
| --- | --- | --- |
| #3425 | `18a1bafaf41c8ab7ace374016bde114d2e158da9` | Exclude auth pages from fresh-session destinations; extend the fix to encoded paths. |
| #3426 | `6b95924df2b74558302cd32c7bb70383a7a84b0b` | Ship the microphone purpose in both plist and generator, with existing native locale translations. |
| #3427 | `6e95df83a318424691eb0e5c3bc382abdc470bd5` | Forward warm app-icon shortcut actions through the connected scene delegate. |
| #3447 | `4fb04fa7eac3cf22b92ce6bf01d3eee79862da56` | Give Stop a distinct DOM identity and preserve Send-to-Stop keyboard focus. |

#3447 was a draft at the earlier inventory snapshot (`1e20dd09a`); it became
ready and gained `4fb04fa7e` before this review. That second commit restores
keyboard focus after splitting the buttons, and adds keyboard regressions for
both composer layouts. Both commits are included in the reviewed delta.

## Confirmed findings corrected

The sign-in classifier recognized only literal URL paths. Next serves
`/lo%67in` as the login form (observed HTTP 200), but the classifier accepted it
as a destination, retaining the redirect loop for encoded links. Classify one
`decodeURI` pass of the URL parser's pathname; keep reserved separators encoded
and preserve the existing strict same-origin return guard. Four added encoded
route/locale regressions fail without this correction. Malformed escaping and
look-alike agent paths remain covered.

The microphone purpose was absent from the native string catalog even after
adding its plist key. Add the same four native locales already shipped for the
camera and lock purposes. Two packaging regressions fail against the original
files: generated/shipped plist consistency and complete native translations.

No other actionable defect was found in the reviewed changes. Scope limits below
remain explicit; this is not a claim that every native path has device coverage.

## Verification and limitations

- 202 focused frontend tests pass across auth landing, auth guard,
  provider-only sign-in, the chat input and the chat-container integration.
  The encoded-path follow-up passes 54 tests in its three-file auth batch.
- Both native microphone packaging tests pass; the plist validates with
  `plutil`. The actual QuickActions enum type-checks against Apple's iOS
  Simulator 26.5 SDK in Swift 5 mode, the app's configured language version.
- The local browser exercises the actual ChatInput component in a clearly
  marked deterministic harness, without agent/model calls. Finishing the
  response during a Stop press retains the whole next draft and one sent
  message, at desktop and phone widths. This is component evidence, not a
  full provider conversation or a real iPhone recording.
- No iOS simulator devices/runtimes are installed on this host. A complete app
  build and microphone permission interaction on a device remain unverified.
- #3427 deliberately handles already-connected scenes. Cold-launch shortcut
  choices arrive through scene connection options and remain unsupported by
  this patch. The app-delegate fallback and existing deep-link routing remain.
- Source workflows for #3425, #3426 and #3427 require maintainer execution
  approval (`action_required`), not green checks. Source #3447 checks were
  still running at the latest-head review. Aggregate train CI is separate.

Apple documents the warm-scene and cold-connection distinction in
[Add Home Screen quick actions](https://developer.apple.com/documentation/uikit/add-home-screen-quick-actions).
React documents ref cleanup and focus ownership in
[Manipulating the DOM with Refs](https://react.dev/learn/manipulating-the-dom-with-refs).
The modern-web-guidance `validate-origins` review supports retaining the URL
parser and strict existing same-origin boundary; no new browser API or dependency
is introduced for this correction.
