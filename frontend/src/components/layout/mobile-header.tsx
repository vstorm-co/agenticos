"use client";

/**
 * The top bar, on the only viewports that still have one.
 *
 * Above `md` there is no header: the brand heads the column, and search, the
 * organization, language, theme and the account moved into it (see
 * `SidebarShell`). Below `md` the column is a slide-over, so a button has to
 * exist to open it - that button and the brand are most of this file, and
 * the reason it is named for the viewport rather than for the page.
 *
 * The bell is the one control repeated here rather than left to the drawer:
 * unread state is worth seeing without first opening the column that holds it.
 * The chat has none of it: its own buttons float over the transcript there
 * (`PhoneChatBar`).
 */

import { Menu } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";

import { BrandLink } from "@/components/layout/brand-link";
import { NotificationBell } from "@/components/layout/notification-bell";
import { Button } from "@/components/ui";
import { pageOf } from "@/lib/assistant-bubbles";
import { useSidebarStore } from "@/stores";

export function MobileHeader() {
  const { toggle } = useSidebarStore();
  const onChat = pageOf(usePathname()).startsWith("/chat");
  const t = useTranslations("nav");

  // The chat draws its own top on a phone: buttons floating over the
  // transcript, which gets the whole height (`PhoneChatBar`).
  if (onChat) return null;

  return (
    <header className="bg-background sticky top-0 z-40 flex h-14 w-full shrink-0 items-center gap-1 border-b px-3 md:hidden">
      <Button variant="ghost" size="sm" className="h-11 w-11 p-0" onClick={toggle}>
        <Menu className="h-5 w-5" />
        <span className="sr-only">{t("toggleMenu")}</span>
      </Button>
      <BrandLink />
      <div className="ml-auto flex items-center gap-1">
        <NotificationBell variant="icon" />
      </div>
    </header>
  );
}
