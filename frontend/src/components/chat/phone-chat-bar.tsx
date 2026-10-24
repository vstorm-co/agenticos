"use client";

import { Menu, MessagesSquare, SquarePen } from "lucide-react";
import { useTranslations } from "next-intl";

import { useConversations } from "@/hooks";
import { useUnreadNotificationCount } from "@/hooks/use-notifications";
import { cn } from "@/lib/utils";
import { useChatSidebarStore, useSidebarStore } from "@/stores";

const ROUND =
  "bg-background/80 text-foreground pointer-events-auto inline-flex size-11 items-center justify-center rounded-full border border-foreground/[0.06] shadow-sm backdrop-blur-md active:scale-95 transition-transform [&_svg]:size-5";

/**
 * The chat's top on a phone: no bar, a few buttons floating over the
 * transcript as a messenger draws them - the menu on the left, and on the
 * right the conversations and a new chat (#2066, #2097).
 *
 * The page's own header steps aside on the chat (`MobileHeader`), so the
 * transcript has the whole height; what scrolls under the buttons fades into
 * the page behind them. The menu carries a dot while something in the inbox
 * is unread, since the bell is in the drawer it opens.
 */
export function PhoneChatBar() {
  const t = useTranslations("nav");
  const ts = useTranslations("chat.sidebar");
  const toggleMenu = useSidebarStore((state) => state.toggle);
  const openConversations = useChatSidebarStore((state) => state.open);
  const { startNewChat } = useConversations();
  const unread = useUnreadNotificationCount();

  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 z-30 md:hidden">
      <div className="from-background via-background/85 absolute inset-x-0 top-0 h-20 bg-gradient-to-b to-transparent" />
      <div className="relative flex items-center justify-between px-3 pt-2">
        <button
          type="button"
          onClick={toggleMenu}
          aria-label={t("toggleMenu")}
          className={cn(ROUND, "relative")}
        >
          <Menu aria-hidden />
          {unread.count > 0 && (
            <span
              aria-hidden
              className="bg-destructive ring-background absolute top-2 right-2 size-2 rounded-full ring-2"
            />
          )}
        </button>
        <div
          className={cn(
            ROUND,
            "h-auto w-auto gap-1 p-1 [&>button]:inline-flex [&>button]:size-11 [&>button]:items-center [&>button]:justify-center [&>button]:rounded-full",
          )}
        >
          <button type="button" onClick={openConversations} aria-label={t("openConversations")}>
            <MessagesSquare aria-hidden />
          </button>
          <button type="button" onClick={() => void startNewChat()} aria-label={ts("newChat")}>
            <SquarePen aria-hidden />
          </button>
        </div>
      </div>
    </div>
  );
}
