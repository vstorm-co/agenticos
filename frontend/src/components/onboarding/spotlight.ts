import { driver, type Driver } from "driver.js";

import { prefersReducedMotion } from "@/lib/motion";
import { isRendered } from "@/lib/rendered";

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
 * What the reader sees of the light is not driver.js's: `tour-spotlight.ts`
 * draws the dim, the cut-out and the ring. driver.js's own overlay stays — it is
 * the click shield `allowClose: false` relies on — but at `overlayOpacity: 0`, and
 * with `animate: false` so it does not run a glide nobody can see. Off, driver.js
 * also builds the caption in the same tick as the highlight rather than halfway
 * through a transition, so the pinned text swaps the moment the step does.
 *
 * Lives under `components/onboarding`, not in a hook: it is DOM and third-party
 * overlay work, and the hook layer is held to a 100% line-coverage gate this
 * could only meet by asserting on driver.js's internals.
 */
export function createTourDriver(): Driver {
  return driver({
    allowClose: false,
    overlayOpacity: 0,
    stagePadding: 8,
    stageRadius: 10,
    disableActiveInteraction: true,
    animate: false,
    popoverClass: "tour-popover",
  });
}

// The reader's Motion preference resolved against the system's - the one answer
// every surface reads (`lib/motion`), offered here for the tour that imports it.
export { prefersReducedMotion };

/**
 * Scroll `element` to the middle of its scroller when `cover` sits over it.
 *
 * The caption is pinned to one spot rather than anchored to the control, so a
 * control near that edge of the page — the Knowledge row low in the builder's
 * capability list — lands underneath the caption describing it. driver.js only
 * scrolls a control that is off screen, and this one is on screen, just covered.
 */
export function keepClearOf(element: Element, cover: Element | null): void {
  if (cover === null) return;
  const a = element.getBoundingClientRect();
  const b = cover.getBoundingClientRect();
  const overlaps = a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
  if (overlaps) element.scrollIntoView({ block: "center", inline: "nearest" });
}

/**
 * Whether a key event landed somewhere the reader is composing text.
 *
 * Arrow keys step the walkthrough, but inside a create dialog the same keys move
 * a caret — and the coach guides the reader *into* those fields, so a step-on-
 * arrow that did not ask this would make the name field unusable. A Radix select
 * counts too: it navigates its own options with the arrows.
 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return true;
  // The attribute rather than `isContentEditable`, which jsdom does not implement —
  // the property is always false there, so a rule written on it could not be tested.
  return (
    target.closest(
      '[contenteditable="true"], [role="combobox"], [role="listbox"], [role="menu"]',
    ) !== null
  );
}

/**
 * Open every collapsed disclosure between `element` and the document, so a
 * control inside one can actually be seen.
 *
 * A `<details>` keeps its content in the document while hiding it, so the wait
 * above finds the control, the ring frames a zero-height box, and the reader is
 * told to pick from a list that is not on screen. The builder's model picker is
 * exactly that: with permission to add a model it shows the add form, and the
 * saved models the step points at sit behind a "use a saved model" disclosure —
 * so the walk stopped dead on "choose its model" with nothing to choose from.
 */
export function revealDisclosures(element: Element): void {
  for (let node: Element | null = element; node !== null; node = node.parentElement) {
    if (node instanceof HTMLDetailsElement) node.open = true;
  }
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

/**
 * An SVG path that fills the whole viewport except a rounded-rect hole over the
 * spotlighted control, wound so an `evenodd` fill leaves the hole transparent.
 *
 * The interactive coach paints this as its freeze layer: the filled area takes
 * pointer events and blocks the frozen page, while the unfilled hole passes
 * clicks straight through to the real control beneath it, which shows at full
 * brightness. It is the same cut-out driver.js draws for the passive tour,
 * rebuilt here because the coach cannot borrow driver's overlay — driver's sits
 * above everything and would dim the create dialog the reader has to use.
 *
 * `radius` is clamped to half the hole's smaller side, so a control narrower or
 * shorter than the corner never inverts the arcs into a bow-tie.
 */
export function spotlightPath(
  viewportWidth: number,
  viewportHeight: number,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
): string {
  const r = Math.max(0, Math.min(radius, width / 2, height / 2));
  const across = width - r * 2;
  const down = height - r * 2;
  return (
    `M${viewportWidth},0 L0,0 L0,${viewportHeight} L${viewportWidth},${viewportHeight} L${viewportWidth},0 Z ` +
    `M${x + r},${y} h${across} a${r},${r} 0 0 1 ${r},${r} v${down} ` +
    `a${r},${r} 0 0 1 -${r},${r} h-${across} a${r},${r} 0 0 1 -${r},-${r} ` +
    `v-${down} a${r},${r} 0 0 1 ${r},-${r} z`
  );
}

/** The first match that is actually rendered, or `null` when none is. */
function findVisible(selector: string): Element | null {
  for (const candidate of document.querySelectorAll(selector)) {
    if (isRendered(candidate)) return candidate;
  }
  return null;
}

/**
 * The document holds the control, but renders none of the copies it holds.
 *
 * Which is the one recoverable case: the surface carrying it is collapsed rather
 * than absent, so something can be opened and the wait will then find it. The
 * coach uses it to open the navigation drawer on a viewport where the desktop
 * column is `display: none` — see `onboarding-coach.tsx`.
 */
export function onlyHiddenMatches(selector: string): boolean {
  return document.querySelector(selector) !== null && findVisible(selector) === null;
}

/**
 * Resolve with the first *rendered* element matching `selector`, or `null` when
 * the wait ends without one. `timeoutMs` bounds the wait; pass `null` for no
 * timeout, so only the `signal` aborting (a step change, the flow ending) ends it —
 * what the coach wants for a target that must appear rather than be skipped, where
 * a fixed deadline would strand the freeze with no cut-out and no way forward.
 *
 * A hidden match is skipped rather than returned: a control the reader cannot see
 * is one they cannot operate, and pointing the walk at it is worse than waiting for
 * the copy that is on screen (`isRendered`).
 */
export function waitForElement(
  selector: string,
  signal: AbortSignal,
  timeoutMs: number | null = 4000,
): Promise<Element | null> {
  return new Promise((resolve) => {
    const existing = findVisible(selector);
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
      if (timer !== null) clearTimeout(timer);
      signal.removeEventListener("abort", onAbort);
      resolve(element);
    };
    // Attributes as well as nodes: a match already in the document becomes
    // visible when a class or a style changes on it or on an ancestor - the
    // navigation sheet opening, a tab panel being revealed - and a childList
    // watch alone never sees that.
    const observer = new MutationObserver(() => {
      const found = findVisible(selector);
      if (found) finish(found);
    });
    const timer = timeoutMs === null ? null : setTimeout(() => finish(null), timeoutMs);
    const onAbort = () => finish(null);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["class", "style", "hidden", "data-state"],
    });
    signal.addEventListener("abort", onAbort);
  });
}
