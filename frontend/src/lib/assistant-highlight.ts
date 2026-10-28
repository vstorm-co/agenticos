/**
 * "Show me where" (#2063): a console link the AI Architect wrote, opened in the
 * console rather than in its frame, and the control it names pointed at.
 *
 * The Architect links to a page with a relative path and may add
 * `?highlight=<anchor>`, an anchor being a `data-tour` value - the same names the
 * onboarding walkthrough spotlights, so a control the tour can find, the
 * Architect can point at. An anchor behind a tab is revealed the way the tour
 * reveals it, by activating the tab its step names (`activateTab`: a Radix tab
 * ignores a bare `click()`).
 */

import { activateTab } from "@/lib/activate-tab";
import { stripLocale } from "@/lib/active-route";
import { glideOrJump } from "@/lib/motion";
import { TOUR_STEPS } from "@/lib/onboarding/tour";

const HIGHLIGHT = "highlight";
const HIGHLIGHT_CLASS = "assistant-highlight";
/** How long a page is given to draw the control before the pointer gives up. */
const WAIT_MS = 4000;
const POLL_MS = 100;
/** How long the ring stays: three pulses of the CSS animation. */
const RING_MS = 3000;

export interface ConsoleLink {
  /** The page, with the highlight taken out of its query. */
  path: string;
  /** The `data-tour` anchor to point at, if the link named one. */
  anchor: string | null;
}

/**
 * The console page an `href` names, or `null` for anything else - another
 * site, the API, a protocol-relative URL or a fragment stay ordinary links.
 */
export function consoleLink(href: string | null, origin: string): ConsoleLink | null {
  if (href === null || !href.startsWith("/") || href.startsWith("//")) return null;
  const url = new URL(href, origin);
  // The console's own route handlers are not pages to open.
  if (/^\/api\//.test(url.pathname)) return null;
  const anchor = url.searchParams.get(HIGHLIGHT);
  url.searchParams.delete(HIGHLIGHT);
  return { path: `${url.pathname}${url.search}${url.hash}`, anchor };
}

function find(anchor: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[data-tour="${CSS.escape(anchor)}"]`);
}

/**
 * Whether the browser is on `page` yet. The locale comes off both sides: the
 * router may have added one, and a link an agent copied may already carry one.
 */
function arrivedAt(page: string): boolean {
  const pushed = new URL(page, window.location.origin).pathname;
  return stripLocale(window.location.pathname) === stripLocale(pushed);
}

/**
 * Point at `anchor` once `page` draws it: reveal it, scroll it into view and
 * ring it. Resolves whether it was found; a page that never draws it - the
 * reader may not hold the permission the control needs - is simply not pointed at.
 *
 * `page` is the path the caller has just pushed. Nothing is looked for until
 * the browser is on it: the page being left often holds the same anchor and the
 * same tab trigger (every agent's Builder does), and switching its tab rewrites
 * its URL, which cancels the navigation still in flight.
 */
export async function pointAt(anchor: string, page: string): Promise<boolean> {
  // By the step's id as well: a step may light its card's header while the
  // Architect names the card, and both sit behind the same tab.
  const tab = TOUR_STEPS.find((step) => step.target === anchor || step.id === anchor)?.activate;
  let revealed = false;
  for (let waited = 0; waited <= WAIT_MS; waited += POLL_MS) {
    const element = arrivedAt(page) ? find(anchor) : null;
    if (element) {
      element.scrollIntoView({ block: "center", behavior: glideOrJump() });
      element.classList.add(HIGHLIGHT_CLASS);
      setTimeout(() => element.classList.remove(HIGHLIGHT_CLASS), RING_MS);
      return true;
    }
    if (tab && !revealed && arrivedAt(page)) {
      const trigger = find(tab);
      if (trigger) {
        // A tab switch leaves focus where the reader was typing, in the
        // Architect's panel. A popover still takes it as it opens.
        activateTab(trigger, { moveFocus: false });
        revealed = true;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
  }
  return false;
}
