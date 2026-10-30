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
import { localePrefixOf } from "@/lib/locale-routing";
import { defaultLocale } from "@/lib/locales";
import { glideOrJump } from "@/lib/motion";
import { TOUR_STEPS } from "@/lib/onboarding/tour";
import { isRendered } from "@/lib/rendered";

const HIGHLIGHT = "highlight";
const HIGHLIGHT_CLASS = "assistant-highlight";
/** How long a page is given to draw the control before the pointer gives up. */
const WAIT_MS = 4000;
const POLL_MS = 100;
/**
 * How long a link's locale is waited for while the browser stays where it was.
 * The locale cookie can send a link naming one locale to the page in another.
 */
const LOCALE_WAIT_MS = 1500;
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
 * site, the API, a fragment or a path that normalises to another host stay
 * ordinary links.
 *
 * Decided on the parsed URL, never the raw string (#2544): the returned `path`
 * is the normalised one, and dot segments turn `/a/..//evil.example` into the
 * pathname `//evil.example`, which `router.push` would follow off-site in this
 * tab. The parser also reads `/\evil.example` and `/<tab>/evil.example` as
 * another host. The `href` is model-written, so it is treated as hostile.
 */
export function consoleLink(href: string | null, origin: string): ConsoleLink | null {
  if (href === null || !href.startsWith("/")) return null;
  let url: URL;
  try {
    url = new URL(href, origin);
  } catch {
    // `/\[` names a host that does not parse: not a console page either.
    return null;
  }
  if (url.origin !== origin || url.pathname.startsWith("//")) return null;
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
 * The first copy of an anchor that is rendered and outside an inactive tab
 * panel, or `null`. A control behind another tab can already be in the
 * document: Radix keeps an inactive panel as an empty, `hidden` element (the
 * Activity page's anchors are its panels), and the organization page keeps
 * every panel mounted. A column a breakpoint collapses (`hidden lg:block`)
 * holds its anchors too. Counting such a control as found rang an invisible
 * element and never switched its tab.
 */
function findShown(anchor: string): HTMLElement | null {
  const copies = document.querySelectorAll<HTMLElement>(`[data-tour="${CSS.escape(anchor)}"]`);
  return (
    Array.from(copies).find(
      (copy) => !copy.closest('[role="tabpanel"][data-state="inactive"]') && isRendered(copy),
    ) ?? null
  );
}

/** A path without its locale prefix, read in any case as the middleware reads it. */
function withoutLocale(pathname: string): string {
  const locale = localePrefixOf(pathname);
  return locale ? pathname.slice(locale.length + 1) || "/" : pathname;
}

/**
 * Whether the browser is on `page` yet. The router may have added a locale, so
 * a link naming none matches the page in any; a link naming one - an agent's
 * copy of the address bar, or the same page in another language - is waited
 * for in that locale while the browser is still on `left`, the page it was on.
 * The locale is not insisted on once the browser has moved or `localeWaited`:
 * the `NEXT_LOCALE` cookie redirects `/en/agents` to `/pl/agents` for a reader
 * who chose Polish, and that page is never in the locale the link named.
 */
function arrivedAt(page: string, left: string, localeWaited: boolean): boolean {
  const pushed = new URL(page, window.location.origin).pathname;
  const here = window.location.pathname;
  const named = localePrefixOf(pushed);
  const inNamedLocale = named === null || named === (localePrefixOf(here) ?? defaultLocale);
  if (!inNamedLocale && here === left && !localeWaited) return false;
  return withoutLocale(here) === withoutLocale(pushed);
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
  const left = window.location.pathname;
  let revealed = false;
  for (let waited = 0; waited <= WAIT_MS; waited += POLL_MS) {
    const arrived = arrivedAt(page, left, waited >= LOCALE_WAIT_MS);
    const element = arrived ? findShown(anchor) : null;
    if (element) {
      element.scrollIntoView({ block: "center", behavior: glideOrJump() });
      element.classList.add(HIGHLIGHT_CLASS);
      setTimeout(() => element.classList.remove(HIGHLIGHT_CLASS), RING_MS);
      return true;
    }
    if (tab && !revealed && arrived) {
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
