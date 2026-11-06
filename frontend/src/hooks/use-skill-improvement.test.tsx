import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import {
  useSkillAccept,
  useSkillImprovements,
  useSkillImprovementsAwaiting,
} from "./use-skill-improvement";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => vi.clearAllMocks());

it("reads main's own sessions, never every line's", async () => {
  vi.mocked(apiClient.get).mockResolvedValue([{ id: "s1" }]);
  const { result } = renderHook(() => useSkillImprovements("k1", { forkId: null, fromRun: null }), {
    wrapper,
  });

  await waitFor(() => expect(result.current.sessions).toHaveLength(1));
  expect(apiClient.get).toHaveBeenCalledWith("/skills/k1/improvements", {
    params: { main: "true" },
  });
});

it("reads the skill sessions waiting for a person across the organization", async () => {
  vi.mocked(apiClient.get).mockResolvedValue([{ id: "s1" }]);
  const { result } = renderHook(() => useSkillImprovementsAwaiting(), { wrapper });

  await waitFor(() => expect(result.current.sessions).toHaveLength(1));
  expect(apiClient.get).toHaveBeenCalledWith("/skill-improvements/awaiting");
});

it("does not read the waiting sessions for a card that is not shown", () => {
  renderHook(() => useSkillImprovementsAwaiting({ enabled: false }), { wrapper });
  expect(apiClient.get).not.toHaveBeenCalled();
});

it("reads the agents again once an attempt is applied or forked, since both move agents", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({});
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const { result } = renderHook(() => useSkillAccept("k1", "s1"), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });

  await result.current.fork.mutateAsync({
    name: "Returns",
    agent_ids: [],
    acknowledge_unknown: false,
  });

  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["agents"] });
});
