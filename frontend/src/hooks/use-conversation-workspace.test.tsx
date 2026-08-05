import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useConversationWorkspace } from "./use-conversation-workspace";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({
    scope: "conversation",
    backend: "state",
    owner_label: "This conversation",
    items: [{ path: "/report.csv", size: 42, is_dir: false }],
    total: 1,
    bytes_total: 42,
  });
});

/**
 * The client half of the conversation's workspace listing.
 *
 * The property worth holding is that it asks for nothing before there is something to
 * ask about: a new chat has no conversation id. Reading one of these *files* is
 * `use-workspace-file.test.tsx`, which covers both addresses a file can have.
 */
describe("the files one conversation is keeping", () => {
  it("does not ask before a conversation exists", () => {
    const { result } = renderHook(() => useConversationWorkspace(null), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
  });

  it("reads the workspace of the conversation on screen", async () => {
    const { result } = renderHook(() => useConversationWorkspace("c1"), { wrapper });

    await waitFor(() => expect(result.current.workspace).not.toBeNull());
    expect(apiClient.get).toHaveBeenCalledWith("/conversations/c1/workspace");
    expect(result.current.workspace?.items).toHaveLength(1);
  });

  it("re-reads on demand, because a turn is what changes the files", async () => {
    const { result } = renderHook(() => useConversationWorkspace("c1"), { wrapper });
    await waitFor(() => expect(result.current.workspace).not.toBeNull());

    await act(async () => {
      await result.current.refresh();
    });

    expect(vi.mocked(apiClient.get).mock.calls).toHaveLength(2);
  });

  it("refreshing a conversation that does not exist asks for nothing", async () => {
    const { result } = renderHook(() => useConversationWorkspace(null), { wrapper });

    await act(async () => {
      await result.current.refresh();
    });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("reports a refusal rather than an empty workspace", async () => {
    // An agent that keeps no files and a request that answered 403 are the same
    // pixels otherwise, and only one of them is worth telling somebody about.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Not permitted"));

    const { result } = renderHook(() => useConversationWorkspace("c1"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("Not permitted"));
    expect(result.current.workspace).toBeNull();
  });
});
