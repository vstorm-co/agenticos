/**
 * The console's style - its look - as a value both halves of the app can read.
 *
 * Server-safe for the same reason `motion-preference.ts` is: the root layout's
 * no-flash script is built from these constants, and a server component that
 * imported them from the `"use client"` theme store would receive client
 * references instead of strings.
 *
 * A look is a set of colour tokens (`globals.css`, `[data-look=…]`), orthogonal
 * to light and dark: every look has both. Glass is the one that also asks
 * something of the window - in the desktop app a translucent material behind
 * it, in a browser its own approximation over a soft backdrop.
 */

export const LOOKS = ["standard", "glass", "graphite", "midnight", "paper"] as const;
export type Look = (typeof LOOKS)[number];

export function isLook(value: unknown): value is Look {
  return typeof value === "string" && (LOOKS as readonly string[]).includes(value);
}

/** The `localStorage` key the theme store persists the theme and the look under. */
export const THEME_STORAGE_KEY = "theme-storage";

/** The attribute on `<html>` every look's tokens key off. */
export const LOOK_ATTRIBUTE = "data-look";

/** Set to the platform (`macos`, …) when the page is inside the desktop app. */
export const SHELL_ATTRIBUTE = "data-shell";

/** Which of the app's windows the page is drawn in: `main`, `blobby` or `quick-ask`. */
export const SHELL_WINDOW_ATTRIBUTE = "data-shell-window";

/** Present when the window draws a real material behind a glass console. */
export const VIBRANCY_ATTRIBUTE = "data-vibrancy";

/**
 * Sets the look, and the shell's attributes, on `<html>` before the first paint.
 *
 * Both decide the first frame. A glass console paints its background
 * transparent over the window's material, and a page inside the shell leaves
 * room for the traffic lights and is dragged by its own header; set a frame
 * late, the window flashes opaque or the sidebar jumps sideways. It reads the
 * theme store's persisted shape (`{"state":{"look":…}}`) and the shell's
 * announcement (`window.__AGENTICOS_SHELL__`), and `appearance.test.ts` runs it
 * against the same cases the store and `parseShellInfo` answer. Storage that
 * throws leaves the look to `ThemeProvider`, which sets it once the app hydrates.
 */
export const APPEARANCE_BOOTSTRAP_SCRIPT =
  "(function(){var d=document.documentElement;try{" +
  `var s=JSON.parse(localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)})||"{}").state;` +
  `var l=s&&s.look;if(${JSON.stringify(LOOKS)}.indexOf(l)>0)d.setAttribute(${JSON.stringify(LOOK_ATTRIBUTE)},l)` +
  "}catch(e){}" +
  'var h=window.__AGENTICOS_SHELL__;if(h&&typeof h.platform==="string"){' +
  `d.setAttribute(${JSON.stringify(SHELL_ATTRIBUTE)},h.platform);` +
  `d.setAttribute(${JSON.stringify(SHELL_WINDOW_ATTRIBUTE)},String(h.window));` +
  `if(h.vibrancy===true)d.setAttribute(${JSON.stringify(VIBRANCY_ATTRIBUTE)},"")` +
  "}})()";
