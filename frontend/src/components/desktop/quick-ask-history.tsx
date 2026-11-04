"use client";
import { useTranslations } from "next-intl";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useConversations } from "@/hooks/use-conversations";
import { useChatStore, useConversationStore } from "@/stores";
import { conversationMessageToChatMessage } from "@/lib/conversation-to-chat";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useTenantId } from "@/hooks/use-organizations";
import { useAuthStore } from "@/stores/auth-store";
import type { ConversationListResponse } from "@/types";

export function useQuickAskHistory(search: string, enabled: boolean) {
  const tenant = useTenantId();
  const account = useAuthStore((s) => s.user?.id);
  const params = new URLSearchParams({
    limit: "50",
    sort_by: "updated_at",
    sort_dir: "desc",
    hide_api: "true",
  });
  if (search.trim()) params.set("search", search.trim());
  const query = params.toString();
  return useQuery({
    queryKey: [...qk.conversations.list(query), account, tenant],
    queryFn: () => apiClient.get<ConversationListResponse>(`/conversations?${query}`),
    enabled,
  });
}
export function RestoreQuickAsk({ id }: { id: string }) {
  const t = useTranslations("desktop.quickAsk");
  const {
    selectConversation,
    isLoading,
    error,
    hasEarlierMessages,
    isLoadingEarlier,
    loadEarlierMessages,
  } = useConversations();
  const history = useConversationStore((s) => s.currentMessages);
  const reread = useChatStore((s) => s.rereadMessages);
  useEffect(() => {
    void selectConversation(id);
  }, [id, selectConversation]);
  useEffect(() => {
    if (history.length && history[0]?.conversation_id === id)
      reread(history.map(conversationMessageToChatMessage));
  }, [history, id, reread]);
  return error ? (
    <button className="text-destructive mb-2 text-xs" onClick={() => void selectConversation(id)}>
      {t("retryHistory")}
    </button>
  ) : isLoading ? (
    <p role="status" className="text-muted-foreground mb-2 text-xs">
      {t("loadingHistory")}
    </p>
  ) : hasEarlierMessages ? (
    <button
      className="text-muted-foreground hover:text-foreground mb-2 text-xs"
      disabled={isLoadingEarlier}
      onClick={() => void loadEarlierMessages()}
    >
      {t("earlierMessages")}
    </button>
  ) : null;
}
