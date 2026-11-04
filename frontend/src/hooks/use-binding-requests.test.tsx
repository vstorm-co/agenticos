import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useBindingRequests, useChannelBindingRequests } from "./use-binding-requests";
import { apiClient } from "@/lib/api-client";
import type { BindingRequest } from "@/types/channels";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function request(overrides: Partial<BindingRequest> = {}): BindingRequest {
  return {
    id: "r1",
    kind: "bind",
    status: "pending",
    void_reason: null,
    agent_id: "a1",
    agent_name: "Front desk",
    channel_bot_id: "b1",
    channel_bot_name: "Shop line",
    exposure_id: null,
    environment_id: null,
    session_scope: null,
    requester_user_id: "u1",
    requester_email: "ana@example.com",
    note: "For the shop",
    decided_by_user_id: null,
    decided_at: null,
    created_at: "2026-11-04T09:00:00Z",
    ...overrides,
  };
}

beforeEach(() => vi.clearAllMocks());

describe("one agent's binding requests", () => {
  it("reads them, and nothing without an agent", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [request()], total: 1 });

    const none = renderHook(() => useBindingRequests(null), { wrapper });
    expect(none.result.current.fetchStatus).toBe("idle");

    const { result } = renderHook(() => useBindingRequests("a1"), { wrapper });

    await waitFor(() => expect(result.current.data).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/binding-requests");
  });
});

describe("the organization's binding requests", () => {
  it("does not fetch for somebody who cannot decide them", () => {
    renderHook(() => useChannelBindingRequests(false), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("lists the pending ones", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [request()], total: 1 });

    const { result } = renderHook(() => useChannelBindingRequests(true), { wrapper });

    await waitFor(() => expect(result.current.requests).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/channels/binding-requests");
  });

  it("is empty before it has answered", () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => undefined));

    const { result } = renderHook(() => useChannelBindingRequests(true), { wrapper });

    expect(result.current.requests).toEqual([]);
    expect(result.current.isLoading).toBe(true);
  });

  it("approves one, says so, and re-reads the list and the bindings", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [request()], total: 1 });
    vi.mocked(apiClient.post).mockResolvedValue(request({ status: "approved" }));
    const { result } = renderHook(() => useChannelBindingRequests(true), { wrapper });
    await waitFor(() => expect(result.current.requests).toHaveLength(1));

    await result.current.approve.mutateAsync("r1");

    expect(apiClient.post).toHaveBeenCalledWith("/channels/binding-requests/r1/approve", {});
    expect(toast.success).toHaveBeenCalledWith("Request approved");
    await waitFor(() => expect(vi.mocked(apiClient.get).mock.calls.length).toBeGreaterThan(1));
  });

  it("declines one", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue(request({ status: "declined" }));
    const { result } = renderHook(() => useChannelBindingRequests(true), { wrapper });

    await result.current.decline.mutateAsync("r1");

    expect(apiClient.post).toHaveBeenCalledWith("/channels/binding-requests/r1/decline", {});
    expect(toast.success).toHaveBeenCalledWith("Request declined");
  });

  it("shows the server's refusal of either decision", async () => {
    const { toast } = await import("sonner");
    const refused = new Error("The bot has moved on");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockRejectedValue(refused);
    const { result } = renderHook(() => useChannelBindingRequests(true), { wrapper });

    await expect(result.current.approve.mutateAsync("r1")).rejects.toThrow(refused);
    await expect(result.current.decline.mutateAsync("r1")).rejects.toThrow(refused);

    expect(toast.error).toHaveBeenCalledTimes(2);
  });
});
