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

  /* Meaningless on the viewport where this is a slide-over, and there is no
     keyboard to press it with. */
  const shortcut = (
    <kbd
      aria-hidden
      className="border-border hidden rounded border px-1 py-px font-mono text-[10px] md:inline-block"
    >
      ⌘K
    </kbd>
  );

  if (variant === "icon") {
    return (
      <button
        type="button"
        onClick={open}
        aria-label={t("search")}
        className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring flex h-9 items-center gap-1.5 rounded-lg px-2 transition-colors outline-none focus-visible:ring-1"
      >
        <Search className="h-[1.1rem] w-[1.1rem] shrink-0" aria-hidden />
        {shortcut}
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
      {shortcut}
    </button>
  );
}
