"use client";

import { useCallback, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores/org-store";
import type {
  Conversation,
  ConversationListResponse,
  ConversationShare,
  ConversationShareListResponse,
} from "@/types";

/** How many shared conversations the chat sidebar lists: one page, favourites before recent activity. */
const SHARED_IN_SIDEBAR = 50;
// Sharing changes can come from another member with this page already open.
const ACCESS_REFRESH_MS = 15_000;

function readSharedSidebar(): Promise<ConversationListResponse> {
  return apiClient.get<ConversationListResponse>(
    `/conversations/shared-with-me?skip=0&limit=${SHARED_IN_SIDEBAR}&include_archived=false`,
  );
}

/**
 * The conversations other people shared with the caller, for the chat sidebar.
 *
 * A direct share alone does not put a thread in the caller's ordinary listing.
 * Channel participation can also list it; the sidebar deduplicates those rows.
 */
export function useSharedConversations(enabled: boolean) {
  // The active organization's shares: the request carries its header, and the
  // key has to change with it or a switch shows the last organization's list.
  const orgId = useOrgStore((state) => state.activeOrgId);
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: qk.conversationShares.sharedWithMe(0, SHARED_IN_SIDEBAR, orgId, false),
    queryFn: readSharedSidebar,
    enabled,
    refetchInterval: ACCESS_REFRESH_MS,
  });
  // An archived thread is its owner's to bring back; it is no conversation to
  // continue, so it is not offered beside the active ones.
  const items = useMemo(
    () => (enabled ? (data?.items ?? []).filter((conversation) => !conversation.is_archived) : []),
    [enabled, data],
  );
  return {
    items,
    isLoading: enabled && isLoading,
    failed: enabled && isError,
    retry: () => void refetch(),
  };
}

/** Observe the sidebar's cached row without starting another list/polling loop. */
export function useSharedConversation(conversationId: string | null): Conversation | undefined {
  const orgId = useOrgStore((state) => state.activeOrgId);
  const { data } = useQuery<ConversationListResponse>({
    queryKey: qk.conversationShares.sharedWithMe(0, SHARED_IN_SIDEBAR, orgId, false),
    queryFn: readSharedSidebar,
    enabled: false,
  });
  return data?.items.find((conversation) => conversation.id === conversationId);
}

/** What the reader may do in an open conversation, once it is known. */
export interface ConversationAccess {
  /** Whether the answer has arrived; until it has, nothing should be written. */
  known: boolean;
  failed: boolean;
  conversation: Conversation | null;
  retry: () => void;
  archived: boolean;
  /** Shared with the reader to view only. */
  viewOnly: boolean;
}

/**
 * Whether the reader may write in a conversation their own listing does not hold.
 *
 * Opened by link or from a notice, or past the first page of shares, a thread
 * has no row to read this from - and a composer offered on a guess is a message
 * the server then refuses. Asked of the conversation itself, only when needed.
 * A failing read keeps writes closed until access can be verified.
 */
export function useConversationAccess(
  conversationId: string | null,
  enabled: boolean,
): ConversationAccess {
  const orgId = useOrgStore((state) => state.activeOrgId);
  const { data, isError, refetch } = useQuery({
    queryKey: qk.conversationShares.access(conversationId ?? "", orgId),
    queryFn: () => apiClient.get<Conversation>(`/conversations/${conversationId}/metadata`),
    enabled: enabled && conversationId !== null,
    retry: false,
    refetchInterval: ACCESS_REFRESH_MS,
  });
  return {
    known: !enabled || (data !== undefined && !isError),
    failed: enabled && isError,
    conversation: enabled && !isError ? (data ?? null) : null,
    retry: () => void refetch(),
    archived: data?.is_archived === true,
    viewOnly: data?.share_permission === "view",
  };
}

/**
 * Take a conversation somebody shared with the caller out of their chats.
 *
 * Ends the caller's own share; the conversation and everybody else's access to
 * it stay. Answers whether it went.
 */
export function useLeaveSharedConversation(): (conversationId: string) => Promise<boolean> {
  const t = useTranslations("chat");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  return useCallback(
    async (conversationId: string) => {
      try {
        await apiClient.delete(`/conversations/${conversationId}/shared-with-me`);
        await queryClient.invalidateQueries({ queryKey: qk.conversationShares.all() });
        toast.success(t("leftShared"));
        return true;
      } catch (err) {
        toast.error(getErrorMessage(err, tErrors, t("failedLeaveShared")));
        return false;
      }
    },
    [queryClient, t, tErrors],
  );
}

export function useConversationShares() {
  const tErrors = useTranslations("errors");
  const t = useTranslations("sharing");
  const orgId = useOrgStore((state) => state.activeOrgId);
  const queryClient = useQueryClient();

  // The shares list belongs to whichever conversation was last requested via
  // fetchShares. React Query owns the cache; we just track which key is active.
  const [conversationId, setConversationId] = useState<string | null>(null);
  // shared-with-me is paginated; remember the last requested window.
  const [sharedWithMeParams, setSharedWithMeParams] = useState<{
    skip: number;
    limit: number;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sharesQuery = useQuery({
    queryKey: conversationId
      ? qk.conversationShares.list(conversationId)
      : qk.conversationShares.all(),
    queryFn: async () => {
      const response = await apiClient.get<ConversationShareListResponse>(
        `/conversations/${conversationId}/shares`,
      );
      return response.items;
    },
    enabled: !!conversationId,
  });

  const sharedWithMeQuery = useQuery({
    queryKey: sharedWithMeParams
      ? qk.conversationShares.sharedWithMe(sharedWithMeParams.skip, sharedWithMeParams.limit, orgId)
      : qk.conversationShares.sharedWithMe(0, 50, orgId),
    queryFn: async () => {
      const { skip, limit } = sharedWithMeParams!;
      return apiClient.get<ConversationListResponse>(
        `/conversations/shared-with-me?skip=${skip}&limit=${limit}`,
      );
    },
    enabled: !!sharedWithMeParams,
  });

  const shares: ConversationShare[] = sharesQuery.data ?? [];
  const sharedWithMe: Conversation[] = sharedWithMeQuery.data?.items ?? [];
  const sharedWithMeTotal = sharedWithMeQuery.data?.total ?? 0;
  const isLoading = sharesQuery.isFetching || sharedWithMeQuery.isFetching;

  // A read that was refused has to say so too. `invalidateQueries` resolves even
  // when the refetch behind it fails, so wrapping the fetchers in a try/catch
  // reported nothing - the dialog sat empty with no explanation.
  const readFailure = sharesQuery.error ?? sharedWithMeQuery.error;

  const shareConversation = useCallback(
    async (
      conversationId: string,
      data: {
        /** A user id, for callers that hold one. The dialog sends the email. */
        shared_with?: string;
        shared_with_email?: string;
        permission?: "view" | "edit";
        generate_link?: boolean;
      },
    ) => {
      setError(null);
      try {
        const share = await apiClient.post<ConversationShare>(
          `/conversations/${conversationId}/shares`,
          data,
        );
        // Optimistically prepend so the dialog updates instantly, then refetch.
        queryClient.setQueryData<ConversationShare[]>(
          qk.conversationShares.list(conversationId),
          (prev = []) => [share, ...prev],
        );
        queryClient.invalidateQueries({
          queryKey: qk.conversationShares.list(conversationId),
        });
        return share;
      } catch (err: unknown) {
        const message = getErrorMessage(err, tErrors, t("failedShare"));
        setError(message);
        throw err;
      }
    },
    [queryClient, t, tErrors],
  );

  const fetchShares = useCallback(
    async (conversationId: string) => {
      setError(null);
      setConversationId(conversationId);
      await queryClient.invalidateQueries({
        queryKey: qk.conversationShares.list(conversationId),
      });
    },
    [queryClient],
  );

  const changePermission = useCallback(
    async (conversationId: string, shareId: string, permission: "view" | "edit") => {
      setError(null);
      const share = await apiClient.patch<ConversationShare>(
        `/conversations/${conversationId}/shares/${shareId}`,
        { permission },
      );
      queryClient.setQueryData<ConversationShare[]>(
        qk.conversationShares.list(conversationId),
        (prev = []) => prev.map((s) => (s.id === shareId ? share : s)),
      );
      // Then read back, as a revoke does: a read already in flight answered
      // with the old level and would otherwise stand.
      queryClient.invalidateQueries({ queryKey: qk.conversationShares.list(conversationId) });
      return share;
    },
    [queryClient],
  );

  const revokeShare = useCallback(
    async (conversationId: string, shareId: string) => {
      setError(null);
      try {
        await apiClient.delete(`/conversations/${conversationId}/shares/${shareId}`);
        queryClient.setQueryData<ConversationShare[]>(
          qk.conversationShares.list(conversationId),
          (prev = []) => prev.filter((s) => s.id !== shareId),
        );
        queryClient.invalidateQueries({
          queryKey: qk.conversationShares.list(conversationId),
        });
      } catch (err: unknown) {
        const message = getErrorMessage(err, tErrors, t("failedRevoke"));
        setError(message);
        throw err;
      }
    },
    [queryClient, t, tErrors],
  );

  const fetchSharedWithMe = useCallback(
    async (skip = 0, limit = 50) => {
      setError(null);
      setSharedWithMeParams({ skip, limit });
      await queryClient.invalidateQueries({
        queryKey: qk.conversationShares.sharedWithMe(skip, limit, orgId),
      });
    },
    [queryClient, orgId],
  );

  return {
    shares,
    sharedWithMe,
    sharedWithMeTotal,
    isLoading,
    /** A refused write, or failing that a refused read. */
    error:
      error ?? (readFailure ? getErrorMessage(readFailure, tErrors, t("failedLoadShares")) : null),
    shareConversation,
    fetchShares,
    revokeShare,
    changePermission,
    fetchSharedWithMe,
  };
}
