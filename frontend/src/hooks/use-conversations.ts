"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { setUrlParam } from "@/lib/utils";
import { useAgentSelectionStore, useAuthStore, useConversationStore, useChatStore } from "@/stores";
import type {
  Conversation,
  ConversationCost,
  ConversationListResponse,
  ConversationMessage,
} from "@/types";

interface CreateConversationResponse {
  id: string;
  title?: string;
  created_at: string;
  updated_at: string;
  is_archived: boolean;
}

interface MessagesResponse {
  items: ConversationMessage[];
  total: number;
  /** What the whole thread cost, summed server-side. Null when nothing was measured. */
  cost: ConversationCost | null;
}

const PAGE_SIZE = 30;

/** Which threads a listing is about. `all` is both, and the default. */
export type ConversationView = "active" | "archived" | "all";

/** The columns `GET /conversations` will sort by. Anything else is a 422. */
export type ConversationSortKey = "title" | "created_at" | "updated_at";

export type ConversationSortDir = "asc" | "desc";

export interface ConversationQuery {
  view: ConversationView;
  /** Matched against the title, on the server. Empty means no search. */
  search: string;
  /** Threads this agent *answered in* - see the route's docstring for why that
   * is not the same as threads it owns. */
  agentId: string | null;
  sortBy: ConversationSortKey;
  sortDir: ConversationSortDir;
}

const DEFAULT_QUERY: ConversationQuery = {
  view: "all",
  search: "",
  agentId: null,
  sortBy: "updated_at",
  sortDir: "desc",
};

/**
 * The last page fetched, and which listing it was a page of.
 *
 * The second half is the load-bearing one: "was the last page full" is only an
 * answer about the list it was measured on, and switching filters puts a
 * different list on screen.
 */
interface LastPage {
  params: string;
  more: boolean;
}

/**
 * The query string one listing is fetched with, which is also its cache key.
 *
 * One expression for both so they cannot disagree: a key that omits a filter
 * the request carries is two lists sharing a cache entry, which reads as the
 * search box answering with the previous search's rows.
 */
function listParams(query: ConversationQuery): string {
  const params = new URLSearchParams({
    limit: String(PAGE_SIZE),
    sort_by: query.sortBy,
    sort_dir: query.sortDir,
  });
  if (query.view === "all") params.set("include_archived", "true");
  if (query.view === "archived") params.set("archived_only", "true");
  if (query.search.trim()) params.set("search", query.search.trim());
  if (query.agentId) params.set("agent_id", query.agentId);
  return params.toString();
}

export function useConversations(query: Partial<ConversationQuery> = {}) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("chat");
  const queryClient = useQueryClient();
  const { view, search, agentId, sortBy, sortDir } = { ...DEFAULT_QUERY, ...query };
  // Memoized on the five values rather than on the object they arrive in: a
  // caller building that object inline hands over a new reference every render,
  // and `listKey` is a dependency of half the callbacks below - one of which
  // the sidebar runs from an effect keyed on its identity.
  const params = useMemo(
    () => listParams({ view, search, agentId, sortBy, sortDir }),
    [view, search, agentId, sortBy, sortDir],
  );
  const listKey = useMemo(() => qk.conversations.list(params), [params]);
  const {
    currentConversationId,
    currentMessages,
    isLoading: selectLoading,
    error,
    setCurrentConversationId,
    setCurrentMessages,
    setLoading,
    setError,
  } = useConversationStore();
  const { clearMessages } = useChatStore();
  // State, not a ref, because it is returned. Reading a ref to build the return
  // value hands whoever asked a value React will never re-render them for - a
  // "load more" control driven by it would stay on screen after the last page
  // arrived. No consumer reads it today; the hook offers it, so it has to be
  // true when one does. The ref stays beside it for the guard in
  // `fetchMoreConversations`, which runs outside render and must see the newest
  // value synchronously.
  const [lastPage, setLastPage] = useState<LastPage | null>(null);
  const lastPageRef = useRef<LastPage | null>(null);

  const rememberHasMore = useCallback(
    (more: boolean) => {
      const measured: LastPage = { params, more };
      lastPageRef.current = measured;
      setLastPage(measured);
    },
    [params],
  );
  // Tracks the in-flight message fetch so a rapid conversation switch can abort
  // the previous request - otherwise a slower earlier fetch could resolve last
  // and overwrite the messages of the conversation the user actually selected.
  const messagesAbortRef = useRef<AbortController | null>(null);

  /**
   * Whether the account the caller started as is still the one signed in.
   *
   * Emptying the stores when a session ends does not stop a request that was
   * already in flight: it resolves afterwards and writes the previous account's
   * messages into the chat the next one is looking at. The abort controller
   * above only settles races between two selects by the same person.
   */
  const stillSameAccount = (startedAs: string | undefined) =>
    useAuthStore.getState().user?.id === startedAs;

  // React Query owns the list: cached across navigations, deduped, no refetch
  // storms (this replaces the old manual fetch + session-singleton guard).
  // The server does the narrowing - see `listParams` - so what comes back is
  // one page of one list, and `total` counts that same list rather than the
  // deployment.
  const { data, isLoading: listLoading } = useQuery({
    queryKey: listKey,
    queryFn: async () => {
      const response = await apiClient.get<ConversationListResponse>(`/conversations?${params}`);
      rememberHasMore(response.items.length >= PAGE_SIZE);
      return response;
    },
  });
  const conversations = data?.items ?? [];
  const total = data?.total ?? 0;

  // Derived, and only from a measurement of *this* list. A bare flag reset when
  // the filters move would need either a write during render or an effect, and
  // the lint rules refuse both; recording which list the last page belonged to
  // says the same thing without a side effect, and says it about the one case
  // that actually needs saying. A cached list answers from the cache without
  // running the query function above, so nothing would measure it - and a
  // search typed after scrolling to the bottom of the previous list would
  // otherwise start out believing it had already reached the end, leaving the
  // scroll handler unable to ask for page two.
  const hasMore = lastPage?.params === params ? lastPage.more : true;

  // `isLoading` historically reflected both the list fetch and the
  // select-messages fetch; preserve that union.
  const isLoading = listLoading || selectLoading;

  /**
   * Append to the cached page, unless there is no longer a page to append to.
   *
   * `setQueryData` *creates* a key that is not there, so returning `prev`
   * untouched is what stops a page arriving late from resurrecting a list that
   * has since been dropped. Signing out clears the whole cache
   * (`use-auth.ts`) and switching organization removes every query
   * (`use-active-organization.ts`) - and the second of those is the same
   * account, so the caller's own account check cannot see it. Without this the
   * previous organization's conversations reappear in the new one's sidebar,
   * under a key nothing else will refetch.
   *
   * The only writer. What a mutation does to this list is no longer something
   * the client can work out: which lists a thread belongs to is now the
   * server's answer, and a patched row that no longer matches the filter it is
   * sitting under would stay on screen claiming otherwise. So mutations
   * invalidate - see `invalidateLists` - and this writes only the page the
   * scroll asked for.
   */
  const appendPage = useCallback(
    (page: Conversation[]) => {
      queryClient.setQueryData<ConversationListResponse>(listKey, (prev) => {
        if (!prev) return prev;
        // Deduped in case a refetch raced with the append.
        const seen = new Set(prev.items.map((c) => c.id));
        return { ...prev, items: [...prev.items, ...page.filter((c) => !seen.has(c.id))] };
      });
    },
    [queryClient, listKey],
  );

  /**
   * Every conversation listing, not only the one on screen.
   *
   * Archiving a thread moves it between two of them and changes the total on
   * both; renaming one can take it out of a search it currently matches. The
   * lists nobody is looking at are the ones that would otherwise still be
   * holding it when somebody switches tab.
   */
  const invalidateLists = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.conversations.list() }),
    [queryClient],
  );

  const fetchConversations = useCallback(async () => {
    // The list query auto-fetches and dedupes; force a fresh pull here to keep
    // the previous explicit-refresh semantics (e.g. after a new conversation is
    // created over WS).
    await invalidateLists();
    // URL ?id= param always takes priority: select that conversation and load
    // its messages if it isn't already the current one.
    const startedAs = useAuthStore.getState().user?.id;
    const urlId = new URLSearchParams(window.location.search).get("id");
    if (urlId && useConversationStore.getState().currentConversationId !== urlId) {
      setCurrentConversationId(urlId);
      clearMessages();
      setCurrentMessages([]);
      try {
        const msgs = await apiClient.get<MessagesResponse>(`/conversations/${urlId}/messages`);
        if (!stillSameAccount(startedAs)) return;
        setCurrentMessages(msgs.items, msgs.cost);
      } catch {
        // The failure belongs to whoever asked. A refusal answering after
        // somebody else has signed in says nothing about the conversation they
        // are looking at, and clearing the id would close it under them.
        if (!stillSameAccount(startedAs)) return;
        // Not accessible (deleted, no permission) - clear the stale id
        setCurrentConversationId(null);
      }
    }
  }, [invalidateLists, setCurrentConversationId, setCurrentMessages, clearMessages]);

  const loadingMoreRef = useRef(false);

  const fetchMoreConversations = useCallback(async () => {
    if (loadingMoreRef.current) return;
    // The ref rather than `hasMore`, so a scroll landing in the same tick as the
    // page that ended the list still sees that it ended - and measured against
    // the list being asked about, for the reason `hasMore` is derived that way.
    const measured = lastPageRef.current;
    if (measured?.params === params && !measured.more) return;
    loadingMoreRef.current = true;
    const startedAs = useAuthStore.getState().user?.id;
    const current = queryClient.getQueryData<ConversationListResponse>(listKey)?.items ?? [];
    try {
      const response = await apiClient.get<ConversationListResponse>(
        `/conversations?${params}&skip=${current.length}`,
      );
      // Both writes below belong to the account that asked. `appendPage` is
      // safe on its own once the cache has been cleared, but `rememberHasMore`
      // is not - it would answer the new account's sidebar with the previous
      // one's pagination.
      if (!stillSameAccount(startedAs)) return;
      if (response.items.length > 0) {
        appendPage(response.items);
      }
      rememberHasMore(response.items.length >= PAGE_SIZE);
    } catch {
    } finally {
      loadingMoreRef.current = false;
    }
  }, [queryClient, listKey, params, appendPage, rememberHasMore]);

  const createConversation = useCallback(
    async (title?: string): Promise<Conversation | null> => {
      setLoading(true);
      setError(null);
      try {
        const response = await apiClient.post<CreateConversationResponse>("/conversations", {
          title,
        });
        await invalidateLists();
        return {
          id: response.id,
          title: response.title,
          created_at: response.created_at,
          updated_at: response.updated_at,
          is_archived: response.is_archived,
        };
      } catch (err) {
        const message = getErrorMessage(err, tErrors, t("failedCreateConversation"));
        setError(message);
        return null;
      } finally {
        setLoading(false);
      }
    },
    [invalidateLists, setLoading, setError, t, tErrors],
  );

  const selectConversation = useCallback(
    async (id: string) => {
      // Abort any previous in-flight message fetch so an earlier, slower request
      // can't resolve after this one and show the wrong messages.
      messagesAbortRef.current?.abort();
      const controller = new AbortController();
      messagesAbortRef.current = controller;
      const startedAs = useAuthStore.getState().user?.id;

      setCurrentConversationId(id);
      clearMessages();
      setUrlParam("id", id);
      setLoading(true);
      setError(null);
      try {
        const response = await apiClient.get<MessagesResponse>(`/conversations/${id}/messages`, {
          signal: controller.signal,
        });
        // Guard against a superseded request resolving after a newer select.
        if (controller.signal.aborted || !stillSameAccount(startedAs)) return;
        setCurrentMessages(response.items, response.cost);
      } catch (err) {
        // Ignore aborted/superseded requests - they're expected on rapid switch.
        if (
          controller.signal.aborted ||
          (err instanceof DOMException && err.name === "AbortError") ||
          // As above: one account's failure is not the next one's error banner.
          !stillSameAccount(startedAs)
        ) {
          return;
        }
        const message = getErrorMessage(err, tErrors, t("failedFetchMessages"));
        setError(message);
      } finally {
        // Only the most recent request owns the loading flag.
        if (messagesAbortRef.current === controller) {
          setLoading(false);
          messagesAbortRef.current = null;
        }
      }
    },
    [setCurrentConversationId, clearMessages, setCurrentMessages, setLoading, setError, t, tErrors],
  );

  const archiveConversation = useCallback(
    async (id: string) => {
      try {
        await apiClient.patch(`/conversations/${id}`, { is_archived: true });
        await invalidateLists();
        toast.success(t("archivedToast"));
      } catch (err) {
        const message = getErrorMessage(err, tErrors, t("failedArchiveConversation"));
        setError(message);
        toast.error(message);
      }
    },
    [invalidateLists, setError, t, tErrors],
  );

  const unarchiveConversation = useCallback(
    async (id: string) => {
      try {
        await apiClient.patch(`/conversations/${id}`, { is_archived: false });
        await invalidateLists();
        toast.success(t("conversationRestored"));
      } catch (err) {
        const message = getErrorMessage(err, tErrors, t("failedRestoreConversation"));
        setError(message);
        toast.error(message);
      }
    },
    [invalidateLists, setError, t, tErrors],
  );

  /**
   * Flip one row's star everywhere it is cached, without refetching.
   *
   * The exception to "mutations invalidate, they do not patch" above, and the
   * boundary is exact: which list a thread belongs to is the server's answer
   * and stays so, but whether *this reader* starred it is a fact about the row
   * that the client just decided. Patching it is what makes the click
   * instant; the reordering still comes from the server (#929).
   */
  const patchFavourite = useCallback(
    (id: string, favourite: boolean) => {
      queryClient.setQueriesData<ConversationListResponse>(
        { queryKey: qk.conversations.list() },
        (prev) =>
          prev === undefined
            ? prev
            : {
                ...prev,
                items: prev.items.map((item) =>
                  item.id === id ? { ...item, is_favourite: favourite } : item,
                ),
              },
      );
    },
    [queryClient],
  );

  const setFavourite = useCallback(
    async (id: string, favourite: boolean) => {
      // The account this started as, for the same reason every other request
      // here captures one: a star refused after somebody else has signed in
      // would roll back *their* cached row and show them the previous
      // account's error.
      const startedAs = useAuthStore.getState().user?.id;
      patchFavourite(id, favourite);
      try {
        if (favourite) await apiClient.post(`/conversations/${id}/favourite`, {});
        else await apiClient.delete(`/conversations/${id}/favourite`);
        if (!stillSameAccount(startedAs)) return;
        // The band is an ordering the server applies, so the list is refetched
        // to move the row - the star itself is already right on screen.
        await invalidateLists();
      } catch (err) {
        if (!stillSameAccount(startedAs)) return;
        patchFavourite(id, !favourite);
        const message = getErrorMessage(err, tErrors, t("failedFavouriteConversation"));
        setError(message);
        toast.error(message);
      }
    },
    [patchFavourite, invalidateLists, setError, t, tErrors],
  );

  const deleteConversation = useCallback(
    async (id: string) => {
      try {
        await apiClient.delete(`/conversations/${id}`);
        await invalidateLists();
        // Mirror the old store behavior: clear the active selection if it was
        // the conversation we just removed.
        if (useConversationStore.getState().currentConversationId === id) {
          setCurrentConversationId(null);
        }
        toast.success(t("conversationDeleted"));
      } catch (err) {
        const message = getErrorMessage(err, tErrors, t("failedDeleteConversation"));
        setError(message);
        toast.error(message);
      }
    },
    [invalidateLists, setCurrentConversationId, setError, t, tErrors],
  );

  const renameConversation = useCallback(
    async (id: string, title: string) => {
      try {
        await apiClient.patch(`/conversations/${id}`, { title });
        await invalidateLists();
        toast.success(t("conversationRenamed"));
      } catch (err) {
        const message = getErrorMessage(err, tErrors, t("failedRenameConversation"));
        setError(message);
        toast.error(message);
      }
    },
    [invalidateLists, setError, t, tErrors],
  );
  const startNewChat = useCallback(async () => {
    // A new chat starts with the user's default agent, when one is starred.
    // Mid-thread switches stay per-thread; this is the reset point. If the
    // default has since been unpublished, the picker resolves the stale
    // selection to the first published agent as usual.
    const { defaultAgentId, select } = useAgentSelectionStore.getState();
    if (defaultAgentId) select(defaultAgentId);
    // Reuse the conversation already open when it is empty, so a stray click does
    // not leave an untitled row in the sidebar.
    //
    // **Empty means nothing on screen**, which is the chat store and not only the
    // fetched list. A conversation created over the websocket never has its
    // messages fetched - `conversation_created` sets the store's id and the `?id=`
    // before `fetchConversations` reads them, so that fetch skips - and
    // `currentMessages` therefore stays empty for a thread that has just answered.
    // Judged on that list alone this reused it: the transcript was cleared while
    // the id and the `?id=` survived, so the strip under the input went on
    // reporting the previous turn's tokens and its workspace fill, the file panel
    // stayed open on the old workspace, and the next message landed in the
    // conversation the user thought they had left.
    const currentId = useConversationStore.getState().currentConversationId;
    if (currentId) {
      const fetched = useConversationStore.getState().currentMessages;
      const onScreen = useChatStore.getState().messages;
      if (fetched.length === 0 && onScreen.length === 0) return;
    }
    clearMessages();
    setCurrentMessages([]);
    setCurrentConversationId(null);
    // Strip the stale ?id= immediately so a refresh mid-flight lands on a
    // fresh /chat instead of the old conversation. The new id will be set
    // by the WS conversation_created event on first message.
    setUrlParam("id", null);
  }, [clearMessages, setCurrentMessages, setCurrentConversationId]);

  return {
    conversations,
    /** How many threads match, not how many were fetched. */
    total,
    currentConversationId,
    currentMessages,
    isLoading,
    error,
    fetchConversations,
    /**
     * Re-ask the server for every listing, and nothing else.
     *
     * The narrow half of `fetchConversations`, for a caller that knows the
     * stored rows have changed but is not opening one of them. Which agents
     * answered in a conversation is derived from its stored turns, so a row
     * fetched before the first answer was written carries no agent at all -
     * and nothing else in the client will ask again.
     */
    refreshConversations: invalidateLists,
    fetchMoreConversations,
    hasMore,
    createConversation,
    selectConversation,
    archiveConversation,
    unarchiveConversation,
    setFavourite,
    deleteConversation,
    renameConversation,
    startNewChat,
  };
}
