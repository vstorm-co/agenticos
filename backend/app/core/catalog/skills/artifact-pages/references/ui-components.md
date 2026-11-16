# A small UI kit, chosen for this App

Read `templates/component-studio.html` for working native controls in three visual directions: warm editorial, precise midnight and playful classroom. It is an original, dependency-free reference, not a new platform library. Copy only the pieces the App needs into its self-contained HTML. Do not load a template path as a browser asset or assume a component exists on `AO`.

Use a few semantic design tokens: page, surface, ink, muted, line, accent and on-accent. Maintain a readable type scale, clear focus rings and touch-sized controls. Choose shapes, density and typography to fit the subject; do not apply one dashboard to every report, game or school exercise. Preserve supplied brand rules. A deliberate composition is more useful than arbitrary gradients, glow, glass cards or decorative badges.

| Pattern | Contract |
| --- | --- |
| Primary button | One main action per region; visible pressed/loading/disabled states; a real button for an action and a link for navigation. |
| Secondary/quiet button | Secondary actions stay legible without competing with the primary. Keep destructive confirmation separate. |
| Input/select/range | Visible label, unit and bound; a useful initial value. Show validation beside the field and preserve the typed value after refusal. |
| Choice group | Native radios or buttons with an accurate `aria-pressed`; all choices work by keyboard. Active appearance must match actual state. |
| Dialog | Native `dialog.showModal()` for a short focused task; title, close control, Escape and restored focus. Do not make a static div look modal. |
| Data row | Align comparable values, label units and distinguish missing/zero. Keep an accessible table when the information is tabular. |
| Empty/error/result | Say what happened and what the person can do. Never replace a failed API response with invented sample results. |
| Feedback | A short status update can use `role=status`; approvals and errors that require a decision stay visible inline. Avoid disappearing essential information. |

Keep buttons and inputs stable in the DOM while their values change. Replacing a whole form or selected row with `innerHTML` on each keystroke loses focus and resets input selection. Prefer text updates, class/attribute updates and keyed region changes. Essential report content should exist before optional JavaScript enhancement.

Verify light/dark contrast, phone width, long labels, keyboard-only use, validation and reset. A reusable pattern earns its place through actual working behavior, not by drawing many component specimens.
