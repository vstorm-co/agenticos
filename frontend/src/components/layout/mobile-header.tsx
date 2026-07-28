"use client";

/**
 * The top bar, on the only viewports that still have one.
 *
 * Above `md` there is no header: the brand heads the column, and search, the
 * organization, language, theme and the account moved into it (see
 * `SidebarShell`). Below `md` the column is a slide-over, so a button has to
 * exist to open it - that button and the brand are the whole of this file, and
 * the reason it is named for the viewport rather than for the page.
 */

import { Menu } from "lucide-react";
import { useTranslations } from "next-intl";

import { BrandLink } from "@/components/layout/brand-link";
import { Button } from "@/components/ui";
import { useSidebarStore } from "@/stores";

export function MobileHeader() {
  const { toggle } = useSidebarStore();
  const t = useTranslations("nav");

  return (
    <header className="bg-background/95 supports-[backdrop-filter]:bg-background/70 sticky top-0 z-40 flex h-14 w-full shrink-0 items-center gap-1 border-b px-3 backdrop-blur md:hidden">
      <Button variant="ghost" size="sm" className="h-9 w-9 p-0" onClick={toggle}>
        <Menu className="h-5 w-5" />
        <span className="sr-only">{t("toggleMenu")}</span>
      </Button>
      <BrandLink />
    </header>
  );
}
