import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useConversationShares } from "./use-conversation-shares";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function share(id: string, email = "sam@example.com") {
  return { id, shared_with_email: email, permission: "view" };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(apiClient.post).mockResolvedValue(share("s-1"));
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

/**
 * Who else can read one conversation, and which conversations were shared with me.
 *
 * Two lists, two cache keys, and neither is fetched until somebody asks for a
 * particular conversation or a particular page - a hook that fetched on mount
 * would request `/conversations/null/shares` on every screen that imports it.
 *
 * The mutations write into the cache before refetching, because the dialog is
 * open while they run: a share that only appears after the round trip reads as a
 * click that did nothing.
 */
describe("the shares of one conversation", () => {
  it("fetches nothing until a conversation is named", () => {
    renderHook(() => useConversationShares(), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("reads the shares of the conversation it was asked for", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [share("s-1")], total: 1 });
    const { result } = renderHook(() => useConversationShares(), { wrapper });

    await act(async () => {
      await result.current.fetchShares("c-1");
    });

    await waitFor(() => expect(result.current.shares).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/conversations/c-1/shares");
  });

  it("shows a new share while the refetch behind it is still in flight", async () => {
    // The dialog is open when this runs: a share that only appears once the
    // server answers reads as a click that did nothing.
    const { result } = renderHook(() => useConversationShares(), { wrapper });
    await act(async () => {
      await result.current.fetchShares("c-1");
    });
    vi.mocked(apiClient.post).mockResolvedValue(share("s-new", "new@example.com"));
    // The refetch never answers, so anything on screen is the optimistic write.
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));

    await act(async () => {
      await result.current.shareConversation("c-1", { shared_with_email: "new@example.com" });
    });

    expect(apiClient.post).toHaveBeenCalledWith("/conversations/c-1/shares", {
      shared_with_email: "new@example.com",
    });
    await waitFor(() => expect(result.current.shares[0]?.id).toBe("s-new"));
  });

  it("hands the created share back to the dialog", async () => {
    // The dialog shows the generated link, which only the response carries.
    vi.mocked(apiClient.post).mockResolvedValue(share("s-new"));
    const { result } = renderHook(() => useConversationShares(), { wrapper });

    let created: unknown;
    await act(async () => {
      created = await result.current.shareConversation("c-1", { generate_link: true });
    });

    expect(created).toMatchObject({ id: "s-new" });
  });

  it("says what the server refused, and still raises it", async () => {
    // Both: the dialog reads `error` for the banner, and the caller needs the
    // throw to keep the form open.
    vi.mocked(apiClient.post).mockRejectedValue(new Error("That person is not in this org"));
    const { result } = renderHook(() => useConversationShares(), { wrapper });

    await expect(
      result.current.shareConversation("c-1", { shared_with_email: "outsider@example.com" }),
    ).rejects.toThrow("That person is not in this org");
    await waitFor(() => expect(result.current.error).toBe("That person is not in this org"));
  });

  it("falls back to its own sentence when the refusal carries none", async () => {
    vi.mocked(apiClient.post).mockRejectedValue("boom");
    const { result } = renderHook(() => useConversationShares(), { wrapper });

    await expect(result.current.shareConversation("c-1", {})).rejects.toBeTruthy();
    await waitFor(() => expect(result.current.error).toBe("Failed to share"));
  });

  it("says a refused read was refused, rather than showing an empty dialog", async () => {
    // `invalidateQueries` resolves even when the refetch behind it fails, so the
    // query's own error is the only thing that knows.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Not your conversation"));
    const { result } = renderHook(() => useConversationShares(), { wrapper });

    await act(async () => {
      await result.current.fetchShares("c-1");
    });

    await waitFor(() => expect(result.current.error).toBe("Not your conversation"));
  });

  it("prefers what a refused write said over a stale read failure", async () => {
    // The dialog's banner is one line, and the thing somebody just tried is the
    // more useful of the two.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("read failed"));
    vi.mocked(apiClient.post).mockRejectedValue(new Error("That person is not in this org"));
    const { result } = renderHook(() => useConversationShares(), { wrapper });
    await act(async () => {
      await result.current.fetchShares("c-1");
    });
    await waitFor(() => expect(result.current.error).toBe("read failed"));

    await expect(result.current.shareConversation("c-1", {})).rejects.toBeTruthy();

    await waitFor(() => expect(result.current.error).toBe("That person is not in this org"));
  });

  it("drops a revoked share from the list at once", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [share("s-1"), share("s-2", "other@example.com")],
      total: 2,
    });
    const { result } = renderHook(() => useConversationShares(), { wrapper });
    await act(async () => {
      await result.current.fetchShares("c-1");
    });
    await waitFor(() => expect(result.current.shares).toHaveLength(2));

    // The refetch never answers, so the list on screen is the optimistic write.
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
    await act(async () => {
      await result.current.revokeShare("c-1", "s-2");
    });

    expect(apiClient.delete).toHaveBeenCalledWith("/conversations/c-1/shares/s-2");
    await waitFor(() => expect(result.current.shares.map((row) => row.id)).toEqual(["s-1"]));
  });

  it("says what the server refused on a revoke, and raises it too", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("Not yours to revoke"));
    const { result } = renderHook(() => useConversationShares(), { wrapper });

    await expect(result.current.revokeShare("c-1", "s-1")).rejects.toThrow("Not yours to revoke");
    await waitFor(() => expect(result.current.error).toBe("Not yours to revoke"));
  });

  it("falls back to its own sentence on a revoke with no reason", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue("boom");
    const { result } = renderHook(() => useConversationShares(), { wrapper });

    await expect(result.current.revokeShare("c-1", "s-1")).rejects.toBeTruthy();
    await waitFor(() => expect(result.current.error).toBe("Failed to revoke"));
  });
});

describe("the conversations shared with me", () => {
  it("fetches nothing until a page is asked for", () => {
    renderHook(() => useConversationShares(), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("reads the window it was asked for, and its total", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "c-1" }], total: 40 });
    const { result } = renderHook(() => useConversationShares(), { wrapper });

    await act(async () => {
      await result.current.fetchSharedWithMe(20, 10);
    });

    await waitFor(() => expect(result.current.sharedWithMe).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/conversations/shared-with-me?skip=20&limit=10");
    expect(result.current.sharedWithMeTotal).toBe(40);
  });

  it("opens on the first page when no window is given", async () => {
    const { result } = renderHook(() => useConversationShares(), { wrapper });

    await act(async () => {
      await result.current.fetchSharedWithMe();
    });

    expect(apiClient.get).toHaveBeenCalledWith("/conversations/shared-with-me?skip=0&limit=50");
  });

  it("says a refused shared-with-me read was refused", async () => {
    vi.mocked(apiClient.get).mockRejectedValue("boom");
    const { result } = renderHook(() => useConversationShares(), { wrapper });

    await act(async () => {
      await result.current.fetchSharedWithMe();
    });

    await waitFor(() => expect(result.current.error).toBe("Failed to load shares"));
  });

  it("says nothing was shared rather than leaving the count undefined", async () => {
    const { result } = renderHook(() => useConversationShares(), { wrapper });

    await act(async () => {
      await result.current.fetchSharedWithMe();
    });

    expect(result.current.sharedWithMe).toEqual([]);
    expect(result.current.sharedWithMeTotal).toBe(0);
  });
});
