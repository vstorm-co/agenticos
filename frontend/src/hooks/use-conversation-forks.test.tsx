import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import type { ConversationForkList } from "@/lib/conversation-forks-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useConversationForks } from "./use-conversation-forks";

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
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
});

describe("useConversationForks", () => {
  it("waits for the active tenant, reader and source before fetching", () => {
    const { result, rerender } = renderHook(
      ({ source, message }) => useConversationForks(source, message),
      {
        initialProps: { source: null as string | null, message: "answer-a" as string | null },
        wrapper,
      },
    );
    expect(apiClient.get).not.toHaveBeenCalled();

    scope.tenant = null;
    act(() => {
      useAuthStore.setState({ user: null });
      rerender({ source: "source-a", message: "answer-a" });
    });
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(result.current.data).toBeUndefined();
  });

  it("keys the bounded list by source, tenant and reader", async () => {
    const page = { items: [], total: 0 };
    vi.mocked(apiClient.get).mockResolvedValueOnce(page);
    const { result } = renderHook(() => useConversationForks("source-a", "answer-a"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(apiClient.get).toHaveBeenCalledExactlyOnceWith("/conversations/source-a/forks", {
      params: { message_id: "answer-a", skip: "0", limit: "100" },
    });
    expect(
      client.getQueryData(
        qk.conversations.forks("source-a", "answer-a", "org-1", "person-1", 0, 100),
      ),
    ).toEqual({ pages: [page], pageParams: [0] });
  });

  it("loads another bounded page only within the same source answer scope", async () => {
    const firstPage: ConversationForkList = {
      items: [
        {
          id: "fork-a",
          title: "First",
          created_at: "2026-11-17T10:00:00Z",
          updated_at: null,
          is_archived: false,
          forked_from: { conversation_id: "source-a", message_id: "answer-a", title: "Main" },
        },
      ],
      total: 2,
    };
    const secondPage: ConversationForkList = {
      items: [{ ...firstPage.items[0]!, id: "fork-b", title: "Second" }],
      total: 2,
    };
    vi.mocked(apiClient.get).mockResolvedValueOnce(firstPage).mockResolvedValueOnce(secondPage);
    const { result } = renderHook(() => useConversationForks("source-a", "answer-a"), { wrapper });

    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    await act(async () => {
      await result.current.fetchNextPage();
    });

    expect(apiClient.get).toHaveBeenNthCalledWith(2, "/conversations/source-a/forks", {
      params: { message_id: "answer-a", skip: "1", limit: "100" },
    });
    await waitFor(() =>
      expect(result.current.data?.pages.map((page) => page.items[0]?.id)).toEqual([
        "fork-a",
        "fork-b",
      ]),
    );
  });

  it("stops pagination when the server returns no progress or the total is reached", async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ items: [{ id: "fork-a" }], total: 2 })
      .mockResolvedValueOnce({ items: [], total: 2 });
    const { result } = renderHook(() => useConversationForks("source-a", "answer-a"), { wrapper });

    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    await act(async () => {
      await result.current.fetchNextPage();
    });
    await waitFor(() => expect(result.current.hasNextPage).toBe(false));
  });

  it("stops pagination when the loaded page reaches the server total", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ items: [{ id: "fork-a" }], total: 1 });
    const finished = renderHook(() => useConversationForks("source-b", "answer-b"), { wrapper });
    await waitFor(() => expect(finished.result.current.isSuccess).toBe(true));
    expect(finished.result.current.hasNextPage).toBe(false);
  });

  it("keeps an old source response out of the newly selected scope", async () => {
    let resolveOld!: (page: ConversationForkList) => void;
    const oldPage = new Promise<ConversationForkList>((resolve) => {
      resolveOld = resolve;
    });
    vi.mocked(apiClient.get)
      .mockReturnValueOnce(oldPage)
      .mockResolvedValueOnce({
        items: [{ id: "fork-b" }] as ConversationForkList["items"],
        total: 1,
      });

    const { result, rerender } = renderHook(
      ({ source }) => useConversationForks(source, "answer-a"),
      {
        initialProps: { source: "source-a" },
        wrapper,
      },
    );
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));
    rerender({ source: "source-b" });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.data?.pages[0]?.items[0]?.id).toBe("fork-b"));

    await act(async () => {
      resolveOld({ items: [{ id: "fork-a" }] as ConversationForkList["items"], total: 1 });
      await oldPage;
    });

    expect(result.current.data?.pages[0]?.items[0]?.id).toBe("fork-b");
    expect(
      client.getQueryData(
        qk.conversations.forks("source-a", "answer-a", "org-1", "person-1", 0, 100),
      ),
    ).toEqual({
      pages: [{ items: [{ id: "fork-a" }], total: 1 }],
      pageParams: [0],
    });
  });
});
