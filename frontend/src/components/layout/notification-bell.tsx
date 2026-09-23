"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import {
  Badge,
  BellGlyph,
  Popover,
  PopoverContent,
  PopoverTrigger,
  RingingBell,
} from "@/components/ui";
import { useNotificationInbox, useUnreadNotificationCount } from "@/hooks";
import type { Notification } from "@/lib/notifications-api";
import { cn, timeAgo } from "@/lib/utils";

interface NotificationBellProps {
  /** The sidebar row (icon, label, badge) above `md`; a bare icon below it,
   * where `MobileHeader` has no room for a labelled row. */
  variant?: "row" | "icon";
}

/**
 * The bell (#1598): a polled unread badge that stays live while the popover
 * is closed, and a paginated list that only has to be current once it is
 * open - `useNotificationInbox(open)` is what draws that line.
 *
 * The glyph swings when the count goes up, which is the whole reason it is a
 * drawn bell rather than a lucide icon: a badge changing from 2 to 3 in the
 * corner of a sidebar is a thing nobody sees, and this is the one control in
 * the console whose job is to be noticed without being looked at.
 */
export function NotificationBell({ variant = "row" }: NotificationBellProps) {
  const [open, setOpen] = useState(false);
  const t = useTranslations("nav");
  const tNotifications = useTranslations("notifications");
  const { count: unread, approximate } = useUnreadNotificationCount();
  const label = unread > 0 ? tNotifications("unreadCount", { count: unread }) : t("notifications");

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {variant === "row" ? (
          <button
            type="button"
            data-tour="notification-bell"
            className="text-muted-foreground hover:bg-accent/60 hover:text-foreground focus-visible:ring-ring flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors outline-none focus-visible:ring-1"
          >
            {/* The bare bell here, not `BellGlyph`: this row already ends in a
                count, and a badge orbiting the icon would sit on top of the
                label between them. */}
            <RingingBell count={unread} className="h-4 w-4 shrink-0" />
            <span className="flex-1 text-left">{t("notifications")}</span>
            <UnreadBadge count={unread} />
          </button>
        ) : (
          <BellGlyph
            data-tour="notification-bell"
            count={unread}
            label={label}
            size={36}
            variant="dot"
            className="text-muted-foreground hover:text-foreground shrink-0 rounded-lg"
          />
        )}
      </PopoverTrigger>
      <PopoverContent
        side={variant === "row" ? "right" : "bottom"}
        align="start"
        className="w-[min(24rem,calc(100vw-2rem))] p-0"
      >
        <NotificationPanel open={open} unread={unread} approximate={approximate} />
      </PopoverContent>
    </Popover>
  );
}

function UnreadBadge({ count }: { count: number }) {
  const t = useTranslations("notifications");
  if (count === 0) return null;
  return (
    <Badge
      variant="default"
      aria-label={t("unreadCount", { count })}
      className="h-5 min-w-5 shrink-0 justify-center rounded-full px-1 text-[10px] leading-none"
    >
      {count > 99 ? "99+" : count}
    </Badge>
  );
}

function NotificationPanel({
  open,
  unread,
  approximate,
}: {
  open: boolean;
  unread: number;
  approximate: boolean;
}) {
  const tNav = useTranslations("nav");
  const t = useTranslations("notifications");
  const {
    notifications,
    isLoading,
    error,
    hasMore,
    isLoadingMore,
    loadMore,
    markRead,
    markAllRead,
    dismiss,
    clearAll,
  } = useNotificationInbox(open);

  // Not `notifications.some(...)`: the loaded page can be all-read while an
  // unpaged older page still holds an unread row, and "mark all read" must
  // stay offered until the same unread-count query the badge itself reads
  // says there is nothing left.
  // `approximate` counts too: a bounded scan whose whole window was rows the
  // read-time gate hides reports zero with rows still behind it, and hiding the
  // sweep on that number is hiding the only control that reaches them (#1761).
  const hasUnread = unread > 0 || approximate;
  // Clearing, unlike marking read, is about what is *listed* - so this one is
  // answered by the page on screen, which is the thing the button empties.
  const hasAny = notifications.length > 0;

  return (
    <div className="flex max-h-[28rem] flex-col">
      <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
        <h3 className="text-foreground text-sm font-semibold">{tNav("notifications")}</h3>
        <div className="flex shrink-0 items-center gap-3">
          {hasUnread ? (
            <button
              type="button"
              onClick={() => void markAllRead().catch(() => {})}
              className="text-muted-foreground hover:text-foreground text-xs"
            >
              {t("markAllRead")}
            </button>
          ) : null}
          {hasAny ? (
            <button
              type="button"
              onClick={() => void clearAll().catch(() => {})}
              className="text-muted-foreground hover:text-foreground text-xs"
            >
              {t("clearAll")}
            </button>
          ) : null}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {isLoading ? (
          <PanelSkeleton />
        ) : error ? (
          <p className="text-muted-foreground p-4 text-center text-sm">{error}</p>
        ) : notifications.length === 0 ? (
          <div className="flex flex-col items-center gap-1 py-8 text-center">
            <p className="text-foreground text-sm font-medium">{t("empty.title")}</p>
            <p className="text-muted-foreground max-w-60 text-xs">{t("empty.description")}</p>
          </div>
        ) : (
          <>
            <ul className="space-y-0.5">
              {notifications.map((item) => (
                <NotificationRow key={item.id} item={item} onRead={markRead} onDismiss={dismiss} />
              ))}
            </ul>
            {hasMore ? (
              <button
                type="button"
                onClick={loadMore}
                disabled={isLoadingMore}
                className="text-muted-foreground hover:text-foreground w-full py-2 text-center text-xs disabled:opacity-50"
              >
                {t("loadMore")}
              </button>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function PanelSkeleton() {
  const t = useTranslations("dashboard.states");
  return (
    <div role="status" aria-label={t("loading")} className="animate-pulse space-y-3 p-2">
      {Array.from({ length: 3 }, (_, index) => (
        <div
          key={index}
          className="bg-muted h-8 rounded"
          style={{ width: `${100 - index * 12}%` }}
        />
      ))}
    </div>
  );
}

function NotificationRow({
  item,
  onRead,
  onDismiss,
}: {
  item: Notification;
  onRead: (id: string) => Promise<void>;
  onDismiss: (id: string) => Promise<void>;
}) {
  const tTime = useTranslations("time");
  const tNotifications = useTranslations("notifications");
  const locale = useLocale();
  const unread = item.read_at === null;
  const rowClassName =
    "hover:bg-muted/60 focus-visible:ring-ring flex w-full items-start gap-2 rounded-md px-2 py-2 pr-7 text-left outline-none focus-visible:ring-2";

  // A row's own click is fire-and-forget: nothing here needs to know its
  // outcome, but an unhandled rejection (a row the read-time gate has since
  // hidden, a dropped connection) must not reach the console as one.
  const handleRead = () => {
    if (unread) {
      onRead(item.id).catch(() => {});
    }
  };

  const content = (
    <>
      <span
        aria-hidden
        className={cn(
          "mt-1.5 size-1.5 shrink-0 rounded-full",
          unread ? "bg-primary" : "bg-transparent",
        )}
      />
      <span className="min-w-0 flex-1">
        <span className="sr-only">
          {unread ? tNotifications("rowUnread") : tNotifications("rowRead")}
        </span>
        <span
          className={cn(
            "block text-sm",
            unread ? "text-foreground font-medium" : "text-muted-foreground",
          )}
        >
          {item.summary}
        </span>
        <span className="text-muted-foreground block text-xs">
          {timeAgo(item.created_at, tTime, locale)}
        </span>
      </span>
    </>
  );

  // `context_url` is a full URL (`FRONTEND_URL` plus a path, `notifications.py`'s
  // own `_link`), never a relative one - a plain anchor rather than `next/link`,
  // which treats an absolute string as an external destination anyway.
  const body = item.context_url ? (
    <a href={item.context_url} onClick={handleRead} className={rowClassName}>
      {content}
    </a>
  ) : (
    <button
      type="button"
      onClick={handleRead}
      disabled={!unread}
      className={cn(rowClassName, !unread && "cursor-default")}
    >
      {content}
    </button>
  );

  return (
    // `group` and a sibling, not a button inside the row: the row is itself an
    // anchor or a button, and a nested one is invalid markup that swallows the
    // outer click in whichever direction the browser resolves it.
    <li className="group relative">
      {body}
      <button
        type="button"
        onClick={() => void onDismiss(item.id).catch(() => {})}
        aria-label={tNotifications("dismissRow")}
        // Revealed on hover, and on focus for anyone tabbing - kept mounted
        // either way, because a control that only exists on hover is one a
        // keyboard never reaches. `touch:` keeps it out permanently on a device
        // that cannot hover at all, where a tap produces no `focus-visible`
        // either and there would otherwise be no way to find it.
        className="text-muted-foreground hover:text-foreground focus-visible:ring-ring touch:opacity-100 absolute top-1.5 right-1 rounded p-1 opacity-0 transition-opacity outline-none group-focus-within:opacity-100 group-hover:opacity-100 focus-visible:opacity-100 focus-visible:ring-2"
      >
        <X className="h-3 w-3" aria-hidden />
      </button>
    </li>
  );
}
