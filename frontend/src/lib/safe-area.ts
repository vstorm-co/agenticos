/**
 * Padding for a surface that covers the whole window.
 *
 * `viewportFit: "cover"` draws the page beneath a phone's status bar, home
 * indicator and - in landscape - its notch; a desktop main window draws it
 * beneath its title-bar row. The console's shell clears them; a surface that
 * leaves it for the whole screen - a side panel on a phone, an expanded view -
 * does not, and its header with the close button sat beneath the clock.
 *
 * The edges come from `desktop.css`: `--fullscreen-inset-top` (status bar or
 * title-bar row) and `--safe-bottom` (the safe area, or the gesture bar the
 * Android app measures, which its WebView does not report). The sides are the
 * safe area, non-zero only beside a landscape notch.
 *
 * Whole strings, not built from parts, so Tailwind finds them when it scans.
 */
export const FULLSCREEN_SAFE =
  "pt-[var(--fullscreen-inset-top,0px)] pb-[var(--safe-bottom,0px)] pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]";

/** The same for a surface padded `p-4 sm:p-6`, keeping that gutter inside the insets. */
export const FULLSCREEN_SAFE_PADDED =
  "pt-[calc(1rem+var(--fullscreen-inset-top,0px))] pb-[calc(1rem+var(--safe-bottom,0px))] pl-[calc(1rem+env(safe-area-inset-left))] pr-[calc(1rem+env(safe-area-inset-right))] sm:pt-[calc(1.5rem+var(--fullscreen-inset-top,0px))] sm:pb-[calc(1.5rem+var(--safe-bottom,0px))] sm:pl-[calc(1.5rem+env(safe-area-inset-left))] sm:pr-[calc(1.5rem+env(safe-area-inset-right))]";
