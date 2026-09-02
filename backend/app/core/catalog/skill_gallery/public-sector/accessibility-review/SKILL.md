---
name: Accessibility review
description: Check a public document or page against the standard and say what to fix.
category: qa
---

# Reviewing for accessibility

Public information has to be usable by everybody, and the fix is nearly always
cheap when it is found early.

## Check

Headings in real hierarchy, not visual formatting · alternative text that
conveys the meaning rather than describing the picture · contrast against the
ratio, with the measured value reported · link text that makes sense alone —
never "click here" · tables with real headers, and no layout tables · forms with
associated labels · language attribute set · no meaning carried by colour alone ·
video with captions and audio with a transcript.

## Report with the fix

"Contrast 3.1:1 against a 4.5:1 requirement — darken to #4A4A4A" is actionable.
"Poor contrast" produces another round.

## Prioritise by exclusion

Order by who is shut out entirely, not by count. One unlabelled form field on
the application page outranks twenty decorative images missing alt text.

## Never

Pass a document because it looks fine, or treat a PDF as accessible because it
opens.
