"use client";

import { Search } from "lucide-react";
import { useTranslations } from "next-intl";

import { useMounted } from "@/hooks/use-mounted";

/**
 * Search, written out rather than hidden behind a magnifying glass.
 *
 * It searches nothing itself: it opens the command palette, the one ⌘K already
 * opens, so there is a single set of results to keep honest. A column has the
 * width to say so - and to show the shortcut, which is how anyone learns the
 * shortcut exists.
 */
interface SidebarSearchProps {
  /**
   * The labelled row, or the icon and its shortcut for the footer strip beside
   * language and theme - where the word "Search" would be the only label among
   * four controls that manage without one.
   */
  variant?: "row" | "icon";
}

export function SidebarSearch({ variant = "row" }: SidebarSearchProps) {
  const t = useTranslations("common");

  const open = () => window.dispatchEvent(new CustomEvent("command-palette:open"));

  // The shortcut as a badge beside the glass, which is how anybody learns it
  // exists. Read after mount: the server cannot know which keyboard is on the
  // other end, and a Mac's ⌘ is a symbol where the others name their key.
  const mounted = useMounted();
  const mac = mounted && /Mac|iPhone|iPad/.test(navigator.platform);

  if (variant === "icon") {
    return (
      <button
        type="button"
        onClick={open}
        aria-label={t("search")}
        title={t("search")}
        className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-lg px-2 transition-colors outline-none focus-visible:ring-1"
      >
        <Search className="h-[1.1rem] w-[1.1rem] shrink-0" aria-hidden />
        {mounted && (
          <kbd
            aria-hidden
            className="border-border bg-background text-muted-foreground rounded-md border px-1.5 font-sans text-[11px] leading-5"
          >
            {mac ? "⌘K" : t("searchShortcut")}
          </kbd>
        )}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={open}
      className="text-muted-foreground hover:bg-accent/60 hover:text-foreground focus-visible:ring-ring flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors outline-none focus-visible:ring-1"
    >
      <Search className="h-4 w-4 shrink-0" aria-hidden />
      <span className="flex-1 text-left">{t("search")}</span>
    </button>
  );
}
