/**
 * Whether the latest navigation went back or forward, for the phone app's
 * page transitions (#2097, item 21): a page pushed slides in from the trailing
 * edge, a page popped from the leading one, as the platform's own do.
 *
 * The browser says only when history was walked (`popstate`); everything else
 * - a link, `router.push` - is a step forward.
 */
export type NavigationDirection = "forward" | "back";

let latest: NavigationDirection = "forward";

if (typeof window !== "undefined") {
  window.addEventListener("popstate", () => {
    latest = "back";
  });
}

let shown: { pathname: string; direction: NavigationDirection } | null = null;

/**
 * The direction `pathname` was arrived at from. Asked again for the page on
 * screen - a re-render - it answers the same; a new page takes the latest walk
 * and resets it, so the step after counts as forward.
 */
export function directionFor(pathname: string): NavigationDirection {
  if (shown?.pathname !== pathname) {
    shown = { pathname, direction: latest };
    latest = "forward";
  }
  return shown.direction;
}
