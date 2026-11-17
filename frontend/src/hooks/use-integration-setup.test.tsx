import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { useIntegrationSetup } from "./use-integration-setup";
import { useWatchConnections } from "./use-watches";
import { apiClient } from "@/lib/api-client";
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));
function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => vi.clearAllMocks());
it("keeps provider and write scope previews separate in the cache", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ products: [] });
  const { result } = renderHook(
    () => ({
      read: useIntegrationSetup("google"),
      write: useIntegrationSetup("google", true),
      slack: useIntegrationSetup("slack"),
    }),
    { wrapper },
  );
  await waitFor(() => expect(result.current.slack.isSuccess).toBe(true));
  expect(apiClient.get).toHaveBeenCalledWith("/me/connected-accounts/setup/google?write=false");
  expect(apiClient.get).toHaveBeenCalledWith("/me/connected-accounts/setup/google?write=true");
  expect(apiClient.get).toHaveBeenCalledWith("/me/connected-accounts/setup/slack?write=false");
});
it("reads the authorized personal watch source choices", async () => {
  const connections = [{ id: "work", name: "Work", label: "Work", catalog_key: "google" }];
  vi.mocked(apiClient.get).mockResolvedValue(connections);
  const { result } = renderHook(() => useWatchConnections(), { wrapper });
  expect(result.current.connections).toEqual([]);
  await waitFor(() => expect(result.current.connections).toEqual(connections));
  expect(apiClient.get).toHaveBeenCalledWith("/me/watches/connections");
});
it("exposes a refused watch source list as an error", async () => {
  const error = new Error("Membership revoked");
  vi.mocked(apiClient.get).mockRejectedValue(error);
  const { result } = renderHook(() => useWatchConnections(), { wrapper });
  await waitFor(() => expect(result.current.error).toBe(error));
  expect(result.current.connections).toEqual([]);
});
