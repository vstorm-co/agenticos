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
        className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring touch:min-h-11 touch:min-w-11 relative flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors outline-none focus-visible:ring-1"
      >
        <Search className="h-[1.1rem] w-[1.1rem] shrink-0" aria-hidden />
        {/* In the corner, as a count sits on an icon: the button keeps the bell's
            size, and the shortcut is a superscript to it rather than a second
            control beside it. */}
        {mounted && (
          <kbd
            aria-hidden
            // No keyboard shortcut to show on a touch screen.
            className="bg-background text-muted-foreground ring-border touch:hidden absolute -top-0.5 -right-1 rounded px-0.5 font-sans text-[9px] leading-3 ring-1"
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
      className="text-foreground/85 bg-background/60 hover:bg-card hover:text-foreground focus-visible:ring-ring touch:min-h-11 border-foreground/10 flex min-h-9 w-full items-center gap-2.5 rounded-xl border px-2.5 py-2 text-sm transition-colors outline-none focus-visible:ring-2"
    >
      <Search className="h-4 w-4 shrink-0" aria-hidden />
      <span className="flex-1 text-left">{t("search")}</span>
      {mounted && (
        <kbd aria-hidden className="touch:hidden text-muted-foreground text-[11px]">
          {mac ? "⌘K" : t("searchShortcut")}
        </kbd>
      )}
    </button>
  );
}
