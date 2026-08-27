"use client";

import { usePathname } from "next/navigation";

import { PAGE_CLEARANCE } from "@/lib/page-clearance";
import { cn } from "@/lib/utils";

/** Routes that scroll inside their own panes, not in `main`. */
const FULL_HEIGHT_ROUTES = /\/(?:chat|runs)(?:\/|$)/;

export function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const constrained = FULL_HEIGHT_ROUTES.test(pathname);

  return (
    // `min-h-0` only on full-height routes. Chat needs the constrained chain:
    // a flex item's `min-height: 0` is a floor, not a ceiling, so the chat
    // page setting it on its own root does NOT stop this box's min-content
    // from growing to the transcript's height - without `min-h-0` here the
    // whole page scrolls instead of the message pane.
    //
    // Everywhere else it stays off, and that is what makes this the one place
    // the room under a page can be declared. `main` scrolls, but `main` is not
    // where its own bottom padding lands: `DeploymentGate` wraps this in a
    // `min-h-0 flex-1` box, so a long page overflows that box and `main`'s
    // padding edge stays where the shorter box ended - buried mid-content,
    // measured at 0px below the last card at every width (#933). This box grows
    // with its content, so padding here is painted after the last element.
    //
    // Not on the constrained branch: chat's composer belongs on the bottom
    // edge, and room beneath it would be a gap under a fixed control.
    <div
      key={pathname}
      className={cn("page-enter flex flex-1 flex-col", constrained ? "min-h-0" : PAGE_CLEARANCE)}
    >
      {children}
    </div>
  );
}
