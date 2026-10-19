import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useExternalAgents } from "./use-external-agents";
import * as api from "@/lib/external-agents-api";
import type { ExternalAgent } from "@/types/external-agents";

vi.mock("@/lib/external-agents-api", () => ({
  listExternalAgents: vi.fn(),
  registerExternalAgent: vi.fn(),
  refreshExternalAgent: vi.fn(),
  deleteExternalAgent: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const AGENT = { id: "ea-1", slug: "reviewer", name: "Reviewer" } as ExternalAgent;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listExternalAgents).mockResolvedValue([AGENT]);
  vi.mocked(api.registerExternalAgent).mockResolvedValue(AGENT);
  vi.mocked(api.refreshExternalAgent).mockResolvedValue(AGENT);
  vi.mocked(api.deleteExternalAgent).mockResolvedValue(undefined);
});

describe("useExternalAgents", () => {
  it("lists the registered agents, and lists again after each write", async () => {
    const { result } = renderHook(() => useExternalAgents(), { wrapper });
    await waitFor(() => expect(result.current.agents).toEqual([AGENT]));

    await act(async () => {
      await result.current.register({ card_url: "https://agents.example.com" });
      await result.current.refresh("ea-1");
      await result.current.remove("ea-1");
    });

    expect(api.refreshExternalAgent).toHaveBeenCalledWith("ea-1");
    expect(api.deleteExternalAgent).toHaveBeenCalledWith("ea-1");
    expect(vi.mocked(api.listExternalAgents).mock.calls.length).toBeGreaterThan(1);
  });

  it("says when the list could not be read", async () => {
    vi.mocked(api.listExternalAgents).mockRejectedValue(new Error("down"));
    const { result } = renderHook(() => useExternalAgents(), { wrapper });

    await waitFor(() => expect(result.current.error).not.toBeNull());
  });

  it("asks for nothing when it is not wanted", () => {
    const { result } = renderHook(() => useExternalAgents(false), { wrapper });

    expect(result.current.isLoading).toBe(false);
    expect(api.listExternalAgents).not.toHaveBeenCalled();
  });
});
