"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { useTenantId } from "@/hooks/use-organizations";
import { listConversationForks } from "@/lib/conversation-forks-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";

const FORK_PAGE_SIZE = 100;

/** List personal forks under the active reader, tenant and source conversation. */
export function useConversationForks(
  sourceId: string | null,
  messageId: string | null,
  enabled = true,
) {
  const tenantId = useTenantId();
  const userId = useAuthStore((state) => state.user?.id ?? null);

  return useInfiniteQuery({
    queryKey: qk.conversations.forks(sourceId, messageId, tenantId, userId, 0, FORK_PAGE_SIZE),
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      listConversationForks(sourceId!, messageId!, { skip: pageParam, limit: FORK_PAGE_SIZE }),
    getNextPageParam: (lastPage, pages) => {
      const loaded = pages.reduce((count, page) => count + page.items.length, 0);
      return lastPage.items.length > 0 && loaded < lastPage.total ? loaded : undefined;
    },
    enabled: Boolean(enabled && sourceId && messageId && tenantId && userId),
    staleTime: 0,
    refetchOnMount: "always",
  });
}
