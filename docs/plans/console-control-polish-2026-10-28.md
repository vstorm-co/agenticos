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
