"use client";

import { useState } from "react";
import { Bell } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
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
 */
export function NotificationBell({ variant = "row" }: NotificationBellProps) {
  const [open, setOpen] = useState(false);
  const t = useTranslations("nav");
  const unread = useUnreadNotificationCount();

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {variant === "row" ? (
          <button
            type="button"
            data-tour="notification-bell"
            className="text-muted-foreground hover:bg-accent/60 hover:text-foreground focus-visible:ring-ring flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors outline-none focus-visible:ring-1"
          >
            <Bell className="h-4 w-4 shrink-0" aria-hidden />
            <span className="flex-1 text-left">{t("notifications")}</span>
            <UnreadBadge count={unread} />
          </button>
        ) : (
          <button
            type="button"
            data-tour="notification-bell"
            aria-label={t("notifications")}
            className="text-muted-foreground hover:bg-accent hover:text-foreground relative flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
          >
            <Bell className="h-5 w-5" aria-hidden />
            {unread > 0 ? (
              <span
                aria-hidden
                className="bg-primary border-background absolute top-1 right-1 size-2.5 rounded-full border-2"
              />
            ) : null}
          </button>
        )}
      </PopoverTrigger>
      <PopoverContent
        side={variant === "row" ? "right" : "bottom"}
        align="start"
        className="w-96 p-0"
      >
        <NotificationPanel open={open} />
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

function NotificationPanel({ open }: { open: boolean }) {
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
  } = useNotificationInbox(open);

  const hasUnread = notifications.some((item) => item.read_at === null);

  return (
    <div className="flex max-h-[28rem] flex-col">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h3 className="text-foreground text-sm font-semibold">{tNav("notifications")}</h3>
        {hasUnread ? (
          <button
            type="button"
            onClick={() => void markAllRead()}
            className="text-muted-foreground hover:text-foreground text-xs"
          >
            {t("markAllRead")}
          </button>
        ) : null}
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
                <NotificationRow key={item.id} item={item} onRead={markRead} />
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

function NotificationRow({ item, onRead }: { item: Notification; onRead: (id: string) => void }) {
  const tTime = useTranslations("time");
  const locale = useLocale();
  const unread = item.read_at === null;
  const rowClassName =
    "hover:bg-muted/60 focus-visible:ring-ring flex w-full items-start gap-2 rounded-md px-2 py-2 text-left outline-none focus-visible:ring-2";

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
  if (item.context_url) {
    return (
      <li>
        <a
          href={item.context_url}
          onClick={() => unread && onRead(item.id)}
          className={rowClassName}
        >
          {content}
        </a>
      </li>
    );
  }

  return (
    <li>
      <button
        type="button"
        onClick={() => unread && onRead(item.id)}
        disabled={!unread}
        className={cn(rowClassName, !unread && "cursor-default")}
      >
        {content}
      </button>
    </li>
  );
}
