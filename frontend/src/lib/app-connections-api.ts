import { apiClient } from "./api-client";
import type {
  AppConnection,
  AppConnectionAuthorization,
  AppConnectionCallback,
  AppConnectionCatalog,
} from "@/types/app-connections";

const ROOT = "/me/app-connections";

export function getAppConnectionCatalog(
  signal?: AbortSignal,
  search = "",
  cursor: string | null = null,
) {
  return apiClient.get<AppConnectionCatalog>(`${ROOT}/catalog`, {
    signal,
    params: { limit: "24", ...(search ? { search } : {}), ...(cursor ? { cursor } : {}) },
  });
}

export async function listAppConnections(signal?: AbortSignal): Promise<AppConnection[]> {
  const result = await apiClient.get<{ items: AppConnection[]; total: number }>(ROOT, { signal });
  return result.items;
}

export function connectApp(input: { toolkit: string; label?: string }) {
  return apiClient.post<AppConnectionAuthorization>(`${ROOT}/connect`, input);
}

export function reconnectApp(id: string) {
  return apiClient.post<AppConnectionAuthorization>(
    `${ROOT}/${encodeURIComponent(id)}/reconnect`,
    {},
  );
}

export function refreshAppConnection(id: string) {
  return apiClient.post<AppConnection>(`${ROOT}/${encodeURIComponent(id)}/refresh`, {});
}

export function completeAppConnection(input: AppConnectionCallback) {
  return apiClient.post<AppConnection>(`${ROOT}/callback`, input);
}

export function disconnectApp(id: string) {
  return apiClient.delete<void>(`${ROOT}/${encodeURIComponent(id)}`);
}
