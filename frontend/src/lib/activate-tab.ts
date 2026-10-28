/**
 * Switch a Radix tab from script, by its trigger element.
 *
 * A `Tabs.Trigger` selects on a primary-button `mousedown` and, in the automatic
 * activation mode this app's tabs use, on `focus` — never on a bare
 * `HTMLElement.click()`, which dispatches only a `click` event and moves no
 * focus. So a script clicking a tab did nothing: the panel stayed unmounted and
 * whatever waited for a control inside it - the walkthrough's next spotlight, the
 * Architect's pointer - hunted a target that never appeared. Firing both what
 * Radix listens to (a `mousedown`, and focus) covers either activation mode.
 * `preventScroll` because the caller does the scrolling; a second one here only
 * fights it.
 *
 * `moveFocus: false` leaves focus where it is and relies on the `mousedown`
 * alone, which selects a Radix tab in either mode: for a caller whose reader is
 * typing elsewhere, such as in the Architect's panel.
 *
 * Shared by the onboarding walkthrough and the Architect's "show me where"
 * (`assistant-highlight.ts`), so the two cannot drift apart again.
 */
export function activateTab(
  trigger: HTMLElement,
  { moveFocus = true }: { moveFocus?: boolean } = {},
): void {
  // A popover's trigger opens on a click, not a press: the chat's settings, whose
  // approval-mode and connection stops sit inside it, waited out their timeout
  // behind a closed popover and the walk stood still between them.
  if (trigger.getAttribute("aria-haspopup") === "dialog") {
    trigger.click();
    return;
  }
  trigger.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
  if (moveFocus) trigger.focus({ preventScroll: true });
}
