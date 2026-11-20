"use client";

import { useLocale, useTranslations } from "next-intl";
import { MessagesSquare } from "lucide-react";

import { ErrorState, LoadingState } from "@/components/states";
import { ListCardEmpty } from "@/components/ui";
import { cn, timeAgo } from "@/lib/utils";
import type { AgentMessageThreadRead } from "@/types/agent-messages";

interface ThreadListProps {
  threads: AgentMessageThreadRead[];
  selectedId: string | null;
  onSelect: (threadId: string) => void;
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
}

/**
 * The threads, most recently active first: both agents, the last message's
 * preview, and a dot while the thread waits on the reader.
 */
export function ThreadList({
  threads,
  selectedId,
  onSelect,
  isLoading,
  error,
  refetch,
}: ThreadListProps) {
  const t = useTranslations("agentMessages");
  const ts = useTranslations("common");
  const tTime = useTranslations("time");
  const locale = useLocale();

  if (isLoading) return <LoadingState variant="skeleton-list" rows={3} className="p-5" />;
  if (error)
    return (
      <ErrorState
        className="m-5 flex-1"
        description={error}
        cta={{ label: ts("retry"), onClick: () => void refetch() }}
      />
    );
  if (threads.length === 0)
    return (
      <ListCardEmpty
        icon={MessagesSquare}
        title={t("emptyThreads.title")}
        description={t("emptyThreads.description")}
      />
    );

  return (
    <ul className="divide-border divide-y">
      {threads.map((thread) => {
        const selected = thread.id === selectedId;
        return (
          <li key={thread.id}>
            <button
              type="button"
              aria-current={selected}
              onClick={() => onSelect(thread.id)}
              className={cn(
                "hover:bg-muted/60 flex w-full items-start gap-3 px-4 py-3 text-left",
                selected && "bg-muted/60",
              )}
            >
              <span className="min-w-0 flex-1">
                <span className="sr-only">{t(thread.unread ? "unread" : "read")}</span>
                <span
                  className={cn(
                    "block truncate text-sm",
                    thread.unread ? "text-foreground font-medium" : "text-muted-foreground",
                  )}
                >
                  {t("threadTitle", {
                    first: thread.agent_a.name,
                    second: thread.agent_b.name,
                  })}
                </span>
                {thread.last_message ? (
                  <span className="text-muted-foreground block truncate text-xs">
                    {t("lastMessage", {
                      slug: thread.last_message.sender_agent_slug,
                      body: thread.last_message.body,
                    })}
                  </span>
                ) : null}
              </span>
              <span className="flex shrink-0 flex-col items-end gap-1">
                {thread.last_message_at ? (
                  <span className="text-muted-foreground text-xs">
                    {timeAgo(thread.last_message_at, tTime, locale)}
                  </span>
                ) : null}
                <span
                  aria-hidden
                  className={cn(
                    "size-2 rounded-full",
                    thread.unread ? "bg-primary" : "bg-transparent",
                  )}
                />
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
