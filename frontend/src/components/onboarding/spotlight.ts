import { driver, type Driver } from "driver.js";

/**
 * A driver.js instance configured for the tour, so the rest of the feature never
 * touches the library's config directly.
 *
 * The tour uses driver.js the way it is meant to be used: an element is
 * spotlighted and a popover is anchored to it with the step's caption. The tour
 * drives it one step at a time with `highlight()` rather than handing it the
 * whole step array, because the steps span pages and driver.js runs within one —
 * so navigation between a page's last step and the next page's first is the
 * caller's job (`onboarding-tour.tsx`), and the popover's Next/Back/close are
 * wired to the caller's handlers per step.
 *
 * `allowClose: false` stops an overlay click or Escape from closing the tour by
 * accident; the popover's own close button is what dismisses it, wired
 * explicitly. `disableActiveInteraction: true` keeps the spotlighted control
 * inert while it is only being described — the interactive tutorial that lets the
 * reader actually use it is a later, separate mode. `popoverClass` is what pins
 * the popover to a fixed spot at the bottom (see `globals.css`): the text and its
 * Next button hold still for the whole walk, and only the spotlight moves.
 *
 * `animate: false` is what keeps that spotlight move from reading as a blink.
 * With driver's animation on, each transition adds a `driver-fade` that fades the
 * popover and overlay back in, and rebuilds the overlay SVG on every frame of the
 * slide; against a pinned, unchanging caption that whole scene flashes on every
 * step — and a step that reveals a control and then lands on its target flashes
 * twice. Off, driver updates the overlay cut-out in place and the cut-out jumps
 * straight to the next control: the caption never moves, nothing fades, and the
 * only thing that changes is where the light is.
 *
 * Lives under `components/onboarding`, not in a hook: it is DOM and third-party
 * overlay work, and the hook layer is held to a 100% line-coverage gate this
 * could only meet by asserting on driver.js's internals.
 */
export function createTourDriver(): Driver {
  return driver({
    allowClose: false,
    overlayColor: "#0a0a0a",
    overlayOpacity: 0.6,
    stagePadding: 8,
    stageRadius: 10,
    disableActiveInteraction: true,
    animate: false,
    popoverClass: "tour-popover",
  });
}

/**
 * Resolve once `selector` is in the document, or with `null` if the wait is
 * aborted or `timeoutMs` elapses first.
 *
 * A step's target only exists after its page has mounted and its data has
 * settled, which is a navigation and a render or two away — so the engine cannot
 * query for it synchronously after telling the router to move. The
 * `MutationObserver` catches it the moment it appears; the timeout keeps a step
 * whose target never renders (a slow page, a control a permission hid) from
 * hanging the spotlight; and the abort signal drops the wait when the reader
 * moves to another step before this one's element arrived.
 */
/**
 * Switch a Radix tab from script, by its trigger element.
 *
 * A `Tabs.Trigger` selects on a primary-button `mousedown` and, in the automatic
 * activation mode this app's tabs use, on `focus` — never on a bare
 * `HTMLElement.click()`, which dispatches only a `click` event and moves no
 * focus. So the tour clicking a tab did nothing: the panel stayed unmounted and
 * the next spotlight hunted a target that never appeared, landing centered with
 * no highlight. Firing both what Radix listens to (a `mousedown`, and focus)
 * covers either activation mode. `preventScroll` because driver.js does the
 * scrolling; a second one here only fights it.
 */
export function activateTab(trigger: HTMLElement): void {
  trigger.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
  trigger.focus({ preventScroll: true });
}

/** The class that drives the "clicked" flourish; see `globals.css`. */
const CLICK_PULSE_CLASS = "tour-click-pulse";

/**
 * Play the "clicked" flourish on `element` and hold for `ms`.
 *
 * Adding the class runs a CSS scale pulse (`globals.css`) that reads as the
 * control being pressed; the class is removed once the hold ends so a later
 * highlight of the same element — a Radix tab that stays mounted after it is
 * activated — replays cleanly rather than sitting on a spent animation. Purely
 * visual: `disableActiveInteraction` keeps the control inert, so nothing is
 * really clicked; the tour navigates or switches the tab itself once this
 * resolves. Resolves at once if `signal` is (or becomes) aborted, and clears
 * the class either way.
 */
export function pulse(element: HTMLElement, signal: AbortSignal, ms: number): Promise<void> {
  element.classList.add(CLICK_PULSE_CLASS);
  return delay(ms, signal).finally(() => element.classList.remove(CLICK_PULSE_CLASS));
}

/** Resolve after `ms`, or at once if `signal` is (or becomes) aborted. */
export function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const finish = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    };
    const timer = setTimeout(finish, ms);
    signal.addEventListener("abort", finish);
  });
}

export function waitForElement(
  selector: string,
  signal: AbortSignal,
  timeoutMs = 4000,
): Promise<Element | null> {
  return new Promise((resolve) => {
    const existing = document.querySelector(selector);
    if (existing) {
      resolve(existing);
      return;
    }
    if (signal.aborted) {
      resolve(null);
      return;
    }
    const finish = (element: Element | null) => {
      observer.disconnect();
      clearTimeout(timer);
      signal.removeEventListener("abort", onAbort);
      resolve(element);
    };
    const observer = new MutationObserver(() => {
      const found = document.querySelector(selector);
      if (found) finish(found);
    });
    const timer = setTimeout(() => finish(null), timeoutMs);
    const onAbort = () => finish(null);
    observer.observe(document.body, { childList: true, subtree: true });
    signal.addEventListener("abort", onAbort);
  });
}
