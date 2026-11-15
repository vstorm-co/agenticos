import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ruleCounts,
  useEvalTry,
  useFailureLearning,
  useOrgPatterns,
  useProposal,
} from "./use-failure-learning";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { toast } from "sonner";
import type { FailurePattern } from "@/lib/failure-learning-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const emptyList = { items: [], total: 0 };
const pattern: FailurePattern = {
  agent_id: "agent-1",
  agent_name: "Helper",
  model: null,
  status: "failed",
  error_class: "other",
  pattern_key: "failed:other",
  count: 3,
  first_seen: "2026-11-13T00:00:00Z",
  last_seen: "2026-11-14T00:00:00Z",
  sample_run_ids: ["run-1"],
  sample_message_ids: ["message-1"],
  already_tracked: false,
};

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/failure-learning/patterns") return { items: [], total: 0, notes: [] };
    if (path.endsWith("/patterns")) return { items: [], total: 0, notes: [] };
    if (path.endsWith("/ledger")) return emptyList;
    if (path.endsWith("/eval-cases")) return emptyList;
    if (path.endsWith("/proposals")) return emptyList;
    if (path.includes("/eval-runs/"))
      return { id: "try-1", agent_id: "agent-1", cases: [], passed: 0, failed: 0, pending: 0 };
    if (path.includes("/proposals/")) return { id: "prop-1", status: "draft" };
    throw new Error(`unexpected GET ${path}`);
  });
  vi.mocked(apiClient.post).mockResolvedValue({ id: "new-1" });
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "entry-1" });
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

describe("useFailureLearning", () => {
  it.each(["accepted", "refused"] as const)(
    "reverts a proposal only after an %s server response",
    async (outcome) => {
      const { client, wrapper } = setup();
      const current = qk.failureLearning.proposal("agent-1", "prop-1");
      const other = qk.failureLearning.proposal("agent-2", "prop-2");
      client.setQueryData(current, { id: "prop-1", status: "applied" });
      client.setQueryData(other, { id: "prop-2", status: "applied" });
      const invalidate = vi.spyOn(client, "invalidateQueries");
      const { result, unmount } = renderHook(() => useFailureLearning("agent-1"), { wrapper });
      await waitFor(() => expect(result.current.patternsLoading).toBe(false));
      const failure = new ApiError(409, "The skill changed after this proposal");
      if (outcome === "refused") vi.mocked(apiClient.post).mockRejectedValueOnce(failure);

      try {
        await act(async () => {
          const reverting = result.current.revert.mutateAsync("prop-1");
          if (outcome === "refused") await expect(reverting).rejects.toBe(failure);
          else await expect(reverting).resolves.toEqual({ id: "new-1" });
        });
        expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
          "/agents/agent-1/failure-learning/proposals/prop-1/revert",
        );
        expect(client.getQueryState(other)?.isInvalidated).toBe(false);
        if (outcome === "accepted") {
          expect(invalidate).toHaveBeenCalledExactlyOnceWith({
            queryKey: ["failure-learning", "agents", "agent-1"],
          });
          expect(client.getQueryState(current)?.isInvalidated).toBe(true);
          expect(toast.success).toHaveBeenCalledTimes(1);
          expect(toast.error).not.toHaveBeenCalled();
        } else {
          expect(invalidate).not.toHaveBeenCalled();
          expect(client.getQueryState(current)?.isInvalidated).toBe(false);
          expect(toast.error).toHaveBeenCalledTimes(1);
          expect(toast.success).not.toHaveBeenCalled();
        }
      } finally {
        unmount();
        client.clear();
      }
    },
  );

  it("reads the agent's patterns, ledger, cases and proposals", async () => {
    const { result } = renderHook(() => useFailureLearning("agent-1"), { wrapper });

    await waitFor(() => expect(result.current.patternsLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/agents/agent-1/failure-learning/patterns");
    expect(apiClient.get).toHaveBeenCalledWith("/agents/agent-1/failure-learning/ledger", {
      params: undefined,
    });
    expect(apiClient.get).toHaveBeenCalledWith("/agents/agent-1/failure-learning/eval-cases");
    expect(apiClient.get).toHaveBeenCalledWith("/agents/agent-1/failure-learning/proposals", {
      params: undefined,
    });
  });

  it("writes through every mutation", async () => {
    const { result } = renderHook(() => useFailureLearning("agent-1"), { wrapper });
    await waitFor(() => expect(result.current.patternsLoading).toBe(false));

    const pattern = {
      agent_id: "agent-1",
      agent_name: "Helper",
      model: null,
      status: "failed",
      error_class: "other",
      pattern_key: "failed:other",
      count: 3,
      first_seen: null,
      last_seen: null,
      sample_run_ids: ["run-1"],
      sample_message_ids: [],
      already_tracked: false,
    };
    result.current.track.mutate({ pattern, input: { title: "T", summary: "S" } });
    result.current.createEntry.mutate({
      scope: "agent",
      pattern_key: "failed:other",
      title: "T",
      summary: "S",
      evidence: {},
    });
    result.current.updateEntry.mutate({ entryId: "entry-1", input: { status: "open" } });
    result.current.removeEntry.mutate("entry-1");
    result.current.createCase.mutate({
      name: "C",
      input: { message: "hi" },
      expectation: { kind: "contains", field: "text", value: "hi" },
    });
    result.current.removeCase.mutate("case-1");
    result.current.createProposal.mutate({
      target: { type: "instructions" },
      old_text: "old",
      new_text: "new",
      rationale: "why",
    });
    result.current.apply.mutate("prop-1");
    result.current.reject.mutate({ proposalId: "prop-1", reason: "no" });
    result.current.startTry.mutate({ case_ids: ["case-1"] });

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(7));
    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/agent-1/failure-learning/ledger",
      expect.objectContaining({ scope: "agent" }),
    );
    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/agent-1/failure-learning/proposals/prop-1/apply",
    );
    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/agent-1/failure-learning/proposals/prop-1/reject",
      { reason: "no" },
    );
    expect(apiClient.post).toHaveBeenCalledWith("/agents/agent-1/failure-learning/eval-runs", {
      case_ids: ["case-1"],
    });
    expect(apiClient.patch).toHaveBeenCalledWith(
      "/agents/agent-1/failure-learning/ledger/entry-1",
      { status: "open" },
    );
    expect(apiClient.delete).toHaveBeenCalledWith(
      "/agents/agent-1/failure-learning/ledger/entry-1",
    );
    expect(apiClient.delete).toHaveBeenCalledWith(
      "/agents/agent-1/failure-learning/eval-cases/case-1",
    );
  });

  it("toasts a mutation failure", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("nope"));
    const { result } = renderHook(() => useFailureLearning("agent-1"), { wrapper });
    await waitFor(() => expect(result.current.patternsLoading).toBe(false));

    result.current.createEntry.mutate({
      scope: "agent",
      pattern_key: "failed:other",
      title: "T",
      summary: "S",
      evidence: {},
    });

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });
});

describe("useOrgPatterns", () => {
  it.each(["accepted", "refused"] as const)(
    "tracks an organization pattern with an %s server response",
    async (outcome) => {
      const { client, wrapper } = setup();
      const firstAgent = qk.failureLearning.agentPatterns("agent-1");
      const secondAgent = qk.failureLearning.ledger("agent-2");
      const unrelated = qk.providers.modelProfiles();
      client.setQueryData(firstAgent, { items: [pattern], total: 1, notes: [] });
      client.setQueryData(secondAgent, emptyList);
      client.setQueryData(unrelated, []);
      const invalidate = vi.spyOn(client, "invalidateQueries");
      const { result, unmount } = renderHook(() => useOrgPatterns(), { wrapper });
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      const failure = new ApiError(403, "This pattern is read-only for this member");
      if (outcome === "refused") vi.mocked(apiClient.post).mockRejectedValueOnce(failure);
      try {
        await act(async () => {
          const tracking = result.current.track.mutateAsync({
            pattern,
            input: { title: "Check failures", summary: "Keep the verified evidence" },
          });
          if (outcome === "refused") await expect(tracking).rejects.toBe(failure);
          else await expect(tracking).resolves.toEqual({ id: "new-1" });
        });
        expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
          "/agents/agent-1/failure-learning/ledger",
          {
            title: "Check failures",
            summary: "Keep the verified evidence",
            scope: "agent",
            model: null,
            pattern_key: pattern.pattern_key,
            evidence: {
              run_ids: ["run-1"],
              message_ids: ["message-1"],
              count: 3,
              window: { from: pattern.first_seen, to: pattern.last_seen },
              error_class: "other",
            },
          },
        );
        expect(client.getQueryState(unrelated)?.isInvalidated).toBe(false);
        if (outcome === "accepted") {
          expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.failureLearning.orgPatterns() });
          expect(invalidate).toHaveBeenCalledWith({ queryKey: ["failure-learning", "agents"] });
          expect(client.getQueryState(firstAgent)?.isInvalidated).toBe(true);
          expect(client.getQueryState(secondAgent)?.isInvalidated).toBe(true);
          expect(toast.error).not.toHaveBeenCalled();
        } else {
          expect(invalidate).not.toHaveBeenCalled();
          expect(client.getQueryState(firstAgent)?.isInvalidated).toBe(false);
          expect(client.getQueryState(secondAgent)?.isInvalidated).toBe(false);
          expect(toast.error).toHaveBeenCalledTimes(1);
        }
      } finally {
        unmount();
        client.clear();
      }
    },
  );

  it("reads the org patterns and tracks one", async () => {
    const { result } = renderHook(() => useOrgPatterns(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/failure-learning/patterns");
  });
});

describe("useEvalTry", () => {
  it("reads a try, and reads nothing without an id", async () => {
    const { result, rerender } = renderHook(
      ({ id }: { id: string | null }) => useEvalTry("agent-1", id),
      {
        wrapper,
        initialProps: { id: "try-1" as string | null },
      },
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.try?.id).toBe("try-1");

    rerender({ id: null });
    expect(result.current.try).toBeNull();
  });
});

describe("useProposal", () => {
  it("reads a proposal, and nothing without an id", async () => {
    const { result, rerender } = renderHook(
      ({ id }: { id: string | null }) => useProposal("agent-1", id),
      { wrapper, initialProps: { id: "prop-1" as string | null } },
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.proposal?.id).toBe("prop-1");

    rerender({ id: null });
    expect(result.current.proposal).toBeNull();
  });
});

describe("ruleCounts", () => {
  it("counts open entries, resolved entries and applied proposals separately", () => {
    expect(
      ruleCounts(
        [{ status: "open" }, { status: "resolved" }, { status: "draft" }, { status: "dismissed" }],
        [{ status: "applied" }, { status: "draft" }],
      ),
    ).toEqual({ openEntries: 2, resolvedEntries: 1, appliedProposals: 1 });
  });
});
