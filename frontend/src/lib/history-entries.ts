/**
 * What this app keeps in `history.state` beside the router's own keys, and what
 * it reads from the browser's list of entries.
 *
 * The router stores its tree in `history.state` and copies it into any state the
 * app writes, so a key written here survives the router's own writes - as long
 * as the app's write leaves the router's keys out and lets the router add them.
 */
import { locales } from "@/lib/locales";

/** An entry the unsaved-changes guard pushed: the page again, so Back lands on it first. */
export const HELD_ENTRY = "__unsavedHeld";
/** An entry `useUrlOverlay` pushed for one object opened over its page, keyed by its parameter. */
export const OVERLAY_ENTRY = "__urlOverlay";

const ROUTER_KEYS = new Set(["__NA", "__PRIVATE_NEXTJS_INTERNALS_TREE"]);

/** The current entry's state without the router's keys, which the router fills in itself. */
export function appHistoryState(): Record<string, unknown> {
  const state = (window.history.state as Record<string, unknown> | null) ?? {};
  return Object.fromEntries(Object.entries(state).filter(([key]) => !ROUTER_KEYS.has(key)));
}

/** Signing in and its detours: leaving a page back onto one of these is leaving the app. */
const SIGN_IN_PAGE =
  /^\/(login|register|forgot-password|reset-password|magic-link[^/]*|auth|invitations)(\/|$)/;

/**
 * Whether Back would land on another page of this app, so a way back on screen
 * can take that step instead of opening its logical parent.
 *
 * Read from the Navigation API, which lists only this origin's own entries; a
 * browser without it, a page opened from a link or in a new tab, and an entry
 * of the sign-in pages all answer `false`.
 */
export function previousEntryInApp(): boolean {
  const navigation = (window as { navigation?: Navigation }).navigation;
  const current = navigation?.currentEntry;
  if (!navigation || !current || current.index < 1) return false;
  const previous = navigation.entries()[current.index - 1];
  if (!previous?.url) return false;
  const url = new URL(previous.url);
  if (url.origin !== window.location.origin) return false;
  const [, first = "", ...rest] = url.pathname.split("/");
  const path = (locales as readonly string[]).includes(first.toLowerCase())
    ? `/${rest.join("/")}`
    : url.pathname;
  return !SIGN_IN_PAGE.test(path);
}

let ownTraversal = false;

/**
 * `history.go`, marked as this app's own step - closing what it opened - so the
 * unsaved-changes guard, still holding until the change it guards unmounts,
 * does not read the `popstate` as somebody pressing Back and step again. A
 * second request before that `popstate` arrives is the same step, and ignored.
 */
export function traverseHistory(delta: number): void {
  // One step at a time: a dialog closing and the guard's own way out can both ask for it.
  if (ownTraversal) return;
  ownTraversal = true;
  window.history.go(delta);
}

/** Whether the `popstate` being handled is `traverseHistory`'s; answered once. */
export function takeOwnTraversal(): boolean {
  const own = ownTraversal;
  ownTraversal = false;
  return own;
}
