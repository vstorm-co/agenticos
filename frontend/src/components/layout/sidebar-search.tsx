"use client";

import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMounted } from "@/hooks/use-mounted";

/** Opens the same command palette as the global keyboard shortcut. */
export function SidebarSearch() {
  const t = useTranslations("common");
  const mounted = useMounted();
  const mac = mounted && /Mac|iPhone|iPad/.test(navigator.platform);
  const shortcut = mac ? "⌘K" : t("searchShortcut");
  return (
    <button
      type="button"
      onClick={() => window.dispatchEvent(new CustomEvent("command-palette:open"))}
      aria-label={t("search")}
      // i18n-exempt: ARIA keyboard shortcut tokens are platform syntax, not translated labels
      aria-keyshortcuts="Meta+K Control+K"
      title={`${t("search")} (${shortcut})`}
      className="pressable-icon text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring touch:min-h-11 touch:min-w-11 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors outline-none focus-visible:ring-2"
    >
      <Search className="size-[18px]" strokeWidth={1.75} aria-hidden />
    </button>
  );
}
