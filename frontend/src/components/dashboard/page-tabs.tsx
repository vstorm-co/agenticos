"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import type { LucideIcon } from "lucide-react";

import { useActiveRoute } from "@/lib/active-route";
import { cn } from "@/lib/utils";

export interface PageTab {
  /**
   * A key in the `nav` namespace, not the word itself.
   *
   * A module-level table cannot call a translator, so it holds the key and the
   * component translates at the point of use - the same shape `NAV_GROUPS`
   * uses. It held the English instead until #425, which rendered the whole
   * `/settings` and `/admin` tab rows in English under every locale while the
   * catalog already had every one of these words.
   */
  labelKey: string;
  href: string;
  icon?: LucideIcon;
  /** Match only the exact path (use for index/overview tabs). */
  exact?: boolean;
}

/**
 * Flat, underline-style horizontal tabs that sit under a PageHeader and replace
 * nested left sidebars. The active state is a bottom border on the tab itself
 * (not an absolutely-positioned bar) so the horizontal scroll container never
 * produces a stray vertical scrollbar. The scrollbar is hidden; tabs scroll
 * horizontally only when they overflow (mobile).
 */
export function PageTabs({ tabs, className }: { tabs: readonly PageTab[]; className?: string }) {
  const isActive = useActiveRoute();
  const t = useTranslations("nav");
  return (
    <div className={cn("border-border border-b", className)}>
      <nav className="-mb-px flex [scrollbar-width:none] gap-0.5 overflow-x-auto [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
        {tabs.map((tab) => {
          const active = isActive(tab.href, tab.exact);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "inline-flex shrink-0 items-center gap-1.5 border-b-2 px-3.5 py-2.5 text-sm font-medium whitespace-nowrap transition-colors",
                active
                  ? "border-foreground text-foreground"
                  : "text-muted-foreground hover:text-foreground border-transparent",
              )}
            >
              {tab.icon && <tab.icon className="h-4 w-4" />}
              {t(tab.labelKey)}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
