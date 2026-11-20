"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { useTenantGuard, useTenantId } from "@/hooks/use-organizations";
import {
  listConversationMessagePins,
  pinConversationMessage,
  unpinConversationMessage,
  type ConversationMessagePin,
} from "@/lib/conversation-message-pin-api";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useChatStore } from "@/stores";

const PAGE_SIZE = 50;

interface TogglePin {
  messageId: string;
  pinned: boolean;
}

interface PinMutationScope extends TogglePin {
  tenant: string | null;
  userId: string | null;
  conversationId: string;
}

type PinMutationResult = ConversationMessagePin | void | null;

/** Read and mutate this reader's paged pins on the current transcript. */
export function useMessagePins(conversationId: string | null | undefined, enabled = true) {
  const tenant = useTenantId();
  const guardTenant = useTenantGuard();
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const updateMessage = useChatStore((state) => state.updateMessage);
  const chatStoreApi = useChatStore.useApi();
  const queryClient = useQueryClient();
  const tErrors = useTranslations("errors");
  const queryKey = qk.conversations.messagePins(tenant, userId, conversationId ?? null);
  const mutationKey = ["conversation-message-pin", tenant, userId, conversationId] as const;
  const mutationScope = JSON.stringify(mutationKey);

  const query = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam, signal }) =>
      listConversationMessagePins(conversationId!, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      const fetched = pages.reduce((count, page) => count + page.items.length, 0);
      return fetched < lastPage.total ? fetched : undefined;
    },
    enabled: enabled && !!tenant && !!userId && !!conversationId,
    staleTime: 15_000,
  });

  const isCurrentReader = (scope: PinMutationScope) =>
    !!scope.tenant &&
    !!scope.userId &&
    guardTenant(scope.tenant) &&
    useAuthStore.getState().user?.id === scope.userId;

  const toggle = useMutation<PinMutationResult, Error, PinMutationScope>({
    mutationKey,
    scope: { id: mutationScope },
    mutationFn: (scope: PinMutationScope) => {
      if (!isCurrentReader(scope)) return Promise.resolve(null);
      return scope.pinned
        ? pinConversationMessage(scope.conversationId, scope.messageId)
        : unpinConversationMessage(scope.conversationId, scope.messageId);
    },
    onSuccess: (result, scope) => {
      if (result === null || !isCurrentReader(scope)) return;

      updateMessage(scope.messageId, (message) =>
        message.conversationId === scope.conversationId
          ? { ...message, isPinned: scope.pinned }
          : message,
      );
      void queryClient.invalidateQueries({
        queryKey: qk.conversations.messagePins(scope.tenant, scope.userId, scope.conversationId),
      });
    },
    onError: (error, scope) => {
      if (
        isCurrentReader(scope) &&
        chatStoreApi.getState().loadedTranscript?.conversationId === scope.conversationId
      ) {
        toast.error(getErrorMessage(error, tErrors));
      }
    },
  });

  return {
    ...query,
    items: query.data?.pages.flatMap((page) => page.items) ?? [],
    total: query.data?.pages[0]?.total ?? 0,
    pendingMessageId: toggle.isPending ? toggle.variables!.messageId : null,
    togglePin: (messageId: string, pinned: boolean) => {
      if (!conversationId) return;
      toggle.mutate({ messageId, pinned, tenant, userId, conversationId });
    },
  };
}

export { PAGE_SIZE as MESSAGE_PINS_PAGE_SIZE };
