/**
 * API client for the endpoints an organization registers once and lets its
 * collections use: an Ollama that embeds, an OpenAI-compatible gateway that
 * embeds (with a Vault key when it wants one), an OCR sidecar LiteParse sends
 * pages to.
 *
 * The same shape as the sandbox connections and the model profiles, for the same
 * reason: a collection names one by id, so moving a server is one edit here
 * rather than a change on every collection pointed at it. A key is never in this
 * file's payloads - a connection carries only the id of a Vault secret.
 */

import { apiClient } from "./api-client";
import type { EmbeddingProbeEstimate, EmbeddingProbeResult } from "./embedding-probe-api";

/** What a service connection does for a collection. */
export type ServiceConnectionKind = "embedding" | "ocr" | "document_parser";

/** The wire protocol a connection speaks. */
export type ServiceConnectionStyle = "ollama" | "openai_compatible" | "liteparse" | "docling";

/** The styles each kind may choose from. The first is the default. */
export const SERVICE_CONNECTION_STYLES: Readonly<
  Record<ServiceConnectionKind, readonly ServiceConnectionStyle[]>
> = {
  embedding: ["ollama", "openai_compatible"],
  ocr: ["liteparse"],
  document_parser: ["docling"],
};

/** The styles that may carry a Vault key. */
export const KEYED_STYLES: ReadonlySet<ServiceConnectionStyle> = new Set([
  "openai_compatible",
  "docling",
]);

/** A style that may carry a Vault key. */
export type KeyedStyle = "openai_compatible" | "docling";

/** Whether a style may carry a Vault key, as a type guard for the purpose lookup. */
export function isKeyedStyle(style: ServiceConnectionStyle): style is KeyedStyle {
  return KEYED_STYLES.has(style);
}

/** The Vault purpose a key must have to be used by each keyed style. */
export const KEY_PURPOSE_BY_STYLE: Readonly<Record<KeyedStyle, string>> = {
  openai_compatible: "openai_compatible",
  docling: "docling",
};

export interface ServiceConnectionRecord {
  id: string;
  /** Null for a deployment-wide row: made by the app admin, offered to every organization. */
  organization_id: string | null;
  kind: ServiceConnectionKind;
  provider: ServiceConnectionStyle;
  name: string;
  /** The http(s) root the service answers on. */
  base_url: string;
  is_active: boolean;
  /** The Vault key the connection sends, or null for a keyless one. */
  secret_id: string | null;
  requires_key: boolean;
  created_at: string;
  updated_at: string | null;
}

interface ServiceConnectionList {
  items: ServiceConnectionRecord[];
  total: number;
}

export interface ServiceConnectionInput {
  name: string;
  kind: ServiceConnectionKind;
  provider: ServiceConnectionStyle;
  base_url: string;
  /** Register for the whole deployment. Refused for anyone but the app admin. */
  deployment_wide?: boolean;
  secret_id?: string;
}

export interface ServiceConnectionPatch {
  name?: string;
  base_url?: string;
  is_active?: boolean;
  secret_id?: string;
  /** From a passing test of exactly these values. */
  probe_token?: string;
  /** Save without a test; the server audits it. */
  unverified?: boolean;
}

/** What to try without saving: the values exactly as the form holds them. */
export interface ServiceConnectionTestInput {
  kind: ServiceConnectionKind;
  provider: ServiceConnectionStyle;
  base_url: string;
  /** A Vault key chosen in the form. */
  secret_id?: string;
  /** The stored connection being edited, so its kept key is the one sent. */
  service_id?: string;
}

/** What the server found. A test never changes anything and never blocks a save. */
export interface ServiceConnectionTestResult {
  outcome: "ok" | "key_refused" | "key_required" | "unreachable" | "not_docling";
  /** The Docling Serve version, when it answered. */
  version: string | null;
}

const ROOT = "/service-connections";

export async function listServiceConnections(): Promise<ServiceConnectionRecord[]> {
  const data = await apiClient.get<ServiceConnectionList>(ROOT);
  return data.items;
}

export async function createServiceConnection(
  input: ServiceConnectionInput,
): Promise<ServiceConnectionRecord> {
  return apiClient.post<ServiceConnectionRecord>(ROOT, input);
}

export async function updateServiceConnection(
  id: string,
  patch: ServiceConnectionPatch,
): Promise<ServiceConnectionRecord> {
  return apiClient.patch<ServiceConnectionRecord>(`${ROOT}/${id}`, patch);
}

export async function deleteServiceConnection(id: string): Promise<void> {
  await apiClient.delete(`${ROOT}/${id}`);
}

/** What testing a changed address or key would cost, before it is run. */
export async function estimateConnectionProbe(id: string): Promise<EmbeddingProbeEstimate> {
  return apiClient.get<EmbeddingProbeEstimate>(`${ROOT}/${id}/probe/estimate`);
}

/** Re-embed stored chunks of every collection on the connection with the values tried. */
export async function probeConnection(
  id: string,
  body: { base_url?: string; secret_id?: string },
): Promise<EmbeddingProbeResult> {
  return apiClient.post<EmbeddingProbeResult>(`${ROOT}/${id}/probe`, body);
}

/** Try an address and key for a document parser, spending no conversion. */
export async function testServiceConnection(
  input: ServiceConnectionTestInput,
): Promise<ServiceConnectionTestResult> {
  return apiClient.post<ServiceConnectionTestResult>(`${ROOT}/test`, input);
}
