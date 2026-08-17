"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import {
  type InfiniteData,
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { apiClient, ApiError } from "@/lib/api-client";
import { parseErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type {
  ConnectorList,
  SyncSourceCreate,
  SyncSourceList,
  SyncSourceRead,
} from "@/lib/rag-api";
import { overrideSize } from "@/lib/ingestion-config";
import { useTenantGuard, useTenantId } from "@/hooks/use-organizations";
import type {
  CreateKnowledgeBaseInput,
  IngestionConfig,
  IngestionOverride,
  KBDocument,
  KBDocumentList,
  KnowledgeBase,
  KnowledgeBaseList,
} from "@/types";

export function useKnowledgeBases() {
  const queryClient = useQueryClient();
  // Every toast the catalog already held. It walked `*.tsx` alone, so this
  // directory had never been read by the guard at all (#425).
  const t = useTranslations("knowledgeBases");
  const listOrgId = useTenantId();
  const stillSameTenant = useTenantGuard();

  // React Query owns the list: cached across navigations, deduped, no refetch
  // storms. Mutations patch the cache directly so the UI stays instant.
  const {
    data: kbs = [],
    isLoading,
    error: listError,
  } = useQuery({
    queryKey: qk.kb.list(),
    queryFn: async () => (await apiClient.get<KnowledgeBaseList>("/kb")).items,
  });

  /**
   * Patch the cached list, unless the organization changed while we were away.
   *
   * `qk.kb.list()` names no tenant, and every caller writes after an await, so
   * a creation started in one organization landed in the list the next one is
   * reading - `setQueryData` recreates the key the switch had just dropped. The
   * guard is here rather than at the two call sites because there is no third
   * caller that should be allowed to forget it.
   */
  const writeCache = useCallback(
    (updater: (prev: KnowledgeBase[]) => KnowledgeBase[], startedIn: string | null) => {
      if (!stillSameTenant(startedIn)) return;
      queryClient.setQueryData<KnowledgeBase[]>(qk.kb.list(), (prev = []) => updater(prev));
    },
    [queryClient, stillSameTenant],
  );

  // Kept for API compatibility: the list auto-fetches on mount; this forces a
  // background refresh.
  const fetchKBs = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: qk.kb.list() });
  }, [queryClient]);

  /**
   * Create a collection, and let the caller decide how a refusal is shown.
   *
   * This used to swallow the error and toast "Failed to create knowledge base",
   * which threw away the only sentence that said what was actually wrong. The
   * dialog owns the fields, so the dialog owns the refusal.
   */
  const createKB = useCallback(
    async (input: CreateKnowledgeBaseInput): Promise<KnowledgeBase> => {
      const startedIn = listOrgId;
      const kb = await apiClient.post<KnowledgeBase>("/kb", input);
      writeCache((prev) => [kb, ...prev], startedIn);
      toast.success(t("created"));
      return kb;
    },
    [writeCache, listOrgId, t],
  );

  /**
   * Rename a collection, letting the caller decide how a refusal is shown.
   *
   * The refusal is rethrown, like `createKB` and `updateIngestion`: a rename is
   * driven from a dialog that owns the name field, and a name already taken
   * belongs beside that field, not in a generic toast the dialog cannot read.
   */
  const patchKB = useCallback(
    async (id: string, patch: Partial<Pick<KnowledgeBase, "name" | "description">>) => {
      const startedIn = listOrgId;
      const updated = await apiClient.patch<KnowledgeBase>(`/kb/${id}`, patch);
      writeCache((prev) => prev.map((k) => (k.id === id ? updated : k)), startedIn);
      toast.success(t("updated"));
      return updated;
    },
    [writeCache, listOrgId, t],
  );

  // There is deliberately no delete here. A collection is deleted from its own
  // page, where the document count is on screen - `useKBDetail.deleteCollection`
  // - and a second path that swallowed the refusal and patched this cache
  // optimistically was two answers to one question.
  return { kbs, isLoading, listError, fetchKBs, createKB, patchKB };
}

/**
 * Hook for the KB detail page: fetches one KB and its documents, exposes
 * upload/delete mutations. Refetches the document list after each mutation
 * since ingestion progresses asynchronously on the worker.
 */
/** Documents fetched per page. Backend `/kb/{id}/documents` caps `limit` at 100. */
const DOCS_PAGE_SIZE = 20;

/**
 * Which of the detail page's side queries failed on the last refresh.
 *
 * The KB and its documents are load-bearing - their failure is the hook's
 * `error` and the whole page says so. These three are sections: a failed one
 * must say "could not load", per section, because its empty state reads as a
 * fact ("no connectors enabled") that a 502 has not established.
 */
export interface KBSectionFailures {
  syncSources: boolean;
  orgIntegrations: boolean;
  connectors: boolean;
}

/** In-flight upload progress entry surfaced by `useKBDetail`. */
export interface UploadProgress {
  /** Stable per-upload id (a file can be uploaded twice with the same name). */
  uploadId: string;
  filename: string;
  /** 0–100. `null` while the browser can't report a determinate size. */
  percent: number | null;
}

export function useKBDetail(id: string | null) {
  const queryClient = useQueryClient();
  const t = useTranslations("knowledgeBases");
  const activeOrgId = useTenantId();

  /**
   * Whether the organization a mutation started in is still the active one.
   *
   * The reads no longer need this: they live in the query cache now, and the
   * tenant switch drops that cache wholesale (`useTenantCacheReset` calls
   * `queryClient.removeQueries()` in a layout effect). The mutations still do -
   * each writes to the cache after an await, and a write that lands past the
   * switch would re-create the key the switch had just dropped, painting the
   * previous tenant's row under the new one's name.
   */
  const stillSameTenant = useTenantGuard();

  // The two failures the paging/loading callbacks report, resolved *here* rather
  // than inside them. A string is a stable dependency by value where a translator
  // is one only as long as it is memoised; `refresh` is a dependency of the page's
  // effect and of the ingest poll, so it must not be able to change identity (#446).
  const failedLoadMessage = t("failedLoad");
  const failedLoadMoreMessage = t("failedLoadMoreDocuments");

  // Per-file upload progress (0–100), keyed by a stable per-upload id. Entries
  // are added when an upload starts and removed once it settles.
  const [uploadProgress, setUploadProgress] = useState<UploadProgress[]>([]);
  // An upload is in flight whenever there's at least one progress entry. Derived
  // rather than stored so sequential/concurrent uploads stay consistent.
  const isUploading = uploadProgress.length > 0;
  // Monotonic counter so concurrent/repeat uploads of same-named files get
  // distinct progress entries.
  const uploadIdRef = useRef(0);

  const enabled = id !== null;

  // The collection, its documents and the three sources feeding it, each a
  // query keyed under `["kb", id]`. `retry: false` because these are one-shot
  // reads with their own error UI: a 403 on a section is that section saying
  // "not for you", not a flake to retry, and a failed collection read is the
  // page's error rather than something to hammer.
  const kbQuery = useQuery({
    queryKey: qk.kb.detail(id ?? "none"),
    queryFn: () => apiClient.get<KnowledgeBase>(`/kb/${id}`),
    enabled,
    retry: false,
  });

  const documentsQuery = useInfiniteQuery({
    queryKey: qk.kb.documents(id ?? "none"),
    queryFn: ({ pageParam }) =>
      apiClient.get<KBDocumentList>(
        `/kb/${id}/documents?skip=${pageParam}&limit=${DOCS_PAGE_SIZE}`,
      ),
    enabled,
    retry: false,
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, page) => sum + page.items.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
  });

  const sourcesQuery = useQuery({
    queryKey: qk.kb.syncSources(id ?? "none"),
    queryFn: () => apiClient.get<SyncSourceList>(`/kb/${id}/sync-sources`),
    enabled,
    retry: false,
  });
  const orgIntegrationsQuery = useQuery({
    queryKey: qk.kb.orgIntegrations(id ?? "none"),
    queryFn: () => apiClient.get<SyncSourceList>(`/kb/${id}/sync-sources/org-integrations`),
    enabled,
    retry: false,
  });
  const connectorsQuery = useQuery({
    queryKey: qk.kb.connectors(id ?? "none"),
    queryFn: () => apiClient.get<ConnectorList>(`/kb/${id}/sync-sources/connectors`),
    enabled,
    retry: false,
  });

  const kb = kbQuery.data ?? null;

  // Flattened and de-duplicated across pages: a poll can re-read a page the
  // append had already fetched, and two copies of one document would list it
  // twice. `useMemo` over the query's `data` keeps the array's identity stable
  // when a poll finds nothing changed, which is what lets `usePollWhileIngesting`
  // stop scheduling - it keys the next poll on a change in the list.
  const documents = useMemo(() => {
    const seen = new Set<string>();
    const flattened: KBDocument[] = [];
    for (const page of documentsQuery.data?.pages ?? []) {
      for (const document of page.items) {
        if (!seen.has(document.id)) {
          seen.add(document.id);
          flattened.push(document);
        }
      }
    }
    return flattened;
  }, [documentsQuery.data]);
  const documentsTotal = documentsQuery.data?.pages.at(-1)?.total ?? 0;

  const syncSources = sourcesQuery.data?.items ?? [];
  const orgIntegrations = orgIntegrationsQuery.data?.items ?? [];
  const connectors = connectorsQuery.data?.items ?? [];
  const sectionFailures: KBSectionFailures = {
    syncSources: sourcesQuery.isError,
    orgIntegrations: orgIntegrationsQuery.isError,
    connectors: connectorsQuery.isError,
  };

  // The collection and its documents are load-bearing: their failure is the
  // page's error. The three sections are not - they report through
  // `sectionFailures` instead.
  const loadError = kbQuery.error ?? documentsQuery.error;
  const error = loadError
    ? loadError instanceof Error
      ? loadError.message
      : failedLoadMessage
    : null;

  // A first load of a load-bearing read that failed with nothing to show - as
  // opposed to a refresh that failed over data already on screen. `isLoadingError`
  // is exactly that distinction (errored *and* holding no data), and it is what
  // lets the page show its whole-page error on a cold failure while a failed
  // refresh keeps the last good answer under a "may be stale" banner. The
  // documents failing counts: they are not caught to an empty list, so a 502 on
  // them must not read as "no documents".
  const loadFailed = kbQuery.isLoadingError || documentsQuery.isLoadingError;

  const isLoading =
    kbQuery.isFetching || (documentsQuery.isFetching && !documentsQuery.isFetchingNextPage);
  const isLoadingMoreDocs = documentsQuery.isFetchingNextPage;

  /**
   * Reload the collection, its documents and the three sources feeding it.
   *
   * One invalidation of the `["kb", id]` prefix, which every query above is
   * keyed beneath - so a single call refetches the whole page. Stable in
   * identity (it closes over nothing that changes per render), which the page's
   * `useEffect([refresh])` and the ingest poll both depend on.
   */
  const { fetchNextPage } = documentsQuery;
  const refresh = useCallback(async () => {
    if (!id) return;
    await queryClient.invalidateQueries({ queryKey: qk.kb.detail(id) });
  }, [id, queryClient]);

  /** Append the next page of documents (server-side skip/limit pagination). */
  const loadMoreDocuments = useCallback(async () => {
    if (!id) return;
    try {
      await fetchNextPage({ throwOnError: true });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : failedLoadMoreMessage);
    }
  }, [id, fetchNextPage, failedLoadMoreMessage]);

  /**
   * Replace how this collection's documents are parsed, from now on.
   *
   * The refusal is rethrown rather than toasted here: the dialog owns the
   * fields, so the dialog decides which input a rejected chunk size belongs
   * under. Nothing already indexed is re-parsed, which the dialog says out loud.
   */
  const updateIngestion = useCallback(
    async (config: IngestionConfig): Promise<KnowledgeBase> => {
      // i18n-exempt: a narrowing guard on a hook only mounted with an id, not copy.
      if (!id) throw new Error("No knowledge base is open");
      const startedIn = activeOrgId;
      const updated = await apiClient.patch<KnowledgeBase>(`/kb/${id}`, {
        ingestion_config: config,
      });
      // The caller is handed the row either way - it asked for the save and the
      // save happened - but it is not written into a page showing somebody else.
      if (stillSameTenant(startedIn)) {
        queryClient.setQueryData(qk.kb.detail(id), updated);
        toast.success(t("ingestionSaved"));
      }
      return updated;
    },
    [id, activeOrgId, stillSameTenant, queryClient, t],
  );

  const uploadDocument = useCallback(
    async (file: File, override?: IngestionOverride) => {
      if (!id) return;
      const startedIn = activeOrgId;
      const uploadId = `${uploadIdRef.current++}`;
      setUploadProgress((prev) => [...prev, { uploadId, filename: file.name, percent: 0 }]);

      const setPercent = (percent: number | null) =>
        setUploadProgress((prev) =>
          prev.map((p) => (p.uploadId === uploadId ? { ...p, percent } : p)),
        );
      const clear = () => setUploadProgress((prev) => prev.filter((p) => p.uploadId !== uploadId));

      try {
        const formData = new FormData();
        formData.append("file", file);
        // One form field holding a JSON object, which is how the API takes a
        // per-upload departure - it rides in the multipart body rather than
        // having a schema of its own. Sent only when it says something: an
        // empty object would mark the document as overridden for no reason.
        if (override !== undefined && overrideSize(override) > 0) {
          formData.append("ingestion", JSON.stringify(override));
        }
        // Use XHR (not fetch) so we can read real byte-level upload progress via
        // upload.onprogress. The BFF route forwards the multipart body raw to
        // FastAPI's UploadFile handler, same as the old fetch path.
        await new Promise<void>((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open("POST", `/api/kb/${id}/documents`);
          xhr.withCredentials = true;
          // XHR is here for byte-level progress, which `fetch` cannot report -
          // but going around `apiClient` means going around the header it
          // attaches, and `/kb` is org-scoped. Without it the backend falls
          // back to the personal organization, where this knowledge base does
          // not exist, and the upload fails for a reason nothing on screen
          // explains.
          if (startedIn) xhr.setRequestHeader("X-Organization-Id", startedIn);
          xhr.upload.onprogress = (event) => {
            if (event.lengthComputable) {
              setPercent(Math.min(100, Math.round((event.loaded / event.total) * 100)));
            } else {
              // Indeterminate: browser can't compute total - fall back to null.
              setPercent(null);
            }
          };
          // Bytes are flushed to the server; the server is now ingesting.
          xhr.upload.onload = () => setPercent(100);
          xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) {
              resolve();
            } else {
              // The backend answers `{"error": {...}}` and this looked for
              // `detail`, so every refusal an upload can produce - an
              // unsupported extension for the chosen parser, a file over the
              // limit, a malformed `ingestion` field - reached the person as
              // "Upload failed". `parseErrorMessage` knows all three wire
              // shapes; the body is handed to `ApiError` as well so a caller
              // can still read the code and details off it.
              let body: unknown = null;
              try {
                body = JSON.parse(xhr.responseText);
              } catch {
                /* non-JSON error body */
              }
              reject(new ApiError(xhr.status, parseErrorMessage(body, t("uploadFailed")), body));
            }
          };
          xhr.onerror = () => reject(new ApiError(0, t("uploadFailed")));
          xhr.send(formData);
        });
        toast.success(t("uploaded", { name: file.name }));
        await refresh();
      } catch (e) {
        const msg = e instanceof Error ? e.message : t("uploadFailed");
        toast.error(msg);
        throw e;
      } finally {
        clear();
      }
    },
    [id, refresh, activeOrgId, t],
  );

  const deleteDocument = useCallback(
    async (docId: string) => {
      if (!id) return;
      const startedIn = activeOrgId;
      try {
        await apiClient.delete(`/kb/${id}/documents/${docId}`);
        if (!stillSameTenant(startedIn)) return;
        // Drop the row from every loaded page, and the count with it, rather
        // than refetching: the page polls anyway, and an optimistic removal is
        // what keeps the table from flashing the document back for a beat.
        queryClient.setQueryData<InfiniteData<KBDocumentList>>(qk.kb.documents(id), (prev) =>
          prev
            ? {
                ...prev,
                pages: prev.pages.map((page) => ({
                  items: page.items.filter((d) => d.id !== docId),
                  total: Math.max(0, page.total - 1),
                })),
              }
            : prev,
        );
        toast.success(t("documentRemoved"));
      } catch (e) {
        toast.error(e instanceof Error ? e.message : t("failedDeleteDocument"));
      }
    },
    [id, activeOrgId, stillSameTenant, queryClient, t],
  );

  /**
   * Delete the open collection and everything indexed in it.
   *
   * The list's cache is invalidated rather than patched: `useKnowledgeBases`
   * owns `qk.kb.list()`, and the page this returns to is the one that reads it.
   * There is no tenant guard here for the same reason there is nothing to write
   * - the row is gone from the server whichever organization is active by the
   * time it answers.
   *
   * The refusal is rethrown as well as toasted, because the caller navigates
   * away on success: swallowing it would leave somebody looking at `/kb` with a
   * collection still in it and a toast explaining why.
   */
  const deleteCollection = useCallback(async () => {
    if (!id) return;
    try {
      await apiClient.delete(`/kb/${id}`);
      queryClient.invalidateQueries({ queryKey: qk.kb.list() });
      toast.success(t("deleted"));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("failedDelete"));
      throw e;
    }
  }, [id, queryClient, t]);

  const createSyncSource = useCallback(
    async (data: SyncSourceCreate) => {
      if (!id) return;
      const startedIn = activeOrgId;
      try {
        const created = await apiClient.post<SyncSourceRead>(`/kb/${id}/sync-sources`, data);
        // Prepended to the cached list rather than the whole list refetched -
        // and only when the tenant has not moved, so a late answer adds the
        // previous organization's row to its own list, never the new one's.
        if (stillSameTenant(startedIn)) {
          queryClient.setQueryData<SyncSourceList>(qk.kb.syncSources(id), (prev) =>
            prev
              ? { items: [created, ...prev.items], total: prev.total + 1 }
              : { items: [created], total: 1 },
          );
        }
        toast.success(t("syncSourceConnected"));
        return created;
      } catch (e) {
        toast.error(e instanceof Error ? e.message : t("failedCreateSyncSource"));
        throw e;
      }
    },
    [id, activeOrgId, stillSameTenant, queryClient, t],
  );

  const cloneSyncSource = useCallback(
    async (sourceId: string, collectionName: string, name: string) => {
      if (!id) return;
      const startedIn = activeOrgId;
      try {
        const created = await apiClient.post<SyncSourceRead>(
          `/kb/${id}/sync-sources/${sourceId}/clone`,
          { collection_name: collectionName, name },
        );
        if (stillSameTenant(startedIn)) {
          queryClient.setQueryData<SyncSourceList>(qk.kb.syncSources(id), (prev) =>
            prev
              ? { items: [created, ...prev.items], total: prev.total + 1 }
              : { items: [created], total: 1 },
          );
          // Out of the offer list in the same breath, or it is offered again and
          // cloning it twice produces two sources pulling the same folder.
          queryClient.setQueryData<SyncSourceList>(qk.kb.orgIntegrations(id), (prev) =>
            prev
              ? {
                  items: prev.items.filter((s) => s.id !== sourceId),
                  total: Math.max(0, prev.total - 1),
                }
              : prev,
          );
          toast.success(t("integrationCloned"));
        }
        return created;
      } catch (e) {
        toast.error(e instanceof Error ? e.message : t("failedCloneIntegration"));
        throw e;
      }
    },
    [id, activeOrgId, stillSameTenant, queryClient, t],
  );

  const triggerSyncSource = useCallback(
    async (sourceId: string) => {
      if (!id) return;
      try {
        await apiClient.post(`/kb/${id}/sync-sources/${sourceId}/trigger`);
        toast.success(t("syncStarted"));
        // Refresh later to pick up new docs that the worker pulls in.
        setTimeout(() => refresh(), 2000);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : t("failedTriggerSync"));
      }
    },
    [id, refresh, t],
  );

  const deleteSyncSource = useCallback(
    async (sourceId: string) => {
      if (!id) return;
      const startedIn = activeOrgId;
      try {
        await apiClient.delete(`/kb/${id}/sync-sources/${sourceId}`);
        if (!stillSameTenant(startedIn)) return;
        queryClient.setQueryData<SyncSourceList>(qk.kb.syncSources(id), (prev) =>
          prev
            ? {
                items: prev.items.filter((s) => s.id !== sourceId),
                total: Math.max(0, prev.total - 1),
              }
            : prev,
        );
        toast.success(t("syncSourceRemoved"));
      } catch (e) {
        toast.error(e instanceof Error ? e.message : t("failedRemoveSyncSource"));
      }
    },
    [id, activeOrgId, stillSameTenant, queryClient, t],
  );

  return {
    kb,
    documents,
    documentsTotal,
    hasMoreDocuments: documentsQuery.hasNextPage,
    loadFailed,
    syncSources,
    orgIntegrations,
    connectors,
    sectionFailures,
    isLoading,
    isLoadingMoreDocs,
    isUploading,
    uploadProgress,
    error,
    refresh,
    loadMoreDocuments,
    updateIngestion,
    uploadDocument,
    deleteDocument,
    deleteCollection,
    createSyncSource,
    cloneSyncSource,
    triggerSyncSource,
    deleteSyncSource,
  };
}
