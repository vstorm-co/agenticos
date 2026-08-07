"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { useRecentConversations } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** The newest few conversations, each one click from continuing. */
export function ConversationsWidget({ title, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.conversations");
  const { conversations, isLoading, error, refetch } = useRecentConversations(4);

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : conversations.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <ul className="space-y-2">
          {conversations.map((conversation) => (
            <li key={conversation.id} className="flex items-center gap-3 text-sm">
              <span className="min-w-0 flex-1">
                <span className="text-foreground block truncate">
                  {conversation.title ?? t("untitled")}
                </span>
                <span className="text-muted-foreground block text-xs">
                  {timeAgo(conversation.updated_at)}
                </span>
              </span>
              <Link
                href={`${ROUTES.CHAT}?id=${conversation.id}`}
                className="text-muted-foreground hover:text-foreground shrink-0 text-xs"
              >
                {t("continue")}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}
