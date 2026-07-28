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

  // React Query owns the list: cached across navigations, deduped, no refetch
  // storms. Mutations patch the cache directly so the UI stays instant.
  const { data: kbs = [], isLoading } = useQuery({
    queryKey: qk.kb.list(),
    queryFn: async () => (await apiClient.get<KnowledgeBaseList>("/kb")).items,
  });

  const writeCache = useCallback(
    (updater: (prev: KnowledgeBase[]) => KnowledgeBase[]) =>
      queryClient.setQueryData<KnowledgeBase[]>(qk.kb.list(), (prev = []) => updater(prev)),
    [queryClient],
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
      const kb = await apiClient.post<KnowledgeBase>("/kb", input);
      writeCache((prev) => [kb, ...prev]);
      toast.success("Knowledge base created");
      return kb;
    },
    [writeCache],
  );

  const patchKB = useCallback(
    async (id: string, patch: Partial<Pick<KnowledgeBase, "name" | "description">>) => {
      try {
        const updated = await apiClient.patch<KnowledgeBase>(`/kb/${id}`, patch);
        writeCache((prev) => prev.map((k) => (k.id === id ? updated : k)));
        toast.success("Knowledge base updated");
        return updated;
      } catch {
        toast.error("Failed to update knowledge base");
        return null;
      }
    },
    [writeCache],
  );

  const deleteKB = useCallback(
    async (id: string) => {
      try {
        await apiClient.delete(`/kb/${id}`);
        writeCache((prev) => prev.filter((k) => k.id !== id));
        toast.success("Knowledge base deleted");
      } catch {
        toast.error("Failed to delete knowledge base");
      }
    },
    [writeCache],
  );

  return { kbs, isLoading, fetchKBs, createKB, patchKB, deleteKB };
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

  // An upload is in flight whenever there's at least one progress entry. Derived
  // rather than stored so sequential/concurrent uploads stay consistent.
  const isUploading = uploadProgress.length > 0;

  // Tracks how many documents are loaded without putting `documents.length` in
  // the deps of `refresh`/`loadMoreDocuments` - keeping them stable so the
  // page's `useEffect([refresh])` runs once instead of looping after each fetch.
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
  }, [id]);

  /** Append the next page of documents (server-side skip/limit pagination). */
  const loadMoreDocuments = useCallback(async () => {
    if (!id) return;
    setIsLoadingMoreDocs(true);
    try {
      const docList = await apiClient.get<KBDocumentList>(
        `/kb/${id}/documents?skip=${loadedDocCountRef.current}&limit=${DOCS_PAGE_SIZE}`,
      );
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
  }, [id]);

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
      const updated = await apiClient.patch<KnowledgeBase>(`/kb/${id}`, {
        ingestion_config: config,
      });
      setKb(updated);
      toast.success("Ingestion settings saved");
      return updated;
    },
    [id],
  );

  const uploadDocument = useCallback(
    async (file: File, override?: IngestionOverride) => {
      if (!id) return;
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
    [id, refresh],
  );

  const deleteDocument = useCallback(
    async (docId: string) => {
      if (!id) return;
      try {
        await apiClient.delete(`/kb/${id}/documents/${docId}`);
        setDocuments((prev) => prev.filter((d) => d.id !== docId));
        setDocumentsTotal((prev) => Math.max(0, prev - 1));
        toast.success("Document removed");
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Failed to delete document");
      }
    },
    [id],
  );

  const createSyncSource = useCallback(
    async (data: SyncSourceCreate) => {
      if (!id) return;
      try {
        const created = await apiClient.post<SyncSourceRead>(`/kb/${id}/sync-sources`, data);
        setSyncSources((prev) => [created, ...prev]);
        toast.success("Sync source connected");
        return created;
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Failed to create sync source");
        throw e;
      }
    },
    [id],
  );

  const cloneSyncSource = useCallback(
    async (sourceId: string, collectionName: string, name: string) => {
      if (!id) return;
      try {
        const created = await apiClient.post<SyncSourceRead>(
          `/kb/${id}/sync-sources/${sourceId}/clone`,
          { collection_name: collectionName, name },
        );
        setSyncSources((prev) => [created, ...prev]);
        setOrgIntegrations((prev) => prev.filter((s) => s.id !== sourceId));
        toast.success("Integration cloned to this knowledge base");
        return created;
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Failed to clone integration");
        throw e;
      }
    },
    [id],
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
      try {
        await apiClient.delete(`/kb/${id}/sync-sources/${sourceId}`);
        setSyncSources((prev) => prev.filter((s) => s.id !== sourceId));
        toast.success("Sync source removed");
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Failed to remove sync source");
      }
    },
    [id],
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
    createSyncSource,
    cloneSyncSource,
    triggerSyncSource,
    deleteSyncSource,
  };
}
