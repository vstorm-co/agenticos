import { driver, type Driver } from "driver.js";

/**
 * The spotlight overlay, wrapping driver.js so the rest of the tour never touches
 * it directly.
 *
 * driver.js is used for the dimmed overlay and the cut-out around one control —
 * never its popover. The tour's own docked panel carries the copy and the
 * buttons, and that split is deliberate: a popover anchors to an element that can
 * scroll off-screen or unmount when the tour navigates to the next page, where a
 * fixed panel spanning the foot of the window does neither.
 *
 * Lives under `components/onboarding` rather than in a hook because it is DOM
 * work — `document`, a `MutationObserver`, a live third-party overlay — and the
 * hook layer is held to a 100% line-coverage gate this could only meet by
 * asserting on driver.js's internals.
 */
export interface Spotlight {
  /** Dim the page and cut a hole around `element`; moves the hole on repeat calls. */
  show: (element: Element) => void;
  /** Remove the overlay and forget the instance, so the next `show` builds a fresh one. */
  destroy: () => void;
}

export function createSpotlight(): Spotlight {
  let instance: Driver | null = null;
  return {
    show: (element) => {
      instance ??= driver({
        allowClose: false,
        overlayColor: "#0a0a0a",
        overlayOpacity: 0.55,
        stagePadding: 8,
        stageRadius: 10,
      });
      instance.highlight({ element });
    },
    destroy: () => {
      instance?.destroy();
      instance = null;
    },
  };
}

/**
 * Resolve once `selector` is in the document, or with `null` if the wait is
 * aborted or `timeoutMs` elapses first.
 *
 * A step's target only exists after its page has mounted, which is a navigation
 * and a render away — so the engine cannot query for it synchronously. The
 * `MutationObserver` catches it the moment it appears; the timeout keeps a step
 * whose target never renders (a control a permission hid, a slow page) from
 * hanging the spotlight forever; and the abort signal drops the wait when the
 * reader moves to another step before this one's element arrived.
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
