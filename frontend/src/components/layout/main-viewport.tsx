"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { stripLocale } from "@/lib/active-route";
import { cn } from "@/lib/utils";

/** The frame owns page insets; chat uses its own draggable header and full area. */
export function MainViewport({ children }: { children: ReactNode }) {
  const chat = stripLocale(usePathname()) === "/chat";
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {!chat && <div aria-hidden className="window-drag-strip" data-tauri-drag-region />}
      <main
        id="main"
        tabIndex={-1}
        className={cn(
          "relative flex min-h-0 flex-1 flex-col overflow-auto",
          chat
            ? "p-0"
            : "px-3 pt-(--page-inset-top) [--page-inset-top:1rem] sm:px-6 sm:[--page-inset-top:2rem]",
        )}
      >
        {children}
      </main>
    </div>
  );
}
