"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { MessagesSquare } from "lucide-react";

import { useAgentMessageThreads } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { cn, timeAgo } from "@/lib/utils";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

const SHOWN = 5;

/**
 * The threads waiting on the reader — unread ones only, most recently
 * active first — each row the two agents, the last message's preview, and
 * when it arrived, linking to the messages page.
 */
export function AgentMessagesWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.agent-messages");
  const tAgentMessages = useTranslations("agentMessages");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { threads, isLoading, error, refetch } = useAgentMessageThreads(0, 20);

  // The list arrives most recently active first; the card shows the unread
  // head of it, five at most.
  const shown = threads.filter((thread) => thread.unread).slice(0, SHOWN);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={refetch} />
      ) : shown.length === 0 ? (
        <WidgetEmptyBody
          icon={MessagesSquare}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="space-y-1">
          {shown.map((thread) => (
            <li key={thread.id}>
              <Link
                href={ROUTES.AGENT_MESSAGES}
                prefetch={false}
                className="hover:bg-muted/60 flex items-start gap-3 rounded-md px-1 py-1.5 text-left text-sm"
              >
                <span className="min-w-0 flex-1">
                  <span className="sr-only">{tAgentMessages("unread")}</span>
                  <span className="text-foreground block truncate font-medium">
                    {tAgentMessages("threadTitle", {
                      first: thread.agent_a.name,
                      second: thread.agent_b.name,
                    })}
                  </span>
                  <span className="text-muted-foreground block truncate">
                    {thread.last_message
                      ? tAgentMessages("lastMessage", {
                          slug: thread.last_message.sender_agent_slug,
                          body: thread.last_message.body,
                        })
                      : tAgentMessages("noMessagesYet")}
                  </span>
                  <span className="text-muted-foreground block text-xs">
                    {timeAgo(thread.last_message_at ?? thread.updated_at, tTime, locale)}
                  </span>
                </span>
                <span
                  aria-hidden
                  className={cn("bg-primary mt-1.5 size-2 shrink-0 rounded-full")}
                />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}
