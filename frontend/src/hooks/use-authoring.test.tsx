import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { agentAuthoring, authoringRequest } from "@/test-utils/authoring";

import {
  AUTHORING_POLL_MS,
  useAgentAuthoring,
  useSkillAuthoring,
  useWaitingSuggestions,
} from "./use-authoring";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.post).mockReset();
});

describe("useAgentAuthoring", () => {
  it("reads the agent's suggestions, and again while a request is worked on", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(
      agentAuthoring({ latest: authoringRequest({ status: "running" }) }),
    );
    const { result } = renderHook(() => useAgentAuthoring("agent-1"), { wrapper });
    await waitFor(() => expect(result.current.authoring?.latest?.status).toBe("running"));
    expect(apiClient.get).toHaveBeenCalledWith("/agents/agent-1/authoring");
    const query = client.getQueryCache().find({ queryKey: qk.authoring.agent("agent-1") });
    const interval = (query?.options as { refetchInterval: (q: unknown) => number | false })
      .refetchInterval;
    expect(interval(query)).toBe(AUTHORING_POLL_MS);
    expect(interval({ state: { data: agentAuthoring() } })).toBe(false);
  });

  it("estimates, starts, decides, dismisses and checks through the agent's routes", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(agentAuthoring());
    const decided = { authoring: agentAuthoring({ batch: null }), draft_spec: { name: "x" } };
    vi.mocked(apiClient.post).mockImplementation(async (url: string) =>
      url.endsWith("/hunks/h1")
        ? decided
        : url.endsWith("/dismiss")
          ? agentAuthoring({ batch: null })
          : {},
    );
    const { result } = renderHook(() => useAgentAuthoring("agent-1"), { wrapper });
    await act(async () => {
      await result.current.estimate.mutateAsync({ kind: "improve", window_days: 30 });
      await result.current.start.mutateAsync({ kind: "verify", window_days: 7 });
      await result.current.decide.mutateAsync({ hunkId: "h1", action: "accept" });
      await result.current.dismissAll.mutateAsync();
      await result.current.checkEstimate.mutateAsync({ dataset_id: "ds" });
      await result.current.check.mutateAsync({ dataset_id: "ds" });
    });
    expect(vi.mocked(apiClient.post).mock.calls.map(([url]) => url)).toEqual([
      "/agents/agent-1/authoring/estimate",
      "/agents/agent-1/authoring",
      "/agents/agent-1/authoring/hunks/h1",
      "/agents/agent-1/authoring/dismiss",
      "/agents/agent-1/authoring/check/estimate",
      "/agents/agent-1/authoring/check",
    ]);
    expect(vi.mocked(apiClient.post).mock.calls[2]?.[1]).toEqual({ action: "accept" });
  });
});

describe("useSkillAuthoring", () => {
  it("reads a skill's requests, polls while one works, and starts and checks", async () => {
    vi.mocked(apiClient.get).mockResolvedValue([authoringRequest({ status: "queued" })]);
    vi.mocked(apiClient.post).mockResolvedValue({});
    const { result } = renderHook(() => useSkillAuthoring("skill-1"), { wrapper });
    await waitFor(() => expect(result.current.latest?.status).toBe("queued"));
    const query = client.getQueryCache().find({ queryKey: qk.authoring.skill("skill-1") });
    const interval = (query?.options as { refetchInterval: (q: unknown) => number | false })
      .refetchInterval;
    expect(interval(query)).toBe(AUTHORING_POLL_MS);
    expect(interval({ state: { data: [] } })).toBe(false);
    await act(async () => {
      await result.current.estimate.mutateAsync({ kind: "improve", window_days: 30 });
      await result.current.start.mutateAsync({ kind: "improve", window_days: 30 });
      await result.current.checkEstimate.mutateAsync({ dataset_id: "ds", proposal_id: "p" });
      await result.current.check.mutateAsync({ dataset_id: "ds", proposal_id: "p" });
    });
    expect(vi.mocked(apiClient.post).mock.calls.map(([url]) => url)).toEqual([
      "/skills/skill-1/authoring/estimate",
      "/skills/skill-1/authoring",
      "/skills/skill-1/authoring/check/estimate",
      "/skills/skill-1/authoring/check",
    ]);
  });

  it("reads the waiting changes again when the request it is on finishes", async () => {
    const running = authoringRequest({ id: "r-1", status: "running" });
    vi.mocked(apiClient.get).mockResolvedValue([running]);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSkillAuthoring("skill-1"), { wrapper });
    await waitFor(() => expect(result.current.latest?.status).toBe("running"));
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: qk.skillChanges.all() });

    vi.mocked(apiClient.get).mockResolvedValue([{ ...running, status: "completed" }]);
    await act(async () => {
      await client.refetchQueries({ queryKey: qk.authoring.skill("skill-1") });
    });

    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.skillChanges.all() }),
    );
  });

  it("answers nothing before it reads", () => {
    const { result } = renderHook(() => useSkillAuthoring("skill-1", { enabled: false }), {
      wrapper,
    });
    expect(result.current.requests).toEqual([]);
    expect(result.current.latest).toBeNull();
  });
});

describe("useWaitingSuggestions", () => {
  it("reads what waits on the caller", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ agents: [], skills: 2 });
    const { result } = renderHook(() => useWaitingSuggestions(), { wrapper });
    await waitFor(() => expect(result.current.waiting).toEqual({ agents: [], skills: 2 }));
    expect(apiClient.get).toHaveBeenCalledWith("/authoring/waiting");
  });
});
