"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ChevronDown, type LucideIcon } from "lucide-react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui";

import { SCROLL_FADE, useScrollFade } from "@/components/ui/scroll-fade";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
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
  /** Related routes represented by this tab, while retaining their own URLs. */
  matchHrefs?: readonly string[];
  href: string;
  icon?: LucideIcon;
  /** Match only the exact path (use for index/overview tabs). */
  exact?: boolean;
  /** A tab for the desktop app's own settings, left out of the row in a browser and on a phone. */
  shellOnly?: boolean;
}

/**
 * Flat, underline-style horizontal tabs that sit under a PageHeader and replace
 * nested left sidebars. The active state is a bottom border on the tab itself
 * (not an absolutely-positioned bar) so the horizontal scroll container never
 * produces a stray vertical scrollbar. The scrollbar is hidden; tabs scroll
 * horizontally only when they overflow. Dense sections default to a menu;
 * a vertical section index uses the same links on desktop and a menu on phones.
 */
export function PageTabs({
  tabs: allTabs,
  className,
  overflow = "menu",
  layout = "horizontal",
}: {
  tabs: readonly PageTab[];
  className?: string;
  /** Keep the section index visible as a scrollable strip at every screen size. */
  overflow?: "menu" | "scroll";
  layout?: "horizontal" | "vertical";
}) {
  const shell = useShell();
  const routeActive = useActiveRoute();
  const isActive = (href: string, exact?: boolean) => {
    const tab = allTabs.find((item) => item.href === href);
    return (
      routeActive(href, exact) ||
      (tab?.matchHrefs?.some((alias) => routeActive(alias, exact)) ?? false)
    );
  };
  const tabs = isDesktopShell(shell)
    ? allTabs
    : allTabs.filter((tab) => !tab.shellOnly || isActive(tab.href, tab.exact));
  const t = useTranslations("nav");
  const tc = useTranslations("common");
  const strip = useRef<HTMLElement>(null);
  const activeTab = tabs.find((tab) => isActive(tab.href, tab.exact)) ?? tabs[0];
  const activeHref = activeTab?.href;
  const vertical = layout === "vertical";
  const many = vertical || (overflow === "menu" && tabs.length > 4);
  const sectionMenu = !vertical && many && tabs.length > 6;
  useScrollFade(strip);

  // On a phone the strip is wider than the screen, and a tab past its edge -
  // API, opened from a link - was active but out of sight. Centre it, moving
  // only the strip, never the page.
  useEffect(() => {
    if (vertical) return;
    const nav = strip.current;
    const active = nav?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!nav || !active) return;
    const centre = () => {
      nav.scrollLeft = active.offsetLeft - (nav.clientWidth - active.offsetWidth) / 2;
    };
    centre();
    const resize = new ResizeObserver(centre);
    resize.observe(nav);
    return () => resize.disconnect();
  }, [activeHref, vertical]);

  return (
    <div
      className={cn(
        !vertical && "border-border border-b",
        many && "max-md:border-0",
        sectionMenu && "border-0",
        className,
      )}
    >
      {many && activeTab && (
        <div className={sectionMenu ? "w-full md:w-64" : "md:hidden"}>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                className="w-full justify-start"
                aria-label={tc("chooseSection", { section: t(activeTab.labelKey) })}
              >
                {activeTab.icon && <activeTab.icon aria-hidden />}
                {t(activeTab.labelKey)}
                <ChevronDown className="ml-auto" aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              className="w-[var(--radix-dropdown-menu-trigger-width)]"
            >
              {tabs.map((tab) => (
                <DropdownMenuItem key={tab.href} asChild>
                  <Link
                    href={tab.href}
                    aria-current={isActive(tab.href, tab.exact) ? "page" : undefined}
                  >
                    {tab.icon && <tab.icon aria-hidden />}
                    {t(tab.labelKey)}
                  </Link>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}
      <nav
        ref={strip}
        className={cn(
          "relative -mb-px flex min-w-0 [scrollbar-width:none] gap-0.5 overflow-x-auto overscroll-x-contain [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden",
          !vertical && SCROLL_FADE,
          vertical && "mb-0 flex-col overflow-visible",
          many && "hidden md:flex",
          sectionMenu && "md:hidden",
        )}
      >
        {tabs.map((tab) => {
          const active = isActive(tab.href, tab.exact);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "focus-visible:outline-ring touch:min-h-11 inline-flex min-h-9 shrink-0 touch-manipulation items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px]",
                active
                  ? "border-foreground text-foreground"
                  : "text-muted-foreground hover:text-foreground border-transparent",
                vertical && "rounded-lg border-0 px-3 py-2",
                vertical && active && "bg-muted text-foreground",
              )}
            >
              {tab.icon && <tab.icon className="h-4 w-4" aria-hidden />}
              {t(tab.labelKey)}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
