import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useClearAgentMemory, useForgetPersonMemory } from "./use-memory";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.delete).mockResolvedValue({ notes_deleted: 0, mem0_agents_cleared: 0 });
});

describe("useForgetPersonMemory", () => {
  it("erases one person across every agent, by id", async () => {
    const { result } = renderHook(() => useForgetPersonMemory(), { wrapper });

    result.current.mutate("u-1");

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/memory/person/u-1"));
  });

  it("reports what was actually removed rather than a bare success", async () => {
    // Half of "forgotten" happens in mem0, so a toast that said "done" without a
    // count would be a claim the caller cannot check.
    vi.mocked(apiClient.delete).mockResolvedValue({ notes_deleted: 4, mem0_agents_cleared: 1 });
    const { result } = renderHook(() => useForgetPersonMemory(), { wrapper });

    result.current.mutate("u-1");

    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(String(toastSuccess.mock.calls[0]?.[0])).toContain("4");
  });

  it("shows the server's refusal rather than swallowing it", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("nope"));
    const { result } = renderHook(() => useForgetPersonMemory(), { wrapper });

    result.current.mutate("u-1");

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});

describe("useClearAgentMemory", () => {
  it("names the agent in the query string rather than the path", async () => {
    const { result } = renderHook(() => useClearAgentMemory("a-1"), { wrapper });

    result.current.mutate();

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/memory?agent_id=a-1"));
  });

  it("reports how many notes went", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue({ notes_deleted: 9, mem0_agents_cleared: 0 });
    const { result } = renderHook(() => useClearAgentMemory("a-1"), { wrapper });

    result.current.mutate();

    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(String(toastSuccess.mock.calls[0]?.[0])).toContain("9");
  });

  it("shows a refusal", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("nope"));
    const { result } = renderHook(() => useClearAgentMemory("a-1"), { wrapper });

    result.current.mutate();

    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });
});
