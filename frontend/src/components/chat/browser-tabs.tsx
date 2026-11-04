"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { Globe } from "lucide-react";
import { useTranslations } from "next-intl";
import type { Browse } from "@/lib/browse";
import { cn } from "@/lib/utils";
import { hostOf } from "./browser-window";

/** The same tab strip in the compact preview and the side panel. */
export function BrowserTabs({
  tabs,
  selected,
  onSelect,
  children,
}: {
  tabs: Browse[];
  selected: string;
  onSelect: (browse: Browse) => void;
  children?: ReactNode;
}) {
  const t = useTranslations("chat");
  const strip = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const list = strip.current;
    const active = list?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!list || !active) return;
    const bounds = list.getBoundingClientRect();
    const tab = active.getBoundingClientRect();
    // Scroll only the strip, keeping the conversation's vertical position intact.
    list.scrollLeft +=
      tab.left < bounds.left ? tab.left - bounds.left : Math.max(0, tab.right - bounds.right);
  }, [selected]);
  return (
    <div className="bg-muted/25 border-border/60 flex shrink-0 items-center gap-1 border-b p-1">
      <div
        ref={strip}
        role="tablist"
        tabIndex={-1}
        aria-label={t("browserHeading")}
        className="flex min-w-0 flex-1 scrollbar-thin gap-0.5 overflow-x-auto"
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const current = tabs.findIndex((tab) => tab.callId === selected);
          const index =
            event.key === "Home"
              ? 0
              : event.key === "End"
                ? tabs.length - 1
                : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
          const tab = tabs[index];
          if (tab) onSelect(tab);
          event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[index]?.focus();
        }}
      >
        {tabs.map((tab) => (
          <button
            type="button"
            role="tab"
            key={tab.callId}
            aria-selected={tab.callId === selected}
            tabIndex={tab.callId === selected ? 0 : -1}
            title={tab.title || tab.url || undefined}
            onClick={() => onSelect(tab)}
            className={cn(
              "flex max-w-44 min-w-0 shrink-0 items-center gap-2 rounded-lg px-2.5 py-2 text-xs transition-colors",
              tab.callId === selected
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:bg-muted",
            )}
          >
            <Globe className="size-3.5 shrink-0" aria-hidden />
            <span className="truncate">{tab.title || hostOf(tab.url) || t("browserHeading")}</span>
          </button>
        ))}
      </div>
      {children}
    </div>
  );
}
