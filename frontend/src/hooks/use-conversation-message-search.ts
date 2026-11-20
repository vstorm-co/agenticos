"use client";

import { useQuery } from "@tanstack/react-query";

import { useTenantId } from "@/hooks/use-organizations";
import { searchConversationMessages } from "@/lib/conversation-message-search-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";

/** Search message bodies only for the signed-in reader and their active tenant. */
export function useConversationMessageSearch(query: string) {
  const tenantId = useTenantId();
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const normalizedQuery = query.trim();

  return useQuery({
    queryKey: qk.conversations.messageSearch(tenantId, userId, normalizedQuery),
    queryFn: () => searchConversationMessages(normalizedQuery),
    enabled: !!tenantId && !!userId && normalizedQuery.length > 0,
    staleTime: 15_000,
  });
}
