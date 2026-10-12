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
 * On the chat, the conversation list is a second slide-over with no other way
 * in, so its button sits beside the bell there.
 */

import { MessagesSquare, Menu } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";

import { BrandLink } from "@/components/layout/brand-link";
import { NotificationBell } from "@/components/layout/notification-bell";
import { Button, IconButton } from "@/components/ui";
import { pageOf } from "@/lib/assistant-bubbles";
import { useChatSidebarStore, useSidebarStore } from "@/stores";

export function MobileHeader() {
  const { toggle } = useSidebarStore();
  const openConversations = useChatSidebarStore((state) => state.open);
  const onChat = pageOf(usePathname()).startsWith("/chat");
  const t = useTranslations("nav");

  return (
    <header className="bg-background sticky top-0 z-40 flex h-14 w-full shrink-0 items-center gap-1 border-b px-3 md:hidden">
      <Button variant="ghost" size="sm" className="h-9 w-9 p-0" onClick={toggle}>
        <Menu className="h-5 w-5" />
        <span className="sr-only">{t("toggleMenu")}</span>
      </Button>
      <BrandLink />
      <div className="ml-auto flex items-center gap-1">
        {onChat && (
          <IconButton
            size="icon"
            aria-label={t("openConversations")}
            onClick={openConversations}
            className="text-muted-foreground rounded-lg [&_svg]:size-5"
          >
            <MessagesSquare />
          </IconButton>
        )}
        <NotificationBell variant="icon" />
      </div>
    </header>
  );
}
