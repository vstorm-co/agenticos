/** Shared by links and imperative router navigation; never owns routing itself. */
export const NAVIGATION_START = "console:navigation-start";

export function navigationDestination(href: string): URL | null {
  let target: URL;
  try {
    target = new URL(href, window.location.href);
  } catch {
    return null;
  }
  const here = window.location;
  if (target.origin !== here.origin) return null;
  if (target.pathname === here.pathname && target.search === here.search) return null;
  return target;
}

export function signalNavigation(href: string): void {
  if (navigationDestination(href)) window.dispatchEvent(new Event(NAVIGATION_START));
}
