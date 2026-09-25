"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { useNotificationInbox } from "@/hooks";
import { isInAppPath } from "@/lib/notification-link";
import { cn, timeAgo } from "@/lib/utils";
import { WidgetFrame } from "../widget-frame";
import { Bell } from "lucide-react";

import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

const SHOWN = 5;

/**
 * The most recent notifications, newest first, unread ones highlighted -
 * the bell's own list, reused rather than a card-only endpoint
 * (`useNotificationInbox` already fetches one page of it). Always enabled:
 * unlike the bell's popover, a dashboard card is on screen the moment the
 * page is.
 */
export function NotificationsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.notifications");
  const tNotifications = useTranslations("notifications");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { notifications, isLoading, error, refetch, markRead } = useNotificationInbox(true);

  const shown = notifications.slice(0, SHOWN);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={refetch} />
      ) : shown.length === 0 ? (
        <WidgetEmptyBody
          icon={Bell}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="space-y-1">
          {shown.map((item) => {
            const unread = item.read_at === null;
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
                    {tNotifications(unread ? "rowUnread" : "rowRead")}
                  </span>
                  <span
                    className={cn(
                      "block truncate text-sm",
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
            const rowClassName =
              "hover:bg-muted/60 flex items-start gap-2.5 rounded-md px-1 py-1.5 text-left text-sm";
            // Fire-and-forget: nothing here needs the outcome, but an
            // unhandled rejection (a row the read-time gate has since
            // hidden, a dropped connection) must not reach the console as
            // one.
            const handleRead = () => {
              if (unread) {
                markRead(item.id).catch(() => {});
              }
            };
            return (
              <li key={item.id}>
                {!item.context_url ? (
                  <button
                    type="button"
                    onClick={handleRead}
                    disabled={!unread}
                    className={cn(rowClassName, "w-full", !unread && "cursor-default")}
                  >
                    {content}
                  </button>
                ) : isInAppPath(item.context_url) ? (
                  // `prefetch={false}`: five rows in view, each otherwise
                  // fetching a dynamic dashboard route nobody has asked for.
                  <Link
                    href={item.context_url}
                    prefetch={false}
                    onClick={handleRead}
                    className={rowClassName}
                  >
                    {content}
                  </Link>
                ) : (
                  // A row written before `context_url` held a path, which
                  // carries an origin and so is a whole new document either
                  // way. Nothing migrates those; they age out.
                  <a href={item.context_url} onClick={handleRead} className={rowClassName}>
                    {content}
                  </a>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </WidgetFrame>
  );
}
