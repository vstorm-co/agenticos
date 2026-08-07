/**
 * RAG (Retrieval Augmented Generation) API client.
 */

import { apiClient } from "./api-client";
import type { KBParsedContent } from "@/types";

export interface RAGCollectionList {
  items: string[];
}

export interface RAGCollectionInfo {
  name: string;
  total_vectors: number;
  dim: number;
  indexing_status: string;
}

export interface RAGSearchRequest {
  query: string;
  collection_name?: string;
  collection_names?: string[];
  limit?: number;
  min_score?: number;
  filter?: string;
}

export interface RAGSearchResult {
  content: string;
  metadata: Record<string, unknown>;
  score: number;
  parent_doc_id: string;
}

export interface RAGSearchResponse {
  results: RAGSearchResult[];
}

export const isRagEnabled = (): boolean => {
  return process.env.NEXT_PUBLIC_RAG_ENABLED === "true";
};

export async function listCollections(): Promise<RAGCollectionList> {
  return apiClient.get<RAGCollectionList>("/rag/collections");
}

export async function getCollectionInfo(collectionName: string): Promise<RAGCollectionInfo> {
  return apiClient.get<RAGCollectionInfo>(`/rag/collections/${collectionName}/info`);
}

/**
 * The longest collection name the server will accept.
 *
 * `MAX_COLLECTION_NAME_LENGTH` in `app/db/vector_tables.py`, derived there from
 * what Postgres keeps of an identifier once the store's `rag_` prefix and
 * `_embedding_idx` suffix are on it: 63 - 4 - 14. Postgres truncates rather
 * than refusing, so two names agreeing to that point are one table and one
 * index.
 *
 * Here only as a `maxLength` on the input, which is why this is the single rule
 * of the four that is mirrored: the server is the authority and answers with
 * its own sentence for every one of them, but a limit a person can type past
 * without noticing is worth stopping at the keyboard.
 */
export const MAX_COLLECTION_NAME_LENGTH = 45;

export async function createCollection(collectionName: string): Promise<{ message: string }> {
  return apiClient.post<{ message: string }>(`/rag/collections/${collectionName}`);
}

export async function deleteCollection(collectionName: string): Promise<void> {
  return apiClient.delete(`/rag/collections/${collectionName}`);
}

export async function deleteDocument(collectionName: string, documentId: string): Promise<void> {
  return apiClient.delete(`/rag/collections/${collectionName}/documents/${documentId}`);
}

export async function searchDocuments(request: RAGSearchRequest): Promise<RAGSearchResponse> {
  return apiClient.post<RAGSearchResponse>("/rag/search", request);
}

export interface RAGDocumentItem {
  document_id: string;
  filename: string;
  filesize: number;
  filetype: string;
  chunk_count: number;
  additional_info?: Record<string, unknown>;
}

export interface RAGDocumentList {
  items: RAGDocumentItem[];
  total: number;
}

export interface RAGIngestResult {
  id: string;
  status: string;
  document_id: string | null;
  filename: string;
  collection: string;
  message: string;
}

export interface RAGTrackedDocument {
  id: string;
  collection_name: string;
  filename: string;
  filesize: number;
  filetype: string;
  /** Read through `ragStatus` in `./rag-status`, which is what knows the tokens. */
  status: string;
  error_message: string | null;
  vector_document_id: string | null;
  chunk_count: number;
  has_file: boolean;
  created_at: string | null;
  completed_at: string | null;
}

/**
 * Open a tracked document's original file in a new tab.
 *
 * Not an `<a href>`, which is what this replaced. A browser navigation sends
 * whatever headers the browser feels like and none that we set, so an anchor to
 * an org-scoped endpoint arrives with no `X-Organization-Id` - the backend then
 * answers from the caller's personal organization and a document belonging to
 * the organization on screen comes back 404. Fetching it and opening the blob
 * is the same trick `downloadKBDocument` uses, for the same reason.
 */
export async function openTrackedDocument(docId: string): Promise<void> {
  const response = await apiClient.raw(`/rag/documents/${docId}/download`);
  const url = URL.createObjectURL(await response.blob());
  window.open(url, "_blank", "noopener,noreferrer");
  // Long enough for the new tab to have read it. Revoking at once closes the
  // tab that was just opened; never revoking leaks it for the life of the page.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export async function downloadKBDocument(
  kbId: string,
  doc: { id: string; filename: string },
  mode: "download" | "view" = "download",
): Promise<void> {
  // `raw` rather than `fetch`: this is an org-scoped endpoint, and without the
  // organization header the backend answers from the caller's personal one.
  const res = await apiClient.raw(`/kb/${kbId}/documents/${doc.id}/download`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  if (mode === "view") {
    window.open(url, "_blank", "noopener,noreferrer");
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } else {
    const a = document.createElement("a");
    a.href = url;
    a.download = doc.filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
}

/**
 * How a KB document parsed: the indexed chunks, grouped back into pages.
 *
 * The counterpart of the download URL above - original bytes there, what the
 * parser made of them here. 404 for a document still processing or failed.
 */
export async function getParsedKBDocument(kbId: string, docId: string): Promise<KBParsedContent> {
  return apiClient.get<KBParsedContent>(`/kb/${kbId}/documents/${docId}/parsed`);
}

export interface RAGTrackedDocumentList {
  items: RAGTrackedDocument[];
  total: number;
}

export async function listTrackedDocuments(
  collectionName?: string,
): Promise<RAGTrackedDocumentList> {
  const params = collectionName ? `?collection_name=${encodeURIComponent(collectionName)}` : "";
  return apiClient.get<RAGTrackedDocumentList>(`/rag/documents${params}`);
}

export async function deleteTrackedDocument(docId: string): Promise<void> {
  return apiClient.delete(`/rag/documents/${docId}`);
}

export async function listDocuments(collectionName: string): Promise<RAGDocumentList> {
  return apiClient.get<RAGDocumentList>(`/rag/collections/${collectionName}/documents`);
}

/**
 * Ingest one file into a collection.
 *
 * Through `apiClient.upload`, not a bare `fetch`. This endpoint is org-scoped,
 * and a request without `X-Organization-Id` is not tenant-less: the backend
 * falls back to the caller's personal organization. Uploading into a collection
 * whose name exists in both wrote the file to the wrong tenant and reported
 * success under the right one.
 */
export function ingestFile(
  collectionName: string,
  file: File,
  replace = false,
): Promise<RAGIngestResult> {
  return apiClient.upload<RAGIngestResult>(
    `/rag/collections/${collectionName}/ingest`,
    file,
    replace ? { params: { replace: "true" } } : undefined,
  );
}

export interface SyncSourceCreate {
  name: string;
  connector_type: string;
  /** Omit to create an org-level integration not yet assigned to a KB. */
  collection_name?: string | null;
  config: Record<string, unknown>;
  sync_mode?: string;
  schedule_minutes?: number | null;
}

export interface SyncSourceClone {
  collection_name: string;
  name?: string;
}

export interface SyncSourceRead {
  id: string;
  organization_id: string | null;
  name: string;
  connector_type: string;
  /** null = org-level integration, not yet assigned to a KB */
  collection_name: string | null;
  config: Record<string, unknown>;
  sync_mode: string;
  schedule_minutes: number | null;
  is_active: boolean;
  last_sync_at: string | null;
  last_sync_status: string | null;
  last_error: string | null;
  created_at: string | null;
}

export interface SyncSourceList {
  items: SyncSourceRead[];
  total: number;
}

export interface ConnectorConfigField {
  type: string;
  required: boolean;
  label: string;
  help?: string;
  default?: unknown;
  secret?: boolean;
}

export interface ConnectorInfo {
  type: string;
  name: string;
  config_schema: Record<string, ConnectorConfigField>;
  enabled: boolean;
}

export interface ConnectorList {
  items: ConnectorInfo[];
}

export interface RAGSyncLog {
  id: string;
  source: string;
  collection_name: string;
  status: string;
  mode: string;
  total_files: number;
  ingested: number;
  updated: number;
  skipped: number;
  failed: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface RAGSyncLogList {
  items: RAGSyncLog[];
  total: number;
}

export async function listSyncLogs(collectionName?: string, limit = 20): Promise<RAGSyncLogList> {
  const params = new URLSearchParams();
  if (collectionName) params.set("collection_name", collectionName);
  params.set("limit", String(limit));
  return apiClient.get<RAGSyncLogList>(`/rag/sync/logs?${params}`);
}

/** Fetch logs for a specific sync source under a KB. */
export async function listKBSyncSourceLogs(
  kbId: string,
  sourceId: string,
  limit = 20,
): Promise<RAGSyncLogList> {
  return apiClient.get<RAGSyncLogList>(`/kb/${kbId}/sync-sources/${sourceId}/logs?limit=${limit}`);
}

export async function triggerSync(
  collectionName: string,
  mode: string,
  path: string,
): Promise<{ id: string; status: string; message: string }> {
  return apiClient.post("/rag/sync/local", { collection_name: collectionName, mode, path });
}

export async function cancelSync(syncId: string): Promise<{ message: string }> {
  return apiClient.delete(`/rag/sync/${syncId}`);
}

export async function listSyncSources(collectionName?: string): Promise<SyncSourceList> {
  const params = collectionName ? `?collection_name=${encodeURIComponent(collectionName)}` : "";
  return apiClient.get<SyncSourceList>(`/rag/sync/sources${params}`);
}

export async function createSyncSource(data: SyncSourceCreate): Promise<SyncSourceRead> {
  return apiClient.post<SyncSourceRead>("/rag/sync/sources", data);
}

export async function cloneSyncSource(
  sourceId: string,
  data: SyncSourceClone,
): Promise<SyncSourceRead> {
  return apiClient.post<SyncSourceRead>(`/rag/sync/sources/${sourceId}/clone`, data);
}

export async function updateSyncSource(
  sourceId: string,
  data: Partial<SyncSourceCreate>,
): Promise<SyncSourceRead> {
  return apiClient.patch<SyncSourceRead>(`/rag/sync/sources/${sourceId}`, data);
}

export async function deleteSyncSource(sourceId: string): Promise<void> {
  return apiClient.delete(`/rag/sync/sources/${sourceId}`);
}

export async function triggerSyncSource(
  sourceId: string,
): Promise<{ id: string; status: string; message: string }> {
  return apiClient.post(`/rag/sync/sources/${sourceId}/trigger`);
}

export async function listConnectors(): Promise<ConnectorList> {
  return apiClient.get<ConnectorList>("/rag/sync/connectors");
}
