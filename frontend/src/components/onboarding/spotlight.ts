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
 * reader actually use it is a later, separate mode.
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
    animate: true,
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
