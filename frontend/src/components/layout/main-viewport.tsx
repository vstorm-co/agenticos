"use client";

import { useRef, type ReactNode } from "react";
import { useConsoleTitle } from "@/hooks/use-console-title";
import { usePathname } from "next/navigation";
import { stripLocale } from "@/lib/active-route";
import { cn } from "@/lib/utils";

/** The frame owns page insets; chat uses its own draggable header and full area. */
export function MainViewport({ children }: { children: ReactNode }) {
  const main = useRef<HTMLElement>(null);
  useConsoleTitle(main);
  const chat = stripLocale(usePathname()) === "/chat";
  return (
    <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
      {chat && <div aria-hidden className="chat-window-drag-region" data-tauri-drag-region />}
      {!chat && <div aria-hidden className="window-drag-strip" data-tauri-drag-region />}
      <main
        ref={main}
        id="main"
        tabIndex={-1}
        className={cn(
          "relative flex min-h-0 min-w-0 flex-1 flex-col",
          chat
            ? "overflow-hidden p-0"
            : "overflow-auto px-3 pt-(--page-inset-top) [--page-inset-top:0.5rem] sm:px-6 sm:[--page-inset-top:1.25rem]",
        )}
      >
        {children}
      </main>
    </div>
  );
}
