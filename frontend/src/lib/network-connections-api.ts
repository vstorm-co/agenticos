import { apiClient } from "@/lib/api-client";
import type {
  NetworkConnection,
  NetworkConnectionList,
  NetworkConnectionScope,
  NetworkEnrollment,
  NetworkPeerList,
} from "@/types/network-connections";

const ROOT = "/network-connections";

export async function listNetworkConnections(
  skip: number,
  limit: number,
  signal?: AbortSignal,
): Promise<NetworkConnectionList> {
  return apiClient.get<NetworkConnectionList>(ROOT, {
    params: { skip: String(skip), limit: String(limit) },
    signal,
  });
}

export async function getNetworkConnection(
  id: string,
  signal?: AbortSignal,
): Promise<NetworkConnection> {
  return apiClient.get<NetworkConnection>(`${ROOT}/${encodeURIComponent(id)}`, { signal });
}

export async function createNetworkConnection(input: {
  name: string;
  scope: NetworkConnectionScope;
}): Promise<NetworkConnection> {
  return apiClient.post<NetworkConnection>(ROOT, input);
}

/** Explicitly starts the enrollment process for one connection. */
export async function connectNetworkConnection(id: string): Promise<NetworkConnection> {
  return apiClient.post<NetworkConnection>(`${ROOT}/${encodeURIComponent(id)}/connect`);
}

/** Fetch only after Connect; callers must keep the URL in transient local state. */
export async function getNetworkEnrollment(
  id: string,
  signal?: AbortSignal,
): Promise<NetworkEnrollment> {
  return apiClient.get<NetworkEnrollment>(`${ROOT}/${encodeURIComponent(id)}/enrollment`, {
    signal,
  });
}

export async function listNetworkPeers(id: string, signal?: AbortSignal): Promise<NetworkPeerList> {
  return apiClient.get<NetworkPeerList>(`${ROOT}/${encodeURIComponent(id)}/peers`, { signal });
}

/** Queues a bounded status refresh; it does not start a connector runtime. */
export async function refreshNetworkConnection(id: string): Promise<NetworkConnection> {
  return apiClient.post<NetworkConnection>(`${ROOT}/${encodeURIComponent(id)}/refresh`);
}

export async function pauseNetworkConnection(id: string): Promise<NetworkConnection> {
  return apiClient.post<NetworkConnection>(`${ROOT}/${encodeURIComponent(id)}/pause`);
}

export async function revokeNetworkConnection(id: string): Promise<NetworkConnection> {
  return apiClient.post<NetworkConnection>(`${ROOT}/${encodeURIComponent(id)}/revoke`);
}
