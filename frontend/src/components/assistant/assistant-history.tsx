"use client";

import { useEffect } from "react";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { useConversations } from "@/hooks/use-conversations";

interface AssistantHistoryProps {
  agentId: string;
  onClose: () => void;
}

/**
 * The reader's earlier conversations with the AI Architect, and only those (#2063).
 */
export function AssistantHistory({ agentId, onClose }: AssistantHistoryProps) {
  const t = useTranslations("assistantWidget");
  const { conversations, fetchConversations, selectConversation } = useConversations({ agentId });

  useEffect(() => {
    void fetchConversations();
  }, [fetchConversations]);

  return (
    <div className="bg-background absolute inset-0 z-30 flex flex-col">
      <div className="border-border flex items-center justify-between border-b px-3 py-2">
        <p className="text-sm font-medium">{t("history")}</p>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("closeHistory")}
          className="text-muted-foreground hover:text-foreground rounded-md p-1"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      {conversations.length === 0 ? (
        <p className="text-muted-foreground p-4 text-sm">{t("noHistory")}</p>
      ) : (
        <ul className="min-h-0 flex-1 overflow-y-auto p-1">
          {conversations.map((conversation) => (
            <li key={conversation.id}>
              <button
                type="button"
                onClick={() => {
                  void selectConversation(conversation.id);
                  onClose();
                }}
                className="hover:bg-foreground/[0.04] w-full truncate rounded-md px-3 py-2 text-left text-sm"
              >
                {conversation.title ?? t("untitled")}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
