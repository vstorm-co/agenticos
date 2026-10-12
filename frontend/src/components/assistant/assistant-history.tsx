"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, MessageSquare, MessageSquarePlus, Search } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { useConversations } from "@/hooks/use-conversations";
import { cn, timeAgo } from "@/lib/utils";

interface AssistantHistoryProps {
  agentId: string;
  onClose: () => void;
  /** Start a new conversation instead of opening an earlier one. */
  onNew: () => void;
}

/**
 * The reader's earlier conversations with the AI Architect, and only those (#2063).
 *
 * Over the conversation rather than beside it, in a window too narrow for two
 * columns: newest first, each with when it was last touched, the open one marked,
 * and a filter for when the list has grown past a glance.
 */
export function AssistantHistory({ agentId, onClose, onNew }: AssistantHistoryProps) {
  const t = useTranslations("assistantWidget");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { conversations, currentConversationId, fetchConversations, selectConversation } =
    useConversations({ agentId });
  const [query, setQuery] = useState("");

  useEffect(() => {
    void fetchConversations();
  }, [fetchConversations]);

  const needle = query.trim().toLowerCase();
  const shown = conversations.filter((conversation) =>
    (conversation.title ?? t("untitled")).toLowerCase().includes(needle),
  );

  return (
    <div className="bg-background absolute inset-0 z-30 flex flex-col">
      <div className="flex items-center gap-1.5 px-2 pt-2 pb-1">
        <button
          type="button"
          onClick={onClose}
          aria-label={t("closeHistory")}
          title={t("closeHistory")}
          className="text-muted-foreground hover:text-foreground hover:bg-foreground/[0.05] rounded-md p-1.5"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <p className="flex-1 text-sm font-semibold">{t("history")}</p>
        <button
          type="button"
          onClick={onNew}
          className="text-foreground hover:bg-foreground/[0.05] border-border inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium"
        >
          <MessageSquarePlus className="h-3.5 w-3.5" />
          {t("newConversation")}
        </button>
      </div>

      {conversations.length > 0 && (
        <div className="px-3 pt-1 pb-2">
          <label className="border-border bg-muted/40 focus-within:border-foreground/30 flex h-9 items-center gap-2 rounded-lg border px-2.5">
            <Search className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("historySearch")}
              aria-label={t("historySearch")}
              className="placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent text-sm outline-none"
            />
          </label>
        </div>
      )}

      {conversations.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-8 pb-12 text-center">
          <span className="bg-muted text-muted-foreground mb-1 flex h-11 w-11 items-center justify-center rounded-2xl">
            <MessageSquare className="h-5 w-5" />
          </span>
          <p className="text-sm font-medium">{t("noHistory")}</p>
          <p className="text-muted-foreground text-xs leading-relaxed">{t("noHistoryLead")}</p>
        </div>
      ) : shown.length === 0 ? (
        <p className="text-muted-foreground px-4 py-6 text-center text-sm">{t("historyNoMatch")}</p>
      ) : (
        <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-2">
          {shown.map((conversation) => {
            const current = conversation.id === currentConversationId;
            return (
              <li key={conversation.id}>
                <button
                  type="button"
                  aria-current={current || undefined}
                  onClick={() => {
                    void selectConversation(conversation.id);
                    onClose();
                  }}
                  className={cn(
                    "group flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors",
                    current ? "bg-accent" : "hover:bg-foreground/[0.04]",
                  )}
                >
                  <span
                    className={cn(
                      "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors",
                      current
                        ? "bg-foreground text-background"
                        : "bg-muted text-muted-foreground group-hover:text-foreground",
                    )}
                  >
                    <MessageSquare className="h-3.5 w-3.5" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">
                      {conversation.title ?? t("untitled")}
                    </span>
                    <span className="text-muted-foreground block text-xs">
                      {timeAgo(conversation.updated_at || conversation.created_at, tTime, locale)}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
