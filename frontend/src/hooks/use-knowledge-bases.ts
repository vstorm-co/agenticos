"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiClient, ApiError } from "@/lib/api-client";
import { parseErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type {
  ConnectorInfo,
  ConnectorList,
  SyncSourceCreate,
  SyncSourceList,
  SyncSourceRead,
} from "@/lib/rag-api";
import { overrideSize } from "@/lib/ingestion-config";
import { useChanged } from "@/hooks/use-changed";
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
  const listOrgId = useTenantId();
  const stillSameTenant = useTenantGuard();

  // React Query owns the list: cached across navigations, deduped, no refetch
  // storms. Mutations patch the cache directly so the UI stays instant.
  const { data: kbs = [], isLoading } = useQuery({
    queryKey: qk.kb.list(),
    queryFn: async () => (await apiClient.get<KnowledgeBaseList>("/kb")).items,
  });

  /**
   * Patch the cached list, unless the organization changed while we were away.
   *
   * `qk.kb.list()` names no tenant, and every caller writes after an await, so
   * a creation started in one organization landed in the list the next one is
   * reading - `setQueryData` recreates the key the switch had just dropped. The
   * guard is here rather than at the three call sites because there is no
   * fourth caller that should be allowed to forget it.
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
      toast.success("Knowledge base created");
      return kb;
    },
    [writeCache, listOrgId],
  );

  const patchKB = useCallback(
    async (id: string, patch: Partial<Pick<KnowledgeBase, "name" | "description">>) => {
      const startedIn = listOrgId;
      try {
        const updated = await apiClient.patch<KnowledgeBase>(`/kb/${id}`, patch);
        writeCache((prev) => prev.map((k) => (k.id === id ? updated : k)), startedIn);
        toast.success("Knowledge base updated");
        return updated;
      } catch {
        toast.error("Failed to update knowledge base");
        return null;
      }
    },
    [writeCache, listOrgId],
  );

  // There is deliberately no delete here. A collection is deleted from its own
  // page, where the document count is on screen - `useKBDetail.deleteCollection`
  // - and a second path that swallowed the refusal and patched this cache
  // optimistically was two answers to one question.
  return { kbs, isLoading, fetchKBs, createKB, patchKB };
}

/**
 * Hook for the KB detail page: fetches one KB and its documents, exposes
 * upload/delete mutations. Refetches the document list after each mutation
 * since ingestion progresses asynchronously on the worker.
 */
/** Documents fetched per page. Backend `/kb/{id}/documents` caps `limit` at 100. */
const DOCS_PAGE_SIZE = 20;

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
  const [kb, setKb] = useState<KnowledgeBase | null>(null);
  const [documents, setDocuments] = useState<KBDocument[]>([]);
  const [documentsTotal, setDocumentsTotal] = useState(0);
  const [syncSources, setSyncSources] = useState<SyncSourceRead[]>([]);
  const [orgIntegrations, setOrgIntegrations] = useState<SyncSourceRead[]>([]);
  const [connectors, setConnectors] = useState<ConnectorInfo[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingMoreDocs, setIsLoadingMoreDocs] = useState(false);
  // Per-file upload progress (0–100), keyed by a stable per-upload id. Entries
  // are added when an upload starts and removed once it settles.
  const [uploadProgress, setUploadProgress] = useState<UploadProgress[]>([]);
  const [error, setError] = useState<string | null>(null);

  // A knowledge base belongs to one organization, and everything above is a
  // response read as that one. Dropping the query cache on a tenant switch does
  // not reach any of it - this hook keeps its data in `useState` - so without
  // this the page went on showing the previous tenant's documents, and an open
  // file viewer went on showing their file. Cleared during render, so the
  // stale rows are never painted under the new organization's name; `refresh`
  // takes the organization in its dependencies below, which is what sends the
  // page back to the server for whatever this id means here, if anything.
  const activeOrgId = useTenantId();
  if (useChanged(activeOrgId)) {
    setKb(null);
    setDocuments([]);
    setDocumentsTotal(0);
    setSyncSources([]);
    setOrgIntegrations([]);
    setConnectors([]);
    setError(null);
  }

  /**
   * Whether the organization a request started in is still the active one.
   *
   * Clearing the state above is no use on its own: every read and every
   * mutation here writes after an await, and an answer that lands past the
   * switch refills what was just emptied - the previous tenant's knowledge base
   * name and configuration, under the new tenant's.
   */
  // An upload is in flight whenever there's at least one progress entry. Derived
  // rather than stored so sequential/concurrent uploads stay consistent.
  const isUploading = uploadProgress.length > 0;

  // Tracks how many documents are loaded without putting `documents.length` in
  // the deps of `refresh`/`loadMoreDocuments` - keeping them stable so the
  // page's `useEffect([refresh])` runs once instead of looping after each fetch.
  const stillSameTenant = useTenantGuard();

  const loadedDocCountRef = useRef(0);
  useEffect(() => {
    loadedDocCountRef.current = documents.length;
  }, [documents.length]);

  // Monotonic counter so concurrent/repeat uploads of same-named files get
  // distinct progress entries.
  const uploadIdRef = useRef(0);

  /**
   * Reload the KB and the first page of documents (plus sync sources and
   * connectors). Refetches as many documents as are currently displayed so an
   * already-expanded list keeps its items after a mutation/poll.
   */
  const refresh = useCallback(async () => {
    if (!id) return;
    const startedIn = activeOrgId;
    setIsLoading(true);
    setError(null);
    try {
      // Keep at least the first page; re-fetch however many are already shown
      // (capped at the backend's max limit of 100).
      const limit = Math.min(Math.max(loadedDocCountRef.current, DOCS_PAGE_SIZE), 100);
      const [kbData, docList, sourceList, orgIntList, connectorList] = await Promise.all([
        apiClient.get<KnowledgeBase>(`/kb/${id}`),
        apiClient.get<KBDocumentList>(`/kb/${id}/documents?skip=0&limit=${limit}`),
        apiClient.get<SyncSourceList>(`/kb/${id}/sync-sources`).catch(() => ({
          items: [] as SyncSourceRead[],
          total: 0,
        })),
        apiClient.get<SyncSourceList>(`/kb/${id}/sync-sources/org-integrations`).catch(() => ({
          items: [] as SyncSourceRead[],
          total: 0,
        })),
        apiClient.get<ConnectorList>(`/kb/${id}/sync-sources/connectors`).catch(() => ({
          items: [] as ConnectorInfo[],
        })),
      ]);
      if (!stillSameTenant(startedIn)) return;
      setKb(kbData);
      setDocuments(docList.items);
      setDocumentsTotal(docList.total);
      setSyncSources(sourceList.items);
      setOrgIntegrations(orgIntList.items);
      setConnectors(connectorList.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load knowledge base");
    } finally {
      setIsLoading(false);
    }
  }, [id, activeOrgId, stillSameTenant]);

  /** Append the next page of documents (server-side skip/limit pagination). */
  const loadMoreDocuments = useCallback(async () => {
    if (!id) return;
    const startedIn = activeOrgId;
    setIsLoadingMoreDocs(true);
    try {
      const docList = await apiClient.get<KBDocumentList>(
        `/kb/${id}/documents?skip=${loadedDocCountRef.current}&limit=${DOCS_PAGE_SIZE}`,
      );
      if (!stillSameTenant(startedIn)) return;
      // Dedupe in case a poll/refresh raced with the append.
      setDocuments((prev) => {
        const seen = new Set(prev.map((d) => d.id));
        return [...prev, ...docList.items.filter((d) => !seen.has(d.id))];
      });
      setDocumentsTotal(docList.total);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to load more documents");
    } finally {
      setIsLoadingMoreDocs(false);
    }
  }, [id, activeOrgId, stillSameTenant]);

  /**
   * Replace how this collection's documents are parsed, from now on.
   *
   * The refusal is rethrown rather than toasted here: the dialog owns the
   * fields, so the dialog decides which input a rejected chunk size belongs
   * under. Nothing already indexed is re-parsed, which the dialog says out loud.
   */
  const updateIngestion = useCallback(
    async (config: IngestionConfig): Promise<KnowledgeBase> => {
      if (!id) throw new Error("No knowledge base is open");
      const startedIn = activeOrgId;
      const updated = await apiClient.patch<KnowledgeBase>(`/kb/${id}`, {
        ingestion_config: config,
      });
      // The caller is handed the row either way - it asked for the save and the
      // save happened - but it is not written into a page showing somebody else.
      if (stillSameTenant(startedIn)) {
        setKb(updated);
        toast.success("Ingestion settings saved");
      }
      return updated;
    },
    [id, activeOrgId, stillSameTenant],
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
              reject(new ApiError(xhr.status, parseErrorMessage(body, "Upload failed"), body));
            }
          };
          xhr.onerror = () => reject(new ApiError(0, "Upload failed"));
          xhr.send(formData);
        });
        toast.success(`Uploaded ${file.name}`);
        await refresh();
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Upload failed";
        toast.error(msg);
        throw e;
      } finally {
        clear();
      }
    },
    [id, refresh, activeOrgId],
  );

  const deleteDocument = useCallback(
    async (docId: string) => {
      if (!id) return;
      const startedIn = activeOrgId;
      try {
        await apiClient.delete(`/kb/${id}/documents/${docId}`);
        if (!stillSameTenant(startedIn)) return;
        setDocuments((prev) => prev.filter((d) => d.id !== docId));
        setDocumentsTotal((prev) => Math.max(0, prev - 1));
        toast.success("Document removed");
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Failed to delete document");
      }
    },
    [id, activeOrgId, stillSameTenant],
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
      toast.success("Knowledge base deleted");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete knowledge base");
      throw e;
    }
  }, [id, queryClient]);

  const createSyncSource = useCallback(
    async (data: SyncSourceCreate) => {
      if (!id) return;
      const startedIn = activeOrgId;
      try {
        const created = await apiClient.post<SyncSourceRead>(`/kb/${id}/sync-sources`, data);
        // An append, not a replace - so a late answer does not overwrite the
        // new tenant's list, it adds the previous tenant's row to it.
        if (stillSameTenant(startedIn)) setSyncSources((prev) => [created, ...prev]);
        toast.success("Sync source connected");
        return created;
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Failed to create sync source");
        throw e;
      }
    },
    [id, activeOrgId, stillSameTenant],
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
          setSyncSources((prev) => [created, ...prev]);
          setOrgIntegrations((prev) => prev.filter((s) => s.id !== sourceId));
          toast.success("Integration cloned to this knowledge base");
        }
        return created;
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Failed to clone integration");
        throw e;
      }
    },
    [id, activeOrgId, stillSameTenant],
  );

  const triggerSyncSource = useCallback(
    async (sourceId: string) => {
      if (!id) return;
      try {
        await apiClient.post(`/kb/${id}/sync-sources/${sourceId}/trigger`);
        toast.success("Sync started - documents will appear as they ingest");
        // Refresh later to pick up new docs that the worker pulls in.
        setTimeout(() => refresh(), 2000);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Failed to trigger sync");
      }
    },
    [id, refresh],
  );

  const deleteSyncSource = useCallback(
    async (sourceId: string) => {
      if (!id) return;
      const startedIn = activeOrgId;
      try {
        await apiClient.delete(`/kb/${id}/sync-sources/${sourceId}`);
        if (!stillSameTenant(startedIn)) return;
        setSyncSources((prev) => prev.filter((s) => s.id !== sourceId));
        toast.success("Sync source removed");
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Failed to remove sync source");
      }
    },
    [id, activeOrgId, stillSameTenant],
  );

  return {
    kb,
    documents,
    documentsTotal,
    hasMoreDocuments: documents.length < documentsTotal,
    syncSources,
    orgIntegrations,
    connectors,
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
