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

const DESKTOP_PLATFORMS = ["macos", "windows", "linux"] as const;

/** Desktop starts with native glass; browser and phone keep their existing look. */
export function defaultLook(platform: unknown): Look {
  return DESKTOP_PLATFORMS.some((known) => known === platform) ? "glass" : "standard";
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
 * theme store's persisted shape (`{"state":{"look":…}}`), the shell's
 * announcement (`window.__AGENTICOS_SHELL__`) and the Android app's measured
 * status bar (`window.AgenticOSInsets`), and `appearance.test.ts` runs it
 * against the same cases the store and `parseShellInfo` answer. Unreadable storage
 * keeps the platform default until the user chooses another look.
 */
export const APPEARANCE_BOOTSTRAP_SCRIPT =
  "(function(){var d=document.documentElement,h=window.__AGENTICOS_SHELL__;" +
  `var l=${JSON.stringify(DESKTOP_PLATFORMS)}.indexOf(h&&h.platform)>=0?"glass":"standard";try{` +
  `var s=JSON.parse(localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)})||"{}").state;` +
  `if(s&&${JSON.stringify(LOOKS)}.indexOf(s.look)>=0)l=s.look` +
  `}catch(e){}if(l!=="standard")d.setAttribute(${JSON.stringify(LOOK_ATTRIBUTE)},l);` +
  'if(h&&typeof h.platform==="string"){' +
  `d.setAttribute(${JSON.stringify(SHELL_ATTRIBUTE)},h.platform);` +
  `d.setAttribute(${JSON.stringify(SHELL_WINDOW_ATTRIBUTE)},String(h.window));` +
  `if(h.vibrancy===true)d.setAttribute(${JSON.stringify(VIBRANCY_ATTRIBUTE)},"")` +
  // The Android app's status bar and gesture bar, measured by the app: its
  // WebView reports no safe area, and both differ between phones.
  ";try{var i=window.AgenticOSInsets,t=i&&Number(i.top()),b=i&&Number(i.bottom());" +
  'if(t>0)d.style.setProperty("--shell-inset-top",t+"px");' +
  'if(b>0)d.style.setProperty("--shell-inset-bottom",b+"px")}catch(e){}' +
  "}})()";
