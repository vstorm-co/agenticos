"use client";

import Link from "next/link";
import { MessageSquare } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { ConversationAgents } from "@/components/agents/conversation-agents";
import { useRecentConversations } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** The newest few conversations, each one click from continuing. */
export function ConversationsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.conversations");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { conversations, isLoading, error, refetch } = useRecentConversations(4);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : conversations.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <ul className="space-y-1">
          {conversations.map((conversation) => (
            <li key={conversation.id}>
              {/* The whole row is the link, not the word at the end of it: the
                  row is what a reader is aiming at, and a four-character target
                  on the far right of a card is the smallest one on the page. */}
              <Link
                href={`${ROUTES.CHAT}?id=${conversation.id}`}
                className="hover:bg-muted/60 focus-visible:ring-ring group flex items-center gap-2.5 rounded-md px-1 py-1.5 text-sm outline-none focus-visible:ring-2"
              >
                {/* Who answered, drawn the way the chat sidebar draws it - the
                    same faces, the same stack when a thread changed agent
                    mid-way. A thread with no agent is the general assistant,
                    which has no face and takes the bubble instead. */}
                {conversation.agents?.length ? (
                  <ConversationAgents agents={conversation.agents} showName={false} />
                ) : (
                  <span
                    className="bg-muted text-muted-foreground grid size-6 shrink-0 place-items-center rounded-full"
                    aria-hidden
                  >
                    <MessageSquare className="size-3" />
                  </span>
                )}
                <span className="min-w-0 flex-1">
                  <span className="text-foreground block truncate">
                    {conversation.title ?? t("untitled")}
                  </span>
                  <span className="text-muted-foreground block text-xs">
                    {timeAgo(conversation.updated_at, tTime, locale)}
                  </span>
                </span>
                <span className="text-muted-foreground group-hover:text-foreground shrink-0 text-xs">
                  {t("continue")}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}
