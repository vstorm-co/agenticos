"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { useTenantGuard, useTenantId } from "@/hooks/use-organizations";
import { apiClient } from "@/lib/api-client";
import { invalidateSoon } from "@/lib/coalesced-invalidation";
import { qk } from "@/lib/query-keys";
import { setUrlParam } from "@/lib/utils";
import {
  useAgentSelectionStore,
  useAuthStore,
  useConversationStore,
  useChatStore,
  useInChatScope,
  useLiveFeedStore,
  useOrgStore,
  useWorkingStore,
} from "@/stores";
import type {
  Conversation,
  ConversationCost,
  ConversationListResponse,
  ConversationMessage,
} from "@/types";

/**
 * One chain of pending stars per reader, tenant and conversation, so two clicks
 * on the same star cannot land out of order.
 *
 * The POST and the DELETE are separate requests and nothing made the second wait
 * for the first, so a double click could have the DELETE answered first and the
 * POST commit after it - leaving the thread starred while the screen said
 * otherwise, with no further click to reconcile them (#1254). The optimistic
 * patch still happens at once; only the request is queued, so the star is as
 * instant as it was.
 *
 * Module scope rather than a ref, because what is being ordered is requests in
 * flight in this tab and a request does not stop when the sidebar unmounts. Two
 * components reading this hook are two refs, and navigating away from the chat
 * and back is a third - each of which would send its click without waiting for
 * a pending one it cannot see. An entry is removed when its chain drains.
 *
 * The account and the organization are in the key because ordering is only owed
 * *within* one reader's view of one thread. A request that hangs is a request
 * that never drains, so a shared key would leave the next account - or the same
 * person after a switch - queued behind a promise that will not settle, on a
 * conversation they can genuinely see.
 */
const favouriteChains = new Map<string, Promise<void>>();

/** Who, where, and which thread - see `favouriteChains`. */
const chainKey = (id: string, account: string | undefined, organization: string | null) =>
  `${account ?? "-"}:${organization ?? "-"}:${id}`;

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
const MESSAGE_PAGE_SIZE = 100;
const transcriptPath = (id: string, before?: string) => {
  const params = new URLSearchParams({ latest: "true", limit: String(MESSAGE_PAGE_SIZE + 1) });
  if (before) params.set("before", before);
  return `/conversations/${encodeURIComponent(id)}/messages?${params}`;
};
const transcriptPage = (response: MessagesResponse) => ({
  items: response.items.slice(-MESSAGE_PAGE_SIZE),
  hasEarlier: response.items.length > MESSAGE_PAGE_SIZE,
});

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
  /** Leave out conversations an API key's runs opened (#2122). */
  hideApi: boolean;
}

const DEFAULT_QUERY: ConversationQuery = {
  view: "all",
  search: "",
  agentId: null,
  sortBy: "updated_at",
  sortDir: "desc",
  hideApi: false,
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
  if (query.hideApi) params.set("hide_api", "true");
  return params.toString();
}

export function useConversations(query: Partial<ConversationQuery> = {}) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("chat");
  const queryClient = useQueryClient();
  const { view, search, agentId, sortBy, sortDir, hideApi } = { ...DEFAULT_QUERY, ...query };
  // Memoized on the five values rather than on the object they arrive in: a
  // caller building that object inline hands over a new reference every render,
  // and `listKey` is a dependency of half the callbacks below - one of which
  // the sidebar runs from an effect keyed on its identity.
  const params = useMemo(
    () => listParams({ view, search, agentId, sortBy, sortDir, hideApi }),
    [view, search, agentId, sortBy, sortDir, hideApi],
  );
  const listKey = useMemo(() => qk.conversations.list(params), [params]);
  const {
    currentConversationId,
    currentMessages,
    hasEarlierMessages,
    isLoading: selectLoading,
    error,
    setCurrentConversationId,
    setCurrentMessages,
    setLoading,
    setError,
  } = useConversationStore();
  const { clearMessages } = useChatStore();
  // The scope's own stores, for reads made in a callback rather than a render.
  const chatApi = useChatStore.useApi();
  const conversationApi = useConversationStore.useApi();
  const selectionApi = useAgentSelectionStore.useApi();
  const scoped = useInChatScope();
  const tenant = useTenantId();
  const stillSameTenant = useTenantGuard();
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
  // Which re-read is the latest; an older one answering after it is dropped.
  const rereadRef = useRef(0);

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
    // While a thread on the page is at work, ask again every few seconds, so its
    // row stops saying so when the run ends - a routine's, or another tab's, as
    // well as this one's. A thread this tab handed off counts too: the listing
    // has to catch up with it before it can say anything about it.
    // While the live-update socket is up it announces the run ending, so the poll
    // is only the safety net for what it does not announce (#2219).
    refetchInterval: (query) =>
      query.state.data?.items.some((conversation) => conversation.running_since) ||
      Object.keys(useWorkingStore.getState().handedOff).length > 0
        ? useLiveFeedStore.getState().connected
          ? RUNNING_POLL_LIVE_MS
          : RUNNING_POLL_MS
        : false,
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
    () => invalidateSoon(queryClient, qk.conversations.list()),
    [queryClient],
  );

  const fetchConversations = useCallback(
    async (signal?: AbortSignal) => {
      if (signal?.aborted) return;
      const startedAs = useAuthStore.getState().user?.id;
      const startedIn = tenant;
      const stillCurrent = () =>
        !signal?.aborted && stillSameAccount(startedAs) && stillSameTenant(startedIn);
      // The list query auto-fetches and dedupes; force a fresh pull here to keep
      // the previous explicit-refresh semantics (e.g. after a new conversation is
      // created over WS).
      // URL ?id= param always takes priority: select that conversation and load
      // its messages if it isn't already the current one. Read before the wait
      // below: the address this call was made for, and a caller that does not
      // await it - a mount effect - may be gone, with its window, when it resumes.
      // A scoped chat owns no part of the address: `?id=` is the main chat's thread.
      const urlId = scoped ? null : new URLSearchParams(window.location.search).get("id");
      const stillAddressed = () =>
        scoped || new URLSearchParams(window.location.search).get("id") === urlId;
      await invalidateLists();
      if (!stillCurrent() || !stillAddressed()) return;
      if (urlId && conversationApi.getState().currentConversationId !== urlId) {
        const selectedBefore = conversationApi.getState().currentConversationId;
        const stillSelected = () =>
          conversationApi.getState().currentConversationId === selectedBefore;
        try {
          const msgs = await apiClient.get<MessagesResponse>(transcriptPath(urlId), { signal });
          if (!stillCurrent() || !stillAddressed() || !stillSelected()) return;
          clearMessages();
          setCurrentConversationId(urlId);
          const page = transcriptPage(msgs);
          setCurrentMessages(page.items, msgs.cost, page.hasEarlier);
        } catch {
          // The failure belongs to whoever asked. A refusal answering after
          // somebody else has signed in says nothing about the conversation they
          // are looking at, and clearing the id would close it under them.
          if (!stillCurrent() || !stillAddressed() || !stillSelected()) return;
          // Not accessible (deleted, no permission) - clear the stale id
          clearMessages();
          setCurrentMessages([]);
          setCurrentConversationId(null);
        }
      }
    },
    [
      invalidateLists,
      setCurrentConversationId,
      setCurrentMessages,
      clearMessages,
      conversationApi,
      scoped,
      tenant,
      stillSameTenant,
    ],
  );

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
      const startedOrg = useOrgStore.getState().activeOrgId;
      const stillSelected = () =>
        !controller.signal.aborted &&
        stillSameAccount(startedAs) &&
        useOrgStore.getState().activeOrgId === startedOrg &&
        stillSameTenant(tenant) &&
        conversationApi.getState().currentConversationId === id;

      setCurrentConversationId(id);
      clearMessages();
      setCurrentMessages([]);
      if (!scoped) setUrlParam("id", id);
      setLoading(true);
      setError(null);
      try {
        const response = await apiClient.get<MessagesResponse>(transcriptPath(id), {
          signal: controller.signal,
        });
        // Guard against a superseded request resolving after a newer select.
        if (!stillSelected()) return;
        const page = transcriptPage(response);
        setCurrentMessages(page.items, response.cost, page.hasEarlier);
      } catch (err) {
        // Ignore aborted/superseded requests - they're expected on rapid switch.
        if (
          controller.signal.aborted ||
          (err instanceof DOMException && err.name === "AbortError") ||
          // As above: one account's failure is not the next one's error banner.
          !stillSelected()
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
    [
      setCurrentConversationId,
      clearMessages,
      setCurrentMessages,
      setLoading,
      setError,
      t,
      tErrors,
      scoped,
      tenant,
      stillSameTenant,
      conversationApi,
    ],
  );

  /**
   * Read the open conversation's messages again in place - nothing cleared, no
   * loading flag, so the transcript and its scroll stay put - for turns written
   * while it is on screen: a voice call's, as each is saved (#54). An answer for
   * a conversation no longer open, or older than the latest re-read, is dropped.
   */
  const rereadConversation = useCallback(
    async (id: string) => {
      const ticket = ++rereadRef.current;
      const startedAs = useAuthStore.getState().user?.id;
      const startedOrg = useOrgStore.getState().activeOrgId;
      let response: MessagesResponse;
      try {
        response = await apiClient.get<MessagesResponse>(transcriptPath(id));
      } catch {
        // The turn is saved whatever this read did; the transcript keeps what it
        // shows, and the next saved turn reads it again.
        return;
      }
      if (
        ticket !== rereadRef.current ||
        conversationApi.getState().currentConversationId !== id ||
        useOrgStore.getState().activeOrgId !== startedOrg ||
        !stillSameTenant(tenant) ||
        !stillSameAccount(startedAs)
      ) {
        return;
      }
      const page = transcriptPage(response);
      const previous = conversationApi.getState();
      const first = previous.currentMessages[0];
      const keepsEarlier =
        first !== undefined && !page.items.some((message) => message.id === first.id);
      const merged = [
        ...new Map(
          [...previous.currentMessages, ...page.items].map((message) => [message.id, message]),
        ).values(),
      ];
      setCurrentMessages(
        merged,
        response.cost,
        keepsEarlier ? previous.hasEarlierMessages : page.hasEarlier,
      );
    },
    [setCurrentMessages, conversationApi, tenant, stillSameTenant],
  );

  const [isLoadingEarlier, setLoadingEarlier] = useState(false);
  const earlierRequest = useRef(false);
  const loadEarlierMessages = useCallback(async () => {
    const selected = conversationApi.getState();
    const id = selected.currentConversationId;
    const first = selected.currentMessages[0];
    if (!id || !first || !selected.hasEarlierMessages || earlierRequest.current) return;
    const account = useAuthStore.getState().user?.id;
    const organization = useOrgStore.getState().activeOrgId;
    const stillSelected = () =>
      stillSameAccount(account) &&
      stillSameTenant(tenant) &&
      useOrgStore.getState().activeOrgId === organization &&
      conversationApi.getState().currentConversationId === id;
    earlierRequest.current = true;
    setLoadingEarlier(true);
    try {
      const response = await apiClient.get<MessagesResponse>(transcriptPath(id, first.id));
      if (!stillSelected()) return;
      const page = transcriptPage(response);
      const previous = conversationApi.getState();
      const merged = [
        ...new Map(
          [...page.items, ...previous.currentMessages].map((message) => [message.id, message]),
        ).values(),
      ];
      setCurrentMessages(merged, previous.currentCost, page.hasEarlier);
      setError(null);
    } catch (error) {
      if (stillSelected()) {
        const message = getErrorMessage(error, tErrors, t("failedFetchMessages"));
        setError(message);
        toast.error(message);
      }
    } finally {
      earlierRequest.current = false;
      setLoadingEarlier(false);
    }
  }, [conversationApi, setCurrentMessages, setError, tenant, stillSameTenant, t, tErrors]);

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

  const patchUnread = useCallback(
    (id: string, unread: boolean) => {
      queryClient.setQueriesData<ConversationListResponse>(
        { queryKey: qk.conversations.list() },
        (prev) =>
          prev === undefined
            ? prev
            : {
                ...prev,
                items: prev.items.map((item) => (item.id === id ? { ...item, unread } : item)),
              },
      );
    },
    [queryClient],
  );

  /**
   * Record that the reader has this conversation open, so it is no longer unread.
   * The mark goes at once; a refusal puts it back, with no toast - the thread is
   * still on screen, and the next listing says the same either way.
   */
  const markRead = useCallback(
    async (id: string) => {
      patchUnread(id, false);
      try {
        await apiClient.post(`/conversations/${id}/read`, {});
      } catch {
        patchUnread(id, true);
      }
    },
    [patchUnread],
  );

  const setFavourite = useCallback(
    async (id: string, favourite: boolean) => {
      // The account this started as, for the same reason every other request
      // here captures one: a star refused after somebody else has signed in
      // would roll back *their* cached row and show them the previous
      // account's error.
      const startedAs = useAuthStore.getState().user?.id;
      // The organization too, for the same reason and one layer down:
      // `apiClient` stamps `X-Organization-Id` from the store when the request
      // is *sent*, so a click queued across a switch would be refused for a
      // conversation in the tenant it was made in - leaving the server on the
      // previous click's answer with nothing on screen saying so.
      const startedIn = useOrgStore.getState().activeOrgId;
      patchFavourite(id, favourite);
      const chains = favouriteChains;
      const key = chainKey(id, startedAs, startedIn);
      let sent = false;
      const stillHere = () =>
        stillSameAccount(startedAs) && useOrgStore.getState().activeOrgId === startedIn;
      const send = async (): Promise<void> => {
        // Checked here as well as after, and this is the half that matters: a
        // click queued behind a slow request is sent with whatever cookies the
        // browser holds when its turn comes, so waiting out a sign-out would
        // have A's queued star land as B's on a thread they both can read. The
        // checks after the call only protect the cache.
        if (!stillHere()) return;
        try {
          if (favourite) await apiClient.post(`/conversations/${id}/favourite`, {});
          else await apiClient.delete(`/conversations/${id}/favourite`);
          sent = true;
        } catch (err) {
          if (!stillHere()) return;
          // Only the newest click owns the row's displayed state; rolling back
          // from an older one would undo a star the reader has since set.
          if (chains.get(key) === mine) patchFavourite(id, !favourite);
          const message = getErrorMessage(err, tErrors, t("failedFavouriteConversation"));
          setError(message);
          toast.error(message);
        }
      };
      const mine = (chains.get(key) ?? Promise.resolve()).then(send);
      chains.set(key, mine);
      await mine;
      // Only the newest click refetches. A superseded one would answer with the
      // state its own request left behind - the server's star, while the reader
      // has since unstarred it - and patch that over the newer optimistic row.
      // The click that supersedes it invalidates when its own write lands.
      const newest = chains.get(key) === mine;
      if (newest) chains.delete(key);
      // Outside the chain: what has to be serialized is the write, and holding
      // the next click behind a refetch of the lists means a slow GET can leave
      // an unstar optimistic while the server keeps the star indefinitely.
      if (!sent || !newest || !stillHere()) return;
      // The band is an ordering the server applies, so the list is refetched to
      // move the row - the star itself is already right on screen.
      await invalidateLists();
    },
    [patchFavourite, invalidateLists, setError, t, tErrors],
  );

  const deleteConversation = useCallback(
    async (id: string) => {
      try {
        await apiClient.delete(`/conversations/${id}`);
        await invalidateLists();
        // The open conversation goes off screen with it - its transcript, its id and
        // the `?id=` too. Leaving the address made every later list fetch and every
        // reload adopt the deleted id again, so the next message was sent to a
        // conversation that no longer exists.
        if (conversationApi.getState().currentConversationId === id) {
          clearMessages();
          setCurrentMessages([]);
          setCurrentConversationId(null);
          if (!scoped) setUrlParam("id", null);
        }
        toast.success(t("conversationDeleted"));
      } catch (err) {
        const message = getErrorMessage(err, tErrors, t("failedDeleteConversation"));
        setError(message);
        toast.error(message);
      }
    },
    [
      invalidateLists,
      setCurrentConversationId,
      setCurrentMessages,
      clearMessages,
      scoped,
      setError,
      t,
      tErrors,
      conversationApi,
    ],
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
    const { defaultAgentId, select } = selectionApi.getState();
    if (defaultAgentId) select(defaultAgentId);
    // Nor in the last one's project: a new chat is an ordinary one until the
    // composer's `+` puts it in a project.
    conversationApi.getState().setPendingProjectId(null);
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
    const currentId = conversationApi.getState().currentConversationId;
    if (currentId) {
      const fetched = conversationApi.getState().currentMessages;
      const onScreen = chatApi.getState().messages;
      if (fetched.length === 0 && onScreen.length === 0) return;
    }
    clearMessages();
    setCurrentMessages([]);
    setCurrentConversationId(null);
    // Strip the stale ?id= immediately so a refresh mid-flight lands on a
    // fresh /chat instead of the old conversation. The new id will be set
    // by the WS conversation_created event on first message.
    if (!scoped) setUrlParam("id", null);
  }, [
    clearMessages,
    setCurrentMessages,
    setCurrentConversationId,
    chatApi,
    conversationApi,
    scoped,
    selectionApi,
  ]);

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
    rereadConversation,
    hasEarlierMessages,
    isLoadingEarlier,
    loadEarlierMessages,
    archiveConversation,
    unarchiveConversation,
    setFavourite,
    markRead,
    deleteConversation,
    renameConversation,
    startNewChat,
  };
}

/**
 * Conversations whose title matches `term`, archived ones included - what the
 * chat's search window lists. Nothing is asked until something is typed.
 */
/** How often a listing with a thread at work in it is read again. */
const RUNNING_POLL_MS = 4000;
/** The same poll while the live-update socket carries the run's end as an event. */
const RUNNING_POLL_LIVE_MS = 30_000;

export function useConversationSearch(term: string) {
  const params = listParams({ ...DEFAULT_QUERY, search: term });
  return useQuery({
    queryKey: qk.conversations.list(params),
    queryFn: () => apiClient.get<ConversationListResponse>(`/conversations?${params}`),
    enabled: term.trim() !== "",
  });
}
