/**
 * API client for the services an organization runs on the deployment's own
 * network and lets its collections use: an Ollama that embeds, an OCR sidecar
 * LiteParse sends pages to.
 *
 * The same shape as the sandbox connections and the model profiles, for the same
 * reason: a collection names one by id, so moving a server is one edit here
 * rather than a change on every collection pointed at it. Nothing in this file
 * carries a credential - these are addresses of hosts the deployment runs, and a
 * keyless endpoint is the whole point of registering one.
 */

import { apiClient } from "./api-client";

/** What a local service does for a collection. */
export type LocalServiceKind = "embedding" | "ocr";

/**
 * The catalog id each kind answers to - the embedding provider whose models an
 * `embedding` server serves, and the parser an `ocr` server serves. Derived from
 * the kind rather than asked, because there is one of each today.
 */
export const LOCAL_SERVICE_PROVIDERS: Readonly<Record<LocalServiceKind, string>> = {
  embedding: "ollama",
  ocr: "liteparse",
};

export interface LocalServiceRecord {
  id: string;
  /** Null for a deployment-wide row: made by the app admin, offered to every organization. */
  organization_id: string | null;
  kind: LocalServiceKind;
  provider: string;
  name: string;
  /** The http(s) root the service answers on. */
  base_url: string;
  is_active: boolean;
  created_at: string;
  updated_at: string | null;
}

interface LocalServiceList {
  items: LocalServiceRecord[];
  total: number;
}

export interface LocalServiceInput {
  name: string;
  kind: LocalServiceKind;
  provider: string;
  base_url: string;
  /** Register for the whole deployment. Refused for anyone but the app admin. */
  deployment_wide?: boolean;
}

export interface LocalServicePatch {
  name?: string;
  base_url?: string;
  is_active?: boolean;
}

const ROOT = "/local-services";

export async function listLocalServices(): Promise<LocalServiceRecord[]> {
  const data = await apiClient.get<LocalServiceList>(ROOT);
  return data.items;
}

export async function createLocalService(input: LocalServiceInput): Promise<LocalServiceRecord> {
  return apiClient.post<LocalServiceRecord>(ROOT, input);
}

export async function updateLocalService(
  id: string,
  patch: LocalServicePatch,
): Promise<LocalServiceRecord> {
  return apiClient.patch<LocalServiceRecord>(`${ROOT}/${id}`, patch);
}

export async function deleteLocalService(id: string): Promise<void> {
  await apiClient.delete(`${ROOT}/${id}`);
}
