/**
 * How much movement a person wants, as a value both halves of the app can read.
 *
 * Server-safe on purpose: the root layout's no-flash script is built here, and a
 * server component that imported these constants from a `"use client"` store
 * would receive client references instead of strings.
 */

/** Follow the operating system, always reduce, or always animate. */
export type MotionPreference = "system" | "reduce" | "full";

/** The `localStorage` key the motion store persists under. */
export const MOTION_STORAGE_KEY = "motion-storage";

/** The attribute on `<html>` that every reduced-motion CSS rule keys off. */
export const MOTION_ATTRIBUTE = "data-motion";

/** The operating system's own answer, which `"system"` defers to. */
export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

/** Whether a preference reduces motion, given what the operating system asks for. */
export function resolveReducedMotion(
  preference: MotionPreference,
  systemReduces: boolean,
): boolean {
  return preference === "reduce" || (preference === "system" && systemReduces);
}

/**
 * Sets `data-motion="reduce"` on `<html>` before the first paint.
 *
 * The motion store hydrates on the client, after the server's HTML has painted,
 * and every reduced-motion rule in `globals.css` keys off the attribute rather
 * than the media query - so without this the entry animations of the first paint
 * would play for somebody who asked for none. It reads the store's persisted
 * shape (`{"state":{"motion":…}}`) and resolves it exactly as
 * `resolveReducedMotion` does; `motion-preference.test.ts` runs it against the
 * same cases. Storage that throws (blocked, or a corrupt value) leaves the
 * attribute to `MotionProvider`, which sets it once the app hydrates.
 */
export const MOTION_BOOTSTRAP_SCRIPT =
  "(function(){try{" +
  `var s=JSON.parse(localStorage.getItem(${JSON.stringify(MOTION_STORAGE_KEY)})||"{}").state;` +
  'var p=s&&s.motion;if(p==="reduce"||(p!=="full"&&' +
  `window.matchMedia(${JSON.stringify(REDUCED_MOTION_QUERY)}).matches))` +
  `document.documentElement.setAttribute(${JSON.stringify(MOTION_ATTRIBUTE)},"reduce")` +
  "}catch(e){}})()";
