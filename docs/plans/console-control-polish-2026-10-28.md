# Console control and interaction polish — 2026-10-28

This pass preserves the established neutral console, system theme and optional
native glass. It applies the feedback and consistency principles in Apple's
[Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons)
and [Feedback](https://developer.apple.com/design/human-interface-guidelines/feedback)
guidance to the existing React controls; it does not imitate a separate OS skin.

## Inventory and limits

A TypeScript AST scan covered 689 non-test component files and 883 button
instances. The narrow check for a single icon child without a label, title or
forwarded props found no candidates. This is a source inventory, not proof that
every dynamic button is accessible or every screen has been visually reviewed.

No browser automation, Computer Use or screenshots were taken, as requested.
Source inspection, DOM interaction tests and actual Tailwind CSS compilation
verify behavior and style generation. They do not establish pixel-perfect
spacing, perceptual animation quality or physical-device behavior.

## Decisions and alternatives

| Concern | Decision | Alternative assessed |
| --- | --- | --- |
| Waiting actions | Retain the label in layout; center an aria-hidden spinner over it and disable repeats | Adding a 16px spinner beside the label expands an action by another 24px including the gap; replacing the label with an ellipsis loses meaning |
| Press feedback | Quiet active fills and the existing fast duration token | Scaling every button moves its edges and adds motion to dense toolbars; use restrained color feedback instead |
| Compact icon actions | 32px desktop square; retain 44px touch minimum | The previous 28px square leaves 7px around a 14px icon |
| Form controls | Consistent 8px corners, matching heights, keyboard focus and visible invalid states | Separate input, select and textarea corner treatments made a row read as unrelated controls |
| Floating surfaces | Scale from the actual Radix anchor; wrap tooltip text within a 20rem/viewport cap | Center-origin scaling disconnects a menu from its opener; unconstrained hints can outgrow a narrow window |
| Confirmation spacing | Use the same separated action band and remove the second mobile cancel margin | A flex gap plus cancel margin doubles one gap |
| Checkbox | Keep the 16px mark inside a separate 44px touch target; show a dash for partial selection | Enlarging the visual box itself would dominate compact forms |

The existing Motion preference still controls all CSS animations and transitions.
No route animation, artificial wait, new animation dependency or browser preview
route is introduced.

## Verified behavior fixes

- `FormField` associates its label with a caller-supplied control id and exposes
  the required state to assistive technology.
- `Progress` reports its actual value and maximum, handles unknown measurements
  separately from zero, and scales its indicator to custom maxima.
- Calendar month names and weekday labels use the console locale. Navigation uses
  the shared icon button, and day targets adapt to touch without forcing overflow.
- Skill creation stays pending across creation and resource upload, preventing a
  second creation while files are still being sent.
- Loading buttons retain their accessible name. Unavailable link-backed buttons
  prevent activation without breaking the single-child Slot contract.

## Scope

Shared controls: Button, Input, Textarea, Select, Checkbox, FormField, Progress,
Popover, DropdownMenu, Tooltip, AlertDialog, ConfirmDialog and DateRangePicker.

Primary waiting actions are connected in agent creation; project creation,
settings and file editing; skill creation, editing and file operations; context
creation/editing; channel registration/editing; API key creation; directory
mapping; group sharing; and watches. Existing controls with their own contextual
feedback are not replaced just to increase the changed-file count.

## Verification

Focused batches: 56 tests for primitives and skill creation, 129 for project,
skill and context workflows, and 80 for agent/channel/key/watch creation and
Quick Ask. Assertions cover retained action names, duplicate submission refusal,
keyboard/click activation, mixed checkboxes, locale output, progress semantics,
label association and upload completion. The full suites and their coverage gates
remain CI work. A visual review remains outstanding under the no-Computer-Use
constraint.


## File browsing follow-up

The project drop hint is now local and ignores pointer hit testing. Capture-phase
drop cleanup also clears it when a folder consumes the drop. Window drop, drag
end and blur clean up cancelled drags. Child transitions preserve folder
highlighting, including a coordinate fallback when WebKit supplies no related
target. A collapsed destination opens after 600ms; leaving cancels its timer.
External files can be uploaded directly into a folder, while internal paths
still use the move endpoint and reject self/descendant destinations.

The tree reserves its action columns instead of animating their width. File
and folder glyphs align at each depth; names use readable body type. Folder
counts are removed. The first upload keeps the empty-project layout until real
files arrive, and the queue shows three entries plus its remaining count.

The shared FileIcon now separates source code, JSON, markup, PDF, text documents,
spreadsheets, archives, media and unknown formats. RAG document rows, retrieval
results, legacy chat attachments, context mentions/cards and skill trees use the
same renderer as modern attachment cards and workspace files. This reuses
Lucide marks and the existing FileKind classifier, without an icon dependency
or a second extension registry.

Desktop spacing uses the existing 28px main drag strip plus a 16px content inset,
instead of 32px. The macOS controls row is 32px instead of 48px. These are CSS
token calculations; the supplied screenshot motivated the change, and no
computer automation was used to inspect its rendered result.

Verification: 136 focused file-workflow tests, a separate 311-test file/chat/icon
batch and a 49-test drag regression recheck passed. Frontend lint and typing,
translation fingerprints, generated Architect guide checks and CSS compilation
passed. The local project route returned HTTP 200. These checks do not establish
physical-device drag performance or full visual QA.


## Quick Ask attachments and focus

The small panel now shares the existing chat file API and attachment chips. A
paperclip, image paste and file drop feed the same upload path. Pending cards
reserve their place; sending and New chat wait for completion. Upload errors keep
the draft and name the failed file. Files can be removed or sent without text.
Account and organization changes invalidate in-flight results. Upload size uses
the deployment's public chat limit.

The native panel remains always on top; pinning changes only dismissal on blur.
The pin survives page reloads within the current app session. Explicit close,
Escape in the composer and the global shortcut still hide it. The system file
chooser temporarily holds the panel open, including on cancellation. Focus-policy
commands are granted only to Quick Ask and verify the calling window. HTML file
drops are enabled for this panel rather than interpreted as native file paths.

The agent menu now focuses its group on opening. Deliberate arrow/Home/End
navigation moves to agent options with an inset keyboard indicator; no clipped
outline is applied automatically to the first row. Existing selection and default
agent actions remain separate.

Verification: 96 focused frontend tests cover uploads, image paste, file drops,
removal, file-only sending, cancellation, failed/oversized uploads, account changes,
pinning failures and keyboard selection. Native focus-policy and capability tests,
Clippy, frontend lint and debug packaging complete the code checks. No browser or
Computer Use was performed; the native UI remains available for manual assessment.

Composer follow-up: use a 32 px one-line input (24 px line plus 4 px top/bottom
padding), matching the adjacent 32 px attachment and send controls. Remove their
extra bottom margins. The textarea can still grow for multiple lines, leaving
controls at its bottom edge. Header actions share a 32 px height.


## Desktop drop delivery correction

The earlier DOM-only tests missed the native handoff. Tauri's default Wry drag
handler returns true after emitting its native event, consuming the macOS drop;
the main console did not subscribe to that event. The console window now disables
that handler, as Quick Ask already does, leaving DOM uploads and moves in control.
Blobby and Dock still use their existing native handlers. This is based on the
installed Tauri/Wry implementation, rather than an inferred CSS problem.

Blank areas of both file panes now target the project root. Dropping on a file
uses its containing folder, so its visible row is no longer a dead target. Invalid
moves stop bubbling and show a refused cursor. The upload hint is a small corner
label instead of a banner over the tree. Focused regression tests cover these
additional targets, along with existing nested/drop-cancellation behavior. Native
packaging checks the builder change; no Computer Use was performed.
