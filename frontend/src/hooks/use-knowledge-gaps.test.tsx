import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useAddKnowledgeGapToDataset,
  useKnowledgeGap,
  useKnowledgeGaps,
  useRegroupKnowledgeGaps,
  useSetKnowledgeGapStatus,
} from "./use-knowledge-gaps";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
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
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useKnowledgeGaps", () => {
  it("lists every knowledge base the caller reads, open topics first page by default", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "t1", label: "parental leave" }],
      total: 7,
      ungrouped: 3,
    });
    const { result } = renderHook(() => useKnowledgeGaps({ kind: "organization" }), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/knowledge-gaps?status=open&skip=0&limit=50");
    expect(result.current.topics[0]?.label).toBe("parental leave");
    expect(result.current.total).toBe(7);
    expect(result.current.ungrouped).toBe(3);
  });

  it("asks one knowledge base, or one agent, for the status and page given", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0, ungrouped: 0 });
    renderHook(
      () => useKnowledgeGaps({ kind: "collection", id: "kb1" }, { status: "dismissed", skip: 50 }),
      { wrapper },
    );
    renderHook(() => useKnowledgeGaps({ kind: "agent", id: "a1" }, { limit: 5 }), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    expect(apiClient.get).toHaveBeenCalledWith(
      "/knowledge-gaps/collections/kb1?status=dismissed&skip=50&limit=50",
    );
    expect(apiClient.get).toHaveBeenCalledWith(
      "/knowledge-gaps/agents/a1?status=open&skip=0&limit=5",
    );
  });

  it("reads an empty answer as nothing rather than throwing", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(undefined);
    const { result } = renderHook(() => useKnowledgeGaps({ kind: "organization" }), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(result.current.topics).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(result.current.ungrouped).toBe(0);
  });
});

describe("useKnowledgeGap", () => {
  it("reads one topic with its questions", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "t1", questions: [] });
    const { result } = renderHook(() => useKnowledgeGap("t1"), { wrapper });
    await waitFor(() => expect(result.current.topic?.id).toBe("t1"));
    expect(apiClient.get).toHaveBeenCalledWith("/knowledge-gaps/t1");
  });
});

describe("the topic mutations", () => {
  it("dismisses a topic and reopens it, saying which", async () => {
    const { result } = renderHook(() => useSetKnowledgeGapStatus(), { wrapper });
    vi.mocked(apiClient.post).mockResolvedValueOnce({ id: "t1", status: "dismissed" });
    await result.current.mutateAsync({ topicId: "t1", status: "dismissed" });
    expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/t1/dismiss");
    expect(toastSuccess).toHaveBeenCalledWith("Topic dismissed");

    vi.mocked(apiClient.post).mockResolvedValueOnce({ id: "t1", status: "open" });
    await result.current.mutateAsync({ topicId: "t1", status: "open" });
    expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/t1/reopen");
    expect(toastSuccess).toHaveBeenCalledWith("Topic reopened");
  });

  it("says why when the server refuses a status change", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("nope"));
    const { result } = renderHook(() => useSetKnowledgeGapStatus(), { wrapper });
    await expect(
      result.current.mutateAsync({ topicId: "t1", status: "dismissed" }),
    ).rejects.toThrow();
    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });

  it("adds a topic's questions to a dataset and counts what was added and skipped", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      dataset_id: "d1",
      version: 4,
      added: 3,
      skipped: 1,
    });
    const { result } = renderHook(() => useAddKnowledgeGapToDataset(), { wrapper });
    await result.current.mutateAsync({ topicId: "t1", datasetId: "d1", name: "refunds" });
    expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/t1/dataset", {
      dataset_id: "d1",
    });
    expect(toastSuccess).toHaveBeenCalledWith("3 cases added to refunds, 1 question skipped");

    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("nope"));
    await expect(
      result.current.mutateAsync({ topicId: "t1", datasetId: "d1", name: "refunds" }),
    ).rejects.toThrow();
    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });

  it("groups a knowledge base's waiting questions now", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useRegroupKnowledgeGaps("kb1"), { wrapper });
    await result.current.mutateAsync();
    expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/collections/kb1/regroup");
    expect(toastSuccess).toHaveBeenCalledWith(
      "Grouping started. New topics appear in a minute or two.",
    );

    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("nope"));
    await expect(result.current.mutateAsync()).rejects.toThrow();
    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });
});
