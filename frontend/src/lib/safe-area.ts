/**
 * Padding for a surface that covers the whole window.
 *
 * `viewportFit: "cover"` draws the page beneath a phone's status bar and home
 * indicator, and the desktop app draws it beneath its title bar
 * (`--shell-inset-top`). The console's shell clears both; a surface that leaves
 * it for the whole screen - a side panel on a phone, an expanded view - does
 * not, and its header with the close button sat beneath the clock, out of reach.
 *
 * Whole strings, not built from parts, so Tailwind finds them when it scans.
 */
export const FULLSCREEN_SAFE =
  "pt-[max(var(--shell-inset-top,0px),env(safe-area-inset-top))] pb-[env(safe-area-inset-bottom)]";

/** The same for a surface padded `p-4 sm:p-6`, keeping that gutter inside the insets. */
export const FULLSCREEN_SAFE_PADDED =
  "pt-[calc(1rem+max(var(--shell-inset-top,0px),env(safe-area-inset-top)))] pb-[calc(1rem+env(safe-area-inset-bottom))] sm:pt-[calc(1.5rem+max(var(--shell-inset-top,0px),env(safe-area-inset-top)))] sm:pb-[calc(1.5rem+env(safe-area-inset-bottom))]";
