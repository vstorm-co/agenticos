# Mobile overlay reference pass — 2026-11-21

This repository-only record connects the supplied design references to the
separately reversible implementation. Videos are references, not instructions.
The existing neutral console palette and semantic status colors remain the design
system. No video, transcript, downloaded software or new UI dependency is bundled.

| Reference | Observation | Applied change |
| --- | --- | --- |
| [Context containers](https://www.facebook.com/watch/?v=1111460338008332), 00:00–00:18 and 00:58–01:07 | Choose the surface for the task; replace a contextual panel rather than stacking it. | Sharing uses a content-sized mobile sheet with a fixed header and scrolling body. The conversation sheet renames inline, replaces its body with sharing and Back, and temporarily yields to search. Destructive confirmations retain a centered dialog. |
| [Elevation](https://www.facebook.com/watch/?v=1691264189015320), 00:00–00:12 and 00:29–00:47 | Combine contact and lift shadows; use a small consistent scale and readable surfaces in dark mode. | Shared floating and dialog shadow tokens use two layers. Command search uses the dialog token instead of an independent shadow. Static gallery cards gain no shadows. |
| [Color hierarchy](https://www.facebook.com/watch/?v=2353636352127882), 00:03–00:28 | Neutral surfaces and limited competing accents clarify the main action. | Preserve the neutral console hierarchy and semantic states. No additional accent palette or literal 60/30/10 pixel allocation is introduced. |
| [Color phenomena](https://www.facebook.com/watch/?v=1209051871452917), 00:00–00:19 | Neighboring colors and opacity affect appearance. | Field edges are derived from their surface and foreground; light and dark are reviewed separately. This is not a claim that every palette/token has passed a contrast audit. |
| [Inputs](https://www.facebook.com/watch/?v=2223199051874939), 00:03–00:34 | Keep labels visible, use comfortable phone fields and visible keyboard focus. | Standard narrow-screen inputs/selects have a 44px minimum. Search inputs use 16px phone text, explicit close controls and focus feedback. Search results own scrolling; headers and actions remain reachable. |

The accompanying requested Voice change removes its inner tabs. Voice calls and
Dictation remain in one vertical list, with the existing permissions, configuration
and preview behavior. Dictation settings remain available while its chat control
is off because connected channels can still use the transcription configuration.

## Interaction contracts

- Keep Radix focus containment and accessible names. Dismissal restores the
  invoker with `preventScroll`; navigation must not restore focus to the old page.
- Escape cancels an inline title edit first. Returning from sharing restores the
  conversation list and its scroll position; opening a panel performs no share.
- Native Close and Retry buttons in command search must not bubble Enter into
  cmdk's result selection handler.
- Use the existing visual-viewport height budget. Header and footer do not scroll
  with results; narrow keyboard-height surrogates are not a real iOS keyboard test.
- Reduced-motion preferences retain immediate, usable state changes. The mobile
  sheet has no drag handle because this change implements no drag gesture.

44px is a product target, not the universal WCAG AA minimum:
[WCAG 2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
uses 24px with exceptions, while
[2.5.5](https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced.html)
describes the enhanced target. Dialog behavior follows the
[ARIA APG modal pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/).
