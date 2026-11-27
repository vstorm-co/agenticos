"use client";

import { useEffect, useRef } from "react";
import { Globe } from "lucide-react";
import { useTranslations } from "next-intl";
import type { EnvironmentTabs } from "@/lib/environment-stream";
import { cn } from "@/lib/utils";

/** Real retained pages; activation saves remote state, so arrows only move focus. */
export function BrowserPageTabs({
  tabs,
  disabled,
  busy = false,
  onActivate,
  panelId,
  id,
}: {
  tabs: EnvironmentTabs;
  disabled: boolean;
  busy?: boolean;
  onActivate: (id: string) => void;
  panelId: string;
  id: string;
}) {
  const t = useTranslations("browse");
  const strip = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const selected = strip.current?.querySelector<HTMLElement>('[aria-selected="true"]');
    selected?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [tabs.active_tab_id]);
  return (
    <div
      ref={strip}
      role="tablist"
      tabIndex={-1}
      aria-label={t("openPages")}
      aria-busy={busy || undefined}
      className="bg-muted/25 flex shrink-0 scrollbar-thin gap-0.5 overflow-x-auto border-b px-1 pt-1"
      onKeyDown={(event) => {
        if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
        const buttons = Array.from(
          event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
        );
        const current = buttons.findIndex((button) => button === document.activeElement);
        if (current < 0) return;
        event.preventDefault();
        const index =
          event.key === "Home"
            ? 0
            : event.key === "End"
              ? buttons.length - 1
              : (current + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
        buttons[index]?.focus();
      }}
    >
      {tabs.tabs.map((tab, index) => {
        const selected = tab.id === tabs.active_tab_id;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`${id}-${index}`}
            aria-controls={panelId}
            aria-selected={selected}
            aria-disabled={disabled || undefined}
            tabIndex={selected || (tabs.active_tab_id === null && index === 0) ? 0 : -1}
            title={tab.url || tab.title || t("untitledPage")}
            onClick={() => {
              if (!disabled && !selected) onActivate(tab.id);
            }}
            className={cn(
              "focus-visible:ring-ring relative flex h-8 max-w-52 min-w-28 shrink-0 items-center gap-2 rounded-t-md border border-b-2 px-3 text-xs outline-none focus-visible:ring-2 focus-visible:ring-inset pointer-coarse:min-h-11",
              selected
                ? "border-border border-b-foreground bg-background text-foreground"
                : "text-muted-foreground hover:bg-muted/60 border-transparent",
              disabled && "cursor-default",
            )}
          >
            <Globe className="size-3 shrink-0" aria-hidden />
            <span className="truncate">{tab.title || tab.url || t("untitledPage")}</span>
          </button>
        );
      })}
    </div>
  );
}
