/**
 * RAG (Retrieval Augmented Generation) API client.
 *
 * Search plus the per-document endpoints of a knowledge base. Everything else
 * about a knowledge base - the list, its documents, sync sources, connectors -
 * goes through `useKnowledgeBases` / `useKBDetail` and the `/kb` routes; the
 * types those payloads share live here.
 */

import { apiClient } from "./api-client";
import { saveBlob, type FileAccess } from "./file-access";
import { qk } from "./query-keys";
import type { KBParsedContent } from "@/types";

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

export async function searchDocuments(request: RAGSearchRequest): Promise<RAGSearchResponse> {
  return apiClient.post<RAGSearchResponse>("/rag/search", request);
}

/**
 * One stored document, as the shared viewer reads it.
 *
 * `raw` rather than `fetch`: this is an org-scoped endpoint, and without the
 * organization header the backend answers from the caller's personal one.
 *
 * One route answers both bodies here, unlike a workspace file - so which of the two
 * a document gets is decided from its name and its stored `filetype` before the
 * request, and the response's own content type is what a byte-rendered document is
 * then displayed as.
 */
export function kbDocumentAccess(kbId: string, doc: { id: string; filename: string }): FileAccess {
  const read = () => apiClient.raw(`/kb/${kbId}/documents/${doc.id}/download`);

  return {
    textKey: qk.kb.documentText(kbId, doc.id),
    bytesKey: qk.kb.documentBytes(kbId, doc.id),
    readText: async () => ({ content: await (await read()).text(), truncated: false }),
    readBytes: async () => (await read()).blob(),
    download: async () => saveBlob(await (await read()).blob(), doc.filename),
  };
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

export interface SyncSourceCreate {
  name: string;
  connector_type: string;
  /** Omit to create an org-level integration not yet assigned to a KB. */
  collection_name?: string | null;
  config: Record<string, unknown>;
  sync_mode?: string;
  schedule_minutes?: number | null;
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

/**
 * Every sync source the caller can reach, or only one collection's.
 *
 * The knowledge pages read a collection's sources through `useKBDetail`; this
 * is the unscoped call, and the dashboard is what makes it, to count what is
 * connected across all of them.
 */
export async function listSyncSources(collectionName?: string): Promise<SyncSourceList> {
  const params = collectionName ? `?collection_name=${encodeURIComponent(collectionName)}` : "";
  return apiClient.get<SyncSourceList>(`/rag/sync/sources${params}`);
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
