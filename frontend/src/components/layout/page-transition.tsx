"use client";

import { usePathname } from "next/navigation";

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
    // whole page scrolls instead of the message pane. Everywhere else it must
    // stay off: with it, a long page overflows this box and parks `main`'s
    // bottom padding mid-content instead of after it.
    <div key={pathname} className={cn("page-enter flex flex-1 flex-col", constrained && "min-h-0")}>
      {children}
    </div>
  );
}
