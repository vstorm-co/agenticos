import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useConversationMessageSearch } from "./use-conversation-message-search";

const scope = vi.hoisted(() => ({ tenant: "org-1" as string | null }));
vi.mock("@/hooks/use-organizations", () => ({ useTenantId: () => scope.tenant }));
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

const user = {
  id: "person-1",
  email: "person@example.test",
  is_active: true,
  created_at: "2026-11-16T10:00:00Z",
};
let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.resetAllMocks();
  scope.tenant = "org-1";
  useAuthStore.setState({ user });
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(apiClient.get).mockResolvedValue([]);
});

describe("useConversationMessageSearch", () => {
  it("waits until reader, tenant and nonblank query are present", () => {
    const { result, rerender } = renderHook(({ query }) => useConversationMessageSearch(query), {
      initialProps: { query: "  " },
      wrapper,
    });

    expect(apiClient.get).not.toHaveBeenCalled();
    expect(result.current.data).toBeUndefined();

    scope.tenant = null;
    act(() => {
      useAuthStore.setState({ user: null });
      rerender({ query: "pricing" });
    });
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("fetches and caches by tenant, reader and trimmed query", async () => {
    const hits = [{ conversation_id: "c-1", message_id: "m-1" }];
    vi.mocked(apiClient.get).mockResolvedValueOnce(hits);
    const { result } = renderHook(() => useConversationMessageSearch(" pricing "), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(apiClient.get).toHaveBeenCalledWith("/conversations/search/messages", {
      params: { query: "pricing" },
    });
    expect(
      client.getQueryData(qk.conversations.messageSearch("org-1", "person-1", "pricing")),
    ).toEqual(hits);
  });
});
