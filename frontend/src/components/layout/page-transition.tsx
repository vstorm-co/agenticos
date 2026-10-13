"use client";

import { usePathname } from "next/navigation";

import { PAGE_CLEARANCE } from "@/lib/page-clearance";
import { cn } from "@/lib/utils";

/**
 * Routes that scroll inside their own panes, not in `main`.
 *
 * `min-h-0` is what stops this box growing with its content, so the pane below
 * it scrolls instead of the page. Chat needs the constrained chain: a flex
 * item's `min-height: 0` is a floor, not a ceiling, so the chat page setting it
 * on its own root does NOT stop this box's min-content from growing to the
 * transcript's height.
 */
const OWN_SCROLL_PANE = /\/chat(?:\/|$)/;

/**
 * Routes that place their own room under themselves, lower down.
 *
 * Two routes, for two different reasons, and both are about something that has
 * to reach the bottom edge of the viewport:
 *
 * - **`/chat`**, whose composer belongs on that edge. Room beneath a fixed
 *   control is a gap under it, so the page takes none at all.
 * - **`/runs`**, whose run detail is `sticky` beside the list. A sticky box is
 *   clamped to its containing block, so padding *below* that block shortens the
 *   scrollport the panel may pin in: 64px of it put the panel's top at -48px at
 *   maximum scroll and cut its own header off by 56px (#1206). Activity declares
 *   the same `PAGE_CLEARANCE` one level in, on the list column, where it lands
 *   under the last row and leaves the row itself ending at the viewport.
 */
const OWN_BOTTOM_ROOM = /\/(?:chat|runs)(?:\/|$)/;

export function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    // Everywhere else the room under a page is declared here, and this is the
    // one place it paints: `main` scrolls, but `main` is not where its own
    // bottom padding lands - `DeploymentGate` wraps this in a `min-h-0 flex-1`
    // box, so a long page overflows that box and `main`'s padding edge stays
    // where the shorter box ended, buried mid-content and measured at 0px below
    // the last card at every width (#933). This box grows with its content, so
    // padding here is painted after the last element.
    <div
      key={pathname}
      className={cn(
        "page-enter flex flex-1 flex-col",
        OWN_SCROLL_PANE.test(pathname) && "min-h-0",
        !OWN_BOTTOM_ROOM.test(pathname) && PAGE_CLEARANCE,
      )}
    >
      {children}
    </div>
  );
}
