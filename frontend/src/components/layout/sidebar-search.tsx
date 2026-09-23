"use client";

import { Search } from "lucide-react";
import { useTranslations } from "next-intl";

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

  /* No shortcut chip. It taught `⌘K` once and then sat in the column forever,
     and in the icon row it made search the one control wider than the rest -
     an icon and a badge among single icons. The palette still opens on `⌘K`,
     and it says so on its own placeholder, which is where somebody who has
     just opened it can actually use the reminder. */

  if (variant === "icon") {
    return (
      <button
        type="button"
        onClick={open}
        aria-label={t("search")}
        className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors outline-none focus-visible:ring-1"
      >
        <Search className="h-[1.1rem] w-[1.1rem] shrink-0" aria-hidden />
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
